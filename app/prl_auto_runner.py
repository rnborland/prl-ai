import os
import json
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

import pandas as pd
import requests


# =========================================================
# Config
# =========================================================
BACKEND_BASE_URL = (os.environ.get("BACKEND_BASE_URL") or "").strip().rstrip("/")
if not BACKEND_BASE_URL.startswith("http"):
    raise RuntimeError(f"BACKEND_BASE_URL looks wrong: {BACKEND_BASE_URL!r}")

API_KEY = os.environ.get("PRL_API_KEY", "").strip()
if not API_KEY:
    raise RuntimeError("Missing PRL_API_KEY")

PROCESS_PDF_ID = os.environ.get("PRL_PROCESS_PDF_ID", "").strip()
if not PROCESS_PDF_ID:
    raise RuntimeError("Missing PRL_PROCESS_PDF_ID")

MODEL_NAME = os.environ.get("PRL_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

CONTROL_PLAN_PATH = os.environ.get("PRL_CONTROL_PLAN_PATH", "/srv/PRL-ui/control_plan.csv").strip()
INFLUX_URL = os.environ.get("INFLUX_URL", "http://127.0.0.1:8086/query").strip()
INFLUX_DB = os.environ.get("INFLUX_DB", "demo_iot").strip()

ASSET_NAME = os.environ.get("PRL_ASSET_NAME", "Demo Asset").strip()
ASSET_TYPE = os.environ.get("PRL_ASSET_TYPE", "Machine / Facility / Process / Installation").strip()
PROCESS_DESC = os.environ.get(
    "PRL_PROCESS_DESC",
    "Steady-state monitored process with defined control limits.",
).strip()

SYSTEM_PROMPT = os.environ.get(
    "PRL_SYSTEM_PROMPT",
    (
        "You are an assistant to the control room operator. "
        "Identify any drift from normal behavior, summarize the current state, "
        "and provide clear, practical guidance based on the control plan."
    ),
).strip()

OPERATOR_NOTES = os.environ.get("PRL_NOTES", "").strip()

LOOKBACK_HOURS = int(os.environ.get("PRL_LOOKBACK_HOURS", "8"))
DISPLAY_TIMEZONE = os.environ.get("PRL_TIMEZONE", "UTC").strip()

LOG_DIR = os.environ.get("PRL_LOG_DIR", "/srv/PRL-ui/logs").strip()
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "PRL_auto_runner.log")
LATEST_STATE_PATH = os.path.join(LOG_DIR, "latest_PRL_explanation.json")

# =========================================================
# Helpers
# =========================================================

def write_latest_state(payload: Dict[str, Any]) -> None:
    with open(LATEST_STATE_PATH, "w") as f:
        json.dump(payload, f, indent=2)


def load_latest_state() -> Dict[str, Any]:
    if not os.path.exists(LATEST_STATE_PATH):
        return {}
    try:
        with open(LATEST_STATE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def safe_float(v: Any) -> Optional[float]:
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(v)
    except Exception:
        return None


def yesno_to_bool(v: Any) -> bool:
    return str(v).strip().lower() in {"yes", "true", "1", "y"}


def fmt_num(x: Any, nd: int = 2) -> str:
    try:
        if x is None or str(x).strip() == "":
            return "—"
        return f"{float(x):.{nd}f}"
    except Exception:
        return "—"


def split_semicolon_steps(text: str) -> List[str]:
    return [s.strip() for s in str(text).split(";") if s.strip()]


def log_json(payload: Dict[str, Any]) -> None:
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(payload, indent=2))
        f.write("\n")


# =========================================================
# Influx helpers
# =========================================================
def influx_query(q: str, db: str = INFLUX_DB, timeout: int = 15) -> Dict[str, Any]:
    r = requests.get(INFLUX_URL, params={"db": db, "q": q}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def influx_latest_value(measurement: str) -> Optional[float]:
    q = f"SELECT last(value) FROM {measurement}"
    resp = influx_query(q)

    results = resp.get("results", [])
    if not results:
        return None

    series = results[0].get("series", [])
    if not series:
        return None

    values = series[0].get("values", [])
    if not values:
        return None

    return safe_float(values[0][1])


def influx_stats_window(measurement: str, window_hours: int) -> Dict[str, Optional[float]]:
    q = (
        f"SELECT min(value) AS vmin, max(value) AS vmax, mean(value) AS vavg "
        f"FROM {measurement} WHERE time > now() - {window_hours}h"
    )
    resp = influx_query(q)

    results = resp.get("results", [])
    if not results:
        return {"min": None, "max": None, "avg": None}

    series = results[0].get("series", [])
    if not series:
        return {"min": None, "max": None, "avg": None}

    values = series[0].get("values", [])
    if not values:
        return {"min": None, "max": None, "avg": None}

    row = values[0]
    return {
        "min": safe_float(row[1]),
        "max": safe_float(row[2]),
        "avg": safe_float(row[3]),
    }


# =========================================================
# Control plan helpers
# =========================================================
def load_control_plan(path: str) -> pd.DataFrame:
    df = pd.read_csv(path).fillna("")
    required_cols = [
        "tag_name",
        "display_name",
        "description",
        "measurement",
        "unit",
        "sampling_interval_sec",
        "lower_limit",
        "upper_limit",
        "warning_low",
        "warning_high",
        "priority",
        "expected_pattern",
        "reaction_plan",
        "document_reference",
        "missing_data_action",
        "enabled",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing control plan columns: {missing}")
    return df


def evaluate_status(latest: Optional[float], row: pd.Series) -> str:
    if latest is None:
        return "nodata"

    lower_limit = safe_float(row["lower_limit"])
    upper_limit = safe_float(row["upper_limit"])
    warning_low = safe_float(row["warning_low"])
    warning_high = safe_float(row["warning_high"])

    if lower_limit is not None and latest < lower_limit:
        return "bad"
    if upper_limit is not None and latest > upper_limit:
        return "bad"
    if warning_low is not None and latest < warning_low:
        return "warn"
    if warning_high is not None and latest > warning_high:
        return "warn"

    return "ok"


def compute_global_status(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "nodata"
    if any(r["status"] == "bad" for r in rows):
        return "bad"
    if any(r["status"] == "warn" for r in rows):
        return "warn"
    if any(r["status"] == "nodata" for r in rows):
        return "nodata"
    return "ok"


# =========================================================
# API helpers
# =========================================================
def api_post_json(path: str, payload: dict, timeout: int = 120) -> Dict[str, Any]:
    r = requests.post(
        f"{BACKEND_BASE_URL}{path}",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"POST {path} -> {r.status_code}: {r.text}")
    return r.json()


def build_explanation_message(
    asset_name: str,
    asset_type: str,
    process_desc: str,
    operator_notes: str,
    channel_rows: List[Dict[str, Any]],
    lookback_hours: int,
    ts_local: str,
    timezone_name: str,
) -> str:
    problem_rows = [r for r in channel_rows if r["status"] in {"warn", "bad", "nodata"}]

    lines: List[str] = []
    lines.append(f"Asset / Process Name: {asset_name}")
    lines.append(f"Asset Type: {asset_type}")
    lines.append(f"Process Description: {process_desc}")
    lines.append(f"Current Time: {ts_local} ({timezone_name})")
    lines.append(f"Look-Back Window: last {lookback_hours} hours")
    lines.append("")

    if operator_notes.strip():
        lines.append("Operator Notes:")
        lines.append(operator_notes.strip())
        lines.append("")

    if not problem_rows:
        lines.append("All monitored variables are currently within warning and control limits.")
        lines.append("Provide a short summary of the current process state and what to continue watching.")
        return "\n".join(lines)

    lines.append("Variables requiring attention:")
    for r in problem_rows:
        lines.append(f"- {r['display_name']}")
        lines.append(f"  Status: {r['status'].upper()}")
        lines.append(f"  Current Value: {fmt_num(r['latest'], 2)} {r['unit']}")
        lines.append(
            f"  Look-back stats: min={fmt_num(r['stats_window'].get('min'))}, "
            f"max={fmt_num(r['stats_window'].get('max'))}, "
            f"avg={fmt_num(r['stats_window'].get('avg'))}"
        )
        lines.append(
            f"  Limits: lower={r['lower_limit']}, upper={r['upper_limit']}, "
            f"warning_low={r['warning_low']}, warning_high={r['warning_high']}"
        )
        lines.append(f"  Description: {r['description']}")
        lines.append(f"  Expected Pattern: {r['expected_pattern']}")
        if r["status"] == "nodata":
            lines.append(f"  Missing Data Action: {r['missing_data_action']}")
        else:
            lines.append(f"  Reaction Plan: {r['reaction_plan']}")
        lines.append(f"  Document Reference: {r['document_reference']}")
        lines.append("")

    lines.append("Instructions:")
    lines.append(
        "Using the attached process and equipment documentation together with the control-plan information above, "
        "provide a concise operator-focused explanation of the current state."
    )
    lines.append(
        "The control plan is the source of truth for limits and actions. Do not invent limits or override the control plan."
    )
    lines.append(
        "Explain: 1) what is outside normal or drifting, 2) what it likely means in process terms, "
        "3) what to check first based on the reaction plan, 4) whether this is urgent or watch-and-monitor."
    )

    return "\n".join(lines)


def explain_current_state(
    asset_name: str,
    asset_type: str,
    process_desc: str,
    operator_notes: str,
    channel_rows: List[Dict[str, Any]],
    lookback_hours: int,
    ts_local: str,
    timezone_name: str,
) -> Dict[str, Any]:
    session_id = str(uuid.uuid4())

    message = build_explanation_message(
        asset_name=asset_name,
        asset_type=asset_type,
        process_desc=process_desc,
        operator_notes=operator_notes,
        channel_rows=channel_rows,
        lookback_hours=lookback_hours,
        ts_local=ts_local,
        timezone_name=timezone_name,
    )

    payload = {
        "session_id": session_id,
        "pdf_id": PROCESS_PDF_ID,
        "message": message,
        "system_prompt": SYSTEM_PROMPT,
        "model": MODEL_NAME,
    }

    return api_post_json("/chat", payload, timeout=120)


# =========================================================
# Main
# =========================================================
def main() -> None:
    utc_now = datetime.now(timezone.utc)
    local_now = utc_now.astimezone(ZoneInfo(DISPLAY_TIMEZONE))
    ts_local = local_now.strftime("%Y-%m-%d %H:%M:%S")

    cp = load_control_plan(CONTROL_PLAN_PATH)
    cp = cp[cp["enabled"].apply(yesno_to_bool)].copy()

    channel_rows: List[Dict[str, Any]] = []

    for _, row in cp.iterrows():
        measurement = str(row["measurement"]).strip()

        try:
            latest = influx_latest_value(measurement)
        except Exception:
            latest = None

        try:
            stats_window = influx_stats_window(measurement, LOOKBACK_HOURS)
        except Exception:
            stats_window = {"min": None, "max": None, "avg": None}

        status = evaluate_status(latest, row)

        channel_rows.append({
            "tag_name": row["tag_name"],
            "display_name": row["display_name"],
            "description": row["description"],
            "measurement": row["measurement"],
            "unit": row["unit"],
            "sampling_interval_sec": row["sampling_interval_sec"],
            "lower_limit": row["lower_limit"],
            "upper_limit": row["upper_limit"],
            "warning_low": row["warning_low"],
            "warning_high": row["warning_high"],
            "priority": row["priority"],
            "expected_pattern": row["expected_pattern"],
            "reaction_plan": row["reaction_plan"],
            "document_reference": row["document_reference"],
            "missing_data_action": row["missing_data_action"],
            "latest": latest,
            "stats_window": stats_window,
            "status": status,
        })

    global_status = compute_global_status(channel_rows)

    resp = explain_current_state(
        asset_name=ASSET_NAME,
        asset_type=ASSET_TYPE,
        process_desc=PROCESS_DESC,
        operator_notes=OPERATOR_NOTES,
        channel_rows=channel_rows,
        lookback_hours=LOOKBACK_HOURS,
        ts_local=ts_local,
        timezone_name=DISPLAY_TIMEZONE,
    )

    out = {
        "ts_local": ts_local,
        "timezone": DISPLAY_TIMEZONE,
        "lookback_hours": LOOKBACK_HOURS,
        "asset_name": ASSET_NAME,
        "global_status": global_status,
        "channel_rows": channel_rows,
        "answer": resp.get("answer"),
        "status": resp.get("status", "ok"),
    }

    log_json(out)

    latest_state = {
        "ts_local": ts_local,
        "timezone": DISPLAY_TIMEZONE,
        "asset_name": ASSET_NAME,
        "global_status": global_status,
        "answer": resp.get("answer", ""),
        "status": resp.get("status", "ok"),
    }

    write_latest_state(latest_state)

if __name__ == "__main__":
    main()
