import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from prl_settings import load_settings


# =========================================================
# Secrets / protected connection settings
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

LOG_DIR = Path(os.environ.get("PRL_LOG_DIR", "/srv/PRL-ui/logs").strip())
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "PRL_auto_runner.log"
LATEST_STATE_PATH = LOG_DIR / "latest_PRL_explanation.json"
SCHEDULE_STATE_PATH = LOG_DIR / "scheduled_reasoning_state.json"


# =========================================================
# General helpers
# =========================================================
def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def yesno_to_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "true", "1", "y"}


def fmt_num(value: Any, ndigits: int = 2) -> str:
    number = safe_float(value)
    return "—" if number is None else f"{number:.{ndigits}f}"


def load_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(temp_path, path)


def log_json(payload: Dict[str, Any]) -> None:
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, indent=2))
        f.write("\n")


def should_run(now_utc: datetime, frequency_minutes: int) -> bool:
    state = load_json(SCHEDULE_STATE_PATH)
    raw = state.get("last_success_utc")

    if not raw:
        return True

    try:
        last_success = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=timezone.utc)
    except ValueError:
        return True

    elapsed = now_utc - last_success
    required = timedelta(minutes=max(5, frequency_minutes))

    return elapsed >= required

# =========================================================
# InfluxDB helpers
# =========================================================
def influx_query(influx_url: str, influx_db: str, query: str, timeout: int = 15) -> Dict[str, Any]:
    response = requests.get(influx_url, params={"db": influx_db, "q": query}, timeout=timeout)
    response.raise_for_status()
    return response.json()


def influx_latest_value(influx_url: str, influx_db: str, measurement: str) -> Optional[float]:
    response = influx_query(influx_url, influx_db, f"SELECT last(value) FROM {measurement}")
    series = (response.get("results") or [{}])[0].get("series") or []
    values = series[0].get("values") if series else []
    return safe_float(values[0][1]) if values else None


def influx_stats_window(
    influx_url: str,
    influx_db: str,
    measurement: str,
    window_hours: int,
) -> Dict[str, Optional[float]]:
    query = (
        f"SELECT min(value) AS vmin, max(value) AS vmax, mean(value) AS vavg "
        f"FROM {measurement} WHERE time > now() - {window_hours}h"
    )
    response = influx_query(influx_url, influx_db, query)
    series = (response.get("results") or [{}])[0].get("series") or []
    values = series[0].get("values") if series else []
    if not values:
        return {"min": None, "max": None, "avg": None}
    row = values[0]
    return {"min": safe_float(row[1]), "max": safe_float(row[2]), "avg": safe_float(row[3])}


# =========================================================
# Control-plan and status helpers
# =========================================================
def load_control_plan(path: str) -> pd.DataFrame:
    df = pd.read_csv(path).fillna("")
    required = [
        "tag_name", "display_name", "description", "measurement", "unit",
        "sampling_interval_sec", "lower_limit", "upper_limit", "warning_low",
        "warning_high", "priority", "expected_pattern", "reaction_plan",
        "document_reference", "missing_data_action", "enabled",
    ]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing control plan columns: {missing}")
    return df


def evaluate_value(value: Optional[float], row: pd.Series) -> str:
    if value is None:
        return "nodata"
    lower = safe_float(row["lower_limit"])
    upper = safe_float(row["upper_limit"])
    warning_low = safe_float(row["warning_low"])
    warning_high = safe_float(row["warning_high"])
    if lower is not None and value < lower:
        return "bad"
    if upper is not None and value > upper:
        return "bad"
    if warning_low is not None and value < warning_low:
        return "warn"
    if warning_high is not None and value > warning_high:
        return "warn"
    return "ok"


def evaluate_window(stats: Dict[str, Optional[float]], row: pd.Series) -> str:
    minimum = stats.get("min")
    maximum = stats.get("max")
    if minimum is None and maximum is None:
        return "nodata"
    statuses = [evaluate_value(value, row) for value in (minimum, maximum) if value is not None]
    if "bad" in statuses:
        return "bad"
    if "warn" in statuses:
        return "warn"
    return "ok"


def combine_status(current_status: str, window_status: str) -> str:
    if current_status == "nodata":
        return "nodata"
    if current_status == "bad":
        return "bad"
    if current_status == "warn":
        return "warn"
    if window_status in {"bad", "warn"}:
        return "warn"  # currently recovered, but a recent excursion occurred
    if window_status == "nodata":
        return "nodata"
    return "ok"


def compute_global_status(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "nodata"
    statuses = [row["status"] for row in rows]
    if "bad" in statuses:
        return "bad"
    if "warn" in statuses:
        return "warn"
    if "nodata" in statuses:
        return "nodata"
    return "ok"


# =========================================================
# Reasoning helpers
# =========================================================
def api_post_json(path: str, payload: Dict[str, Any], timeout: int = 120) -> Dict[str, Any]:
    response = requests.post(
        f"{BACKEND_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"POST {path} -> {response.status_code}: {response.text}")
    return response.json()


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
    lines: List[str] = [
        f"Asset / Process Name: {asset_name}",
        f"Asset Type: {asset_type}",
        f"Process Description: {process_desc}",
        f"Current Time: {ts_local} ({timezone_name})",
        f"Look-Back Window: last {lookback_hours} hours",
        "",
    ]

    if operator_notes.strip():
        lines.extend([
            "Operator Notes:",
            operator_notes.strip(),
            "",
        ])

    lines.append("Monitored variables (complete evidence set):")

    for row in channel_rows:
        flags = row["engineering_flags"]

        lines.extend([
            f"- {row['display_name']} ({row['tag_name']})",
            f"  Current value: {fmt_num(row['latest'])} {row['unit']}",
            f"  Current status: {row['current_status'].upper()}",
            f"  Lookback min/max/avg: "
            f"{fmt_num(row['stats_window'].get('min'))} / "
            f"{fmt_num(row['stats_window'].get('max'))} / "
            f"{fmt_num(row['stats_window'].get('avg'))} {row['unit']}",
            f"  Lookback status: {row['window_status'].upper()}",
            f"  Combined operator status: {row['status'].upper()}",
            f"  Limits: lower={row['lower_limit']}, upper={row['upper_limit']}, "
            f"warning_low={row['warning_low']}, warning_high={row['warning_high']}",

            "  AUTHORITATIVE ENGINEERING COMPARISONS:",
            f"    Current below lower control limit: "
            f"{'YES' if flags['current_below_control'] else 'NO'}",
            f"    Current above upper control limit: "
            f"{'YES' if flags['current_above_control'] else 'NO'}",
            f"    Current below warning low: "
            f"{'YES' if flags['current_below_warning'] else 'NO'}",
            f"    Current above warning high: "
            f"{'YES' if flags['current_above_warning'] else 'NO'}",
            f"    Lookback minimum below lower control limit: "
            f"{'YES' if flags['window_below_control'] else 'NO'}",
            f"    Lookback maximum above upper control limit: "
            f"{'YES' if flags['window_above_control'] else 'NO'}",
            f"    Lookback minimum below warning low: "
            f"{'YES' if flags['window_below_warning'] else 'NO'}",
            f"    Lookback maximum above warning high: "
            f"{'YES' if flags['window_above_warning'] else 'NO'}",

            f"  Description: {row['description']}",
            f"  Expected pattern: {row['expected_pattern']}",
            f"  Reaction plan: {row['reaction_plan']}",
            f"  Missing-data action: {row['missing_data_action']}",
            f"  Document reference: {row['document_reference']}",
            "",
        ])

    lines.extend([
        "Instructions:",
        "Use only the monitored variables listed above. "
        "Do not mention variables that are not listed.",

        "Explain both the latest value and the entire lookback window using the "
        "authoritative statuses and engineering comparisons supplied above.",

        "Report only warning or control-limit excursions explicitly marked YES in the "
        "AUTHORITATIVE ENGINEERING COMPARISONS.",

        "Clearly separate: (1) current condition, "
        "(2) recent events or excursions, "
        "(3) likely process meaning, and "
        "(4) practical operator checks.",

        "The control-plan limits and reaction plans above are the source of truth. "
        "Use the attached process documentation for supporting explanation and citations; "
        "do not invent limits.",

        "AUTHORITATIVE STATUS DEFINITIONS:",
        "OK means the value or lookback window remained within warning and control limits.",
        "WARN means a warning threshold was exceeded, but no control limit was exceeded.",
        "BAD means a control limit was exceeded.",
        "NODATA means required telemetry was unavailable.",

        "Use these status definitions exactly.",
        "Never describe a BAD condition as merely a warning.",
        "Never downgrade BAD to WARN in the explanation.",

        "If the current status is OK but the lookback status is BAD, state that the process "
        "has currently recovered but a control-limit excursion occurred during the lookback period.",

        "If the current status is OK but the lookback status is WARN, state that the process "
        "has currently recovered but a warning-threshold excursion occurred during the lookback period.",

        "IMPORTANT NUMERIC RULES:",
        "All threshold comparisons above have already been calculated by PRL code.",
        "Treat the AUTHORITATIVE ENGINEERING COMPARISONS as correct and final.",
        "Do not independently recalculate whether a value is above or below a limit.",
        "Do not contradict the YES/NO engineering comparison results.",
    ])

    return "\n".join(lines)

def main() -> None:
    settings = load_settings()

    frequency_minutes = int(settings["reasoning_frequency_minutes"])

    now_utc = datetime.now(timezone.utc)

    if not should_run(now_utc, frequency_minutes):
        return

    timezone_name = str(settings["timezone"])
    lookback_hours = int(settings["lookback_hours"])

    local_now = now_utc.astimezone(ZoneInfo(timezone_name))
    ts_local = local_now.strftime("%Y-%m-%d %H:%M:%S")
    generated_at_utc = now_utc.isoformat().replace("+00:00", "Z")

    notes_path = Path(str(settings["operator_notes_path"]))

    if notes_path.exists():
        operator_notes = notes_path.read_text(encoding="utf-8")
    else:
        operator_notes = ""

    control_plan = load_control_plan(str(settings["control_plan_path"]))

    control_plan = control_plan[
        control_plan["enabled"].apply(yesno_to_bool)
    ].copy()

    channel_rows: List[Dict[str, Any]] = []

    for _, row in control_plan.iterrows():

        measurement = str(row["measurement"]).strip()

        # -------------------------------------------------
        # Latest value
        # -------------------------------------------------
        try:
            latest = influx_latest_value(
                str(settings["influx_url"]),
                str(settings["influx_db"]),
                measurement,
            )
        except Exception:
            latest = None

        # -------------------------------------------------
        # Lookback statistics
        # -------------------------------------------------
        try:
            stats_window = influx_stats_window(
                str(settings["influx_url"]),
                str(settings["influx_db"]),
                measurement,
                lookback_hours,
            )
        except Exception:
            stats_window = {
                "min": None,
                "max": None,
                "avg": None,
            }

        # -------------------------------------------------
        # Existing deterministic status evaluation
        # -------------------------------------------------
        current_status = evaluate_value(latest, row)

        window_status = evaluate_window(
            stats_window,
            row,
        )

        status = combine_status(
            current_status,
            window_status,
        )

        # -------------------------------------------------
        # Control-plan numeric limits
        # -------------------------------------------------
        lower = safe_float(row["lower_limit"])
        upper = safe_float(row["upper_limit"])

        warning_low = safe_float(row["warning_low"])
        warning_high = safe_float(row["warning_high"])

        window_min = stats_window.get("min")
        window_max = stats_window.get("max")

        # -------------------------------------------------
        # AUTHORITATIVE NUMERIC COMPARISONS
        #
        # These calculations are done by Python so the LLM
        # does not need to decide whether one numeric value
        # is greater or less than another.
        # -------------------------------------------------
        engineering_flags = {

            "current_below_control": (
                latest is not None
                and lower is not None
                and latest < lower
            ),

            "current_above_control": (
                latest is not None
                and upper is not None
                and latest > upper
            ),

            "current_below_warning": (
                latest is not None
                and warning_low is not None
                and latest < warning_low
            ),

            "current_above_warning": (
                latest is not None
                and warning_high is not None
                and latest > warning_high
            ),

            "window_below_control": (
                window_min is not None
                and lower is not None
                and window_min < lower
            ),

            "window_above_control": (
                window_max is not None
                and upper is not None
                and window_max > upper
            ),

            "window_below_warning": (
                window_min is not None
                and warning_low is not None
                and window_min < warning_low
            ),

            "window_above_warning": (
                window_max is not None
                and warning_high is not None
                and window_max > warning_high
            ),
        }

        # -------------------------------------------------
        # Build complete evidence row
        # -------------------------------------------------
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

            "current_status": current_status,

            "window_status": window_status,

            "status": status,

            "engineering_flags": engineering_flags,
        })

    # -----------------------------------------------------
    # Overall PRL status
    # -----------------------------------------------------
    global_status = compute_global_status(channel_rows)

    # -----------------------------------------------------
    # Build AI reasoning message
    # -----------------------------------------------------
    message = build_explanation_message(
        asset_name=str(settings["asset_name"]),
        asset_type=str(settings["asset_type"]),
        process_desc=str(settings["process_description"]),
        operator_notes=operator_notes,
        channel_rows=channel_rows,
        lookback_hours=lookback_hours,
        ts_local=ts_local,
        timezone_name=timezone_name,
    )

    # -----------------------------------------------------
    # Backend request
    # -----------------------------------------------------
    payload = {
        "session_id": str(uuid.uuid4()),
        "pdf_id": PROCESS_PDF_ID,
        "message": message,
        "system_prompt": str(settings["system_prompt"]),
        "model": str(settings["model_name"]),
    }

    response = api_post_json(
        "/chat",
        payload,
        timeout=120,
    )

    # -----------------------------------------------------
    # Persist result
    # -----------------------------------------------------
    result = {

        "generated_at_utc": generated_at_utc,

        "ts_local": ts_local,

        "timezone": timezone_name,

        "trigger_type": "scheduled",

        "lookback_hours": lookback_hours,

        "reasoning_frequency_minutes": frequency_minutes,

        "asset_name": settings["asset_name"],

        "global_status": global_status,

        "channel_rows": channel_rows,

        "answer": response.get("answer", ""),

        "status": response.get("status", "ok"),
    }

    log_json(result)

    write_json_atomic(
        LATEST_STATE_PATH,
        result,
    )

    write_json_atomic(
        SCHEDULE_STATE_PATH,
        {
            "last_success_utc": generated_at_utc
        },
    )


if __name__ == "__main__":
    main()
