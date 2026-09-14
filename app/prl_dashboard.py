import os
import uuid
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
from pathlib import Path

from prl_settings import load_settings, save_settings

# =========================================================
# Config
# =========================================================
DEFAULT_INFLUX_URL = os.environ.get("INFLUX_URL", "http://127.0.0.1:8086/query")
DEFAULT_INFLUX_DB = os.environ.get("INFLUX_DB", "demo_iot")
DEFAULT_CONTROL_PLAN_PATH = "/srv/PRL-ui/control_plan.csv"
DEFAULT_BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "https://users.pdf-insights.ai")
DEFAULT_NOTES_PATH = "/srv/PRL-ui/operator_notes.txt"
LATEST_EXPLANATION_PATH = Path("/srv/PRL-ui/logs/latest_PRL_explanation.json")
SETTINGS = load_settings()

# =========================================================
# Page Setup
# =========================================================
st.set_page_config(
    page_title="Process Monitor Console",
    page_icon="🛰️",
    layout="wide",
)
st.markdown(
    """
<style>
:root {
  --card:#111827;
  --card2:#0b1220;
  --text:#e5e7eb;
  --muted:#9ca3af;
  --border:#1f2937;
}

.main {
  background: linear-gradient(180deg, #05070f 0%, #070a14 100%);
}

.block-container {
  padding-top: 1.2rem;
  padding-bottom: 2rem;
}

h1, h2, h3, h4 {
  color: var(--text) !important;
}

.small-muted {
  color: var(--muted);
  font-size: 0.9rem;
}

.card {
  background: linear-gradient(180deg, var(--card) 0%, var(--card2) 100%);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px 16px;
  box-shadow: 0 10px 30px rgba(0,0,0,.25);
}

.kpi {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.kpi .label {
  color: var(--muted);
  font-size: 0.85rem;
  letter-spacing: .02em;
}

.kpi .value {
  color: var(--text);
  font-size: 1.9rem;
  font-weight: 700;
  line-height: 1;
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 999px;
  font-weight: 700;
  font-size: 0.9rem;
  border: 1px solid var(--border);
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  display: inline-block;
}

.pill.ok {
  background: rgba(16,185,129,.12);
}
.pill.ok .dot {
  background: #10b981;
}

.pill.warn {
  background: rgba(245,158,11,.12);
}
.pill.warn .dot {
  background: #f59e0b;
}

.pill.bad {
  background: rgba(239,68,68,.12);
}
.pill.bad .dot {
  background: #ef4444;
}

.pill.nodata {
  background: rgba(107,114,128,.18);
}
.pill.nodata .dot {
  background: #9ca3af;
}

hr {
  border-color: var(--border) !important;
}
</style>
""",
    unsafe_allow_html=True,
)


# =========================================================
# Helper Functions
# =========================================================

def save_operator_chat(
    messages: List[Dict[str, Any]],
    asset_name: str,
    timezone_name: str,
) -> str:
    now_local = datetime.now(timezone.utc).astimezone(
        ZoneInfo(timezone_name)
    )

    timestamp = now_local.strftime("%Y%m%d_%H%M%S")

    safe_asset = "".join(
        c if c.isalnum() or c in {"-", "_"} else "_"
        for c in asset_name.strip()
    ) or "asset"

    filename = (
        f"operator_chat_{safe_asset}_{timestamp}.txt"
    )

    path = Path("/srv/PRL-ui/logs") / filename

    lines = [
        f"PRL Operator Chat",
        f"Asset: {asset_name}",
        f"Saved: {now_local.strftime('%Y-%m-%d %H:%M:%S')} "
        f"({timezone_name})",
        "",
    ]

    for message in messages:
        role = message.get("role", "assistant")
        content = message.get("content", "")

        if role == "user":
            label = "OPERATOR"
        else:
            label = "PRL"

        lines.extend([
            f"{label}:",
            content.strip(),
            "",
        ])

    path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    return str(path)

def load_text_file(path: str) -> str:
    try:
        if not os.path.exists(path):
            return ""
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return ""

def load_latest_explanation(path: Path = LATEST_EXPLANATION_PATH) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_latest_explanation(payload: Dict[str, Any], path: Path = LATEST_EXPLANATION_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(temp_path, path)

def card(html_inner: str):
    st.markdown(f'<div class="card">{html_inner}</div>', unsafe_allow_html=True)


def status_pill(level: str) -> str:
    mapping = {
        "ok": ("ok", "NORMAL"),
        "warn": ("warn", "WATCH"),
        "bad": ("bad", "ALERT"),
        "nodata": ("nodata", "NO DATA"),
    }
    klass, label = mapping.get(level, ("warn", "WATCH"))
    return f'<span class="pill {klass}"><span class="dot"></span>{label}</span>'


def fmt_num(x: Any, nd: int = 2) -> str:
    try:
        if x is None or str(x).strip() == "":
            return "—"
        return f"{float(x):.{nd}f}"
    except Exception:
        return "—"


def yesno_to_bool(v: Any) -> bool:
    return str(v).strip().lower() in {"yes", "true", "1", "y"}


def safe_float(v: Any) -> Optional[float]:
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(v)
    except Exception:
        return None


def split_semicolon_steps(text: str) -> List[str]:
    return [s.strip() for s in str(text).split(";") if s.strip()]


# =========================================================
# Influx Helpers
# =========================================================
def influx_query(influx_url: str, db: str, q: str, timeout: int = 10) -> Dict[str, Any]:
    r = requests.get(influx_url, params={"db": db, "q": q}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def influx_latest_value(influx_url: str, db: str, measurement: str) -> Optional[float]:
    q = f"SELECT last(value) FROM {measurement}"
    resp = influx_query(influx_url, db, q)

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


def influx_stats_window(
    influx_url: str, db: str, measurement: str, window_hours: int
) -> Dict[str, Optional[float]]:
    q = (
        f"SELECT min(value) AS vmin, max(value) AS vmax, mean(value) AS vavg "
        f"FROM {measurement} WHERE time > now() - {window_hours}h"
    )
    resp = influx_query(influx_url, db, q)

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


def influx_timeseries_last_24h(
    influx_url: str,
    db: str,
    measurement: str,
    timezone_name: str = "UTC",
) -> pd.DataFrame:
    q = f"SELECT value FROM {measurement} WHERE time > now() - 24h ORDER BY time ASC"
    resp = influx_query(influx_url, db, q)

    results = resp.get("results", [])
    if not results:
        return pd.DataFrame(columns=["time", "value"])

    series = results[0].get("series", [])
    if not series:
        return pd.DataFrame(columns=["time", "value"])

    values = series[0].get("values", [])
    if not values:
        return pd.DataFrame(columns=["time", "value"])

    df = pd.DataFrame(values, columns=["time", "value"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["time"] = df["time"].dt.tz_convert(ZoneInfo(timezone_name))
    return df

# =========================================================
# Control Plan Helpers
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


def evaluate_value(value: Optional[float], row: pd.Series) -> str:
    if value is None:
        return "nodata"

    lower_limit = safe_float(row["lower_limit"])
    upper_limit = safe_float(row["upper_limit"])
    warning_low = safe_float(row["warning_low"])
    warning_high = safe_float(row["warning_high"])

    if lower_limit is not None and value < lower_limit:
        return "bad"
    if upper_limit is not None and value > upper_limit:
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
    statuses = [evaluate_value(v, row) for v in (minimum, maximum) if v is not None]
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
        return "warn"
    if window_status == "nodata":
        return "nodata"
    return "ok"


def compute_global_status(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "nodata"
    statuses = [r["status"] for r in rows]
    if "bad" in statuses:
        return "bad"
    if "warn" in statuses:
        return "warn"
    if "nodata" in statuses:
        return "nodata"
    return "ok"


# =========================================================
# API Helpers (Public API Key Flow)
# =========================================================
def api_post_json(base_url: str, path: str, payload: dict, api_key: str, timeout: int = 60) -> Dict[str, Any]:
    r = requests.post(
        f"{base_url.rstrip('/')}{path}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"POST {path} -> {r.status_code}: {r.text}")
    return r.json()


def start_backend_session() -> str:
    return str(uuid.uuid4())


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
        lines.extend(["Operator Notes:", operator_notes.strip(), ""])

    lines.append("Monitored variables (complete evidence set):")
    for row in channel_rows:
        lines.extend([
            f"- {row['display_name']} ({row['tag_name']})",
            f"  Current value: {fmt_num(row['latest'])} {row['unit']}",
            f"  Current status: {row['current_status'].upper()}",
            f"  Lookback min/max/avg: {fmt_num(row['stats_window'].get('min'))} / "
            f"{fmt_num(row['stats_window'].get('max'))} / {fmt_num(row['stats_window'].get('avg'))} {row['unit']}",
            f"  Lookback status: {row['window_status'].upper()}",
            f"  Combined operator status: {row['status'].upper()}",
            f"  Limits: lower={row['lower_limit']}, upper={row['upper_limit']}, "
            f"warning_low={row['warning_low']}, warning_high={row['warning_high']}",
            f"  Description: {row['description']}",
            f"  Expected pattern: {row['expected_pattern']}",
            f"  Reaction plan: {row['reaction_plan']}",
            f"  Missing-data action: {row['missing_data_action']}",
            f"  Document reference: {row['document_reference']}",
            "",
        ])

    lines.extend([
        "Instructions:",
        "Use only the monitored variables listed above. Do not mention variables that are not listed.",
        "Evaluate both the latest value and the entire lookback window.",
        "Report every warning or control-limit excursion in the lookback window, even if the current value has recovered.",
        "Clearly separate current condition, recent events or excursions, likely process meaning, and practical operator checks.",
        "The control-plan limits and reaction plans above are the source of truth. Use the attached process documentation for supporting explanation and citations; do not invent limits.",
    ])
    return "\n".join(lines)


def explain_current_state(
    base_url: str,
    api_key: str,
    pdf_id: str,
    system_prompt: str,
    asset_name: str,
    asset_type: str,
    process_desc: str,
    operator_notes: str,
    channel_rows: List[Dict[str, Any]],
    lookback_hours: int,
    ts_local: str,
    timezone_name: str,
    model_name: str = "gpt-4o-mini",
) -> str:
    session_id = start_backend_session()

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
        "pdf_id": pdf_id,
        "message": message,
        "system_prompt": system_prompt,
        "model": model_name,
    }

    resp = api_post_json(base_url, "/chat", payload, api_key, timeout=120)
    return (resp.get("answer") or "").strip()


def ask_prl(
    base_url: str,
    api_key: str,
    pdf_id: str,
    system_prompt: str,
    operator_question: str,
    session_id: str,
    asset_name: str,
    asset_type: str,
    process_desc: str,
    operator_notes: str,
    channel_rows: List[Dict[str, Any]],
    lookback_hours: int,
    ts_local: str,
    timezone_name: str,
    model_name: str = "gpt-4o-mini",
) -> str:

    lines: List[str] = [
        f"Asset / Process Name: {asset_name}",
        f"Asset Type: {asset_type}",
        f"Process Description: {process_desc}",
        f"Current Time: {ts_local} ({timezone_name})",
        f"Telemetry Lookback Window: last {lookback_hours} hours",
        "",
    ]

    if operator_notes.strip():
        lines.extend([
            "Operator Notes:",
            operator_notes.strip(),
            "",
        ])

    lines.append("CURRENT PRL PROCESS EVIDENCE:")

    for row in channel_rows:

        latest = safe_float(row.get("latest"))

        stats_window = row.get("stats_window", {})
        window_min = safe_float(stats_window.get("min"))
        window_max = safe_float(stats_window.get("max"))
        window_avg = safe_float(stats_window.get("avg"))

        lower = safe_float(row.get("lower_limit"))
        upper = safe_float(row.get("upper_limit"))
        warning_low = safe_float(row.get("warning_low"))
        warning_high = safe_float(row.get("warning_high"))

        # =================================================
        # Deterministic comparisons
        # =================================================

        current_below_control = (
            latest is not None
            and lower is not None
            and latest < lower
        )

        current_above_control = (
            latest is not None
            and upper is not None
            and latest > upper
        )

        current_below_warning = (
            latest is not None
            and warning_low is not None
            and latest < warning_low
        )

        current_above_warning = (
            latest is not None
            and warning_high is not None
            and latest > warning_high
        )

        window_below_control = (
            window_min is not None
            and lower is not None
            and window_min < lower
        )

        window_above_control = (
            window_max is not None
            and upper is not None
            and window_max > upper
        )

        window_below_warning = (
            window_min is not None
            and warning_low is not None
            and window_min < warning_low
        )

        window_above_warning = (
            window_max is not None
            and warning_high is not None
            and window_max > warning_high
        )

        # =================================================
        # Authoritative human-readable interpretations
        # =================================================

        if window_min is None:
            minimum_interpretation = (
                "No lookback minimum is available. "
                "Low-side classification: NODATA."
            )

        elif window_below_control:
            minimum_interpretation = (
                "The lookback minimum crossed the LOWER CONTROL LIMIT. "
                "Low-side classification: BAD."
            )

        elif window_below_warning:
            minimum_interpretation = (
                "The lookback minimum crossed the WARNING LOW threshold, "
                "but did NOT cross the lower control limit. "
                "Low-side classification: WARN."
            )

        else:
            minimum_interpretation = (
                "The lookback minimum did NOT cross either the warning-low "
                "threshold or the lower control limit. "
                "Low-side classification: OK."
            )

        if window_max is None:
            maximum_interpretation = (
                "No lookback maximum is available. "
                "High-side classification: NODATA."
            )

        elif window_above_control:
            maximum_interpretation = (
                "The lookback maximum crossed the UPPER CONTROL LIMIT. "
                "High-side classification: BAD."
            )

        elif window_above_warning:
            maximum_interpretation = (
                "The lookback maximum crossed the WARNING HIGH threshold, "
                "but did NOT cross the upper control limit. "
                "High-side classification: WARN."
            )

        else:
            maximum_interpretation = (
                "The lookback maximum did NOT cross either the warning-high "
                "threshold or the upper control limit. "
                "High-side classification: OK."
            )

        lines.extend([
            "",
            f"- {row['display_name']} ({row['tag_name']})",

            f"  Current value: {fmt_num(latest)} {row['unit']}",
            f"  Current status: {str(row['current_status']).upper()}",

            f"  Lookback minimum: {fmt_num(window_min)} {row['unit']}",
            f"  AUTHORITATIVE MINIMUM INTERPRETATION: "
            f"{minimum_interpretation}",

            f"  Lookback maximum: {fmt_num(window_max)} {row['unit']}",
            f"  AUTHORITATIVE MAXIMUM INTERPRETATION: "
            f"{maximum_interpretation}",

            f"  Lookback average: {fmt_num(window_avg)} {row['unit']}",

            f"  Lookback status: "
            f"{str(row['window_status']).upper()}",

            f"  Combined operator status: "
            f"{str(row['status']).upper()}",

            f"  Control-plan thresholds: "
            f"lower_control={row['lower_limit']}, "
            f"warning_low={row['warning_low']}, "
            f"warning_high={row['warning_high']}, "
            f"upper_control={row['upper_limit']}",

            "  AUTHORITATIVE ENGINEERING COMPARISONS:",

            f"    Current below lower control limit: "
            f"{'YES' if current_below_control else 'NO'}",

            f"    Current above upper control limit: "
            f"{'YES' if current_above_control else 'NO'}",

            f"    Current below warning low: "
            f"{'YES' if current_below_warning else 'NO'}",

            f"    Current above warning high: "
            f"{'YES' if current_above_warning else 'NO'}",

            f"    Lookback minimum below lower control limit: "
            f"{'YES' if window_below_control else 'NO'}",

            f"    Lookback maximum above upper control limit: "
            f"{'YES' if window_above_control else 'NO'}",

            f"    Lookback minimum below warning low: "
            f"{'YES' if window_below_warning else 'NO'}",

            f"    Lookback maximum above warning high: "
            f"{'YES' if window_above_warning else 'NO'}",

            f"  Description: {row['description']}",
            f"  Expected pattern: {row['expected_pattern']}",
            f"  Reaction plan: {row['reaction_plan']}",
            f"  Missing-data action: {row['missing_data_action']}",
            f"  Document reference: {row['document_reference']}",
        ])

    lines.extend([
        "",
        "AUTHORITATIVE STATUS DEFINITIONS:",

        "OK means no warning or control threshold was crossed.",

        "WARN means a warning threshold was crossed, "
        "but no control limit was crossed.",

        "BAD means a control limit was crossed.",

        "NODATA means required telemetry was unavailable.",

        "",
        "CHAT INSTRUCTIONS:",

        "Answer the operator's specific question directly.",

        "Use the current process evidence above together with "
        "the process documentation.",

        "All numerical threshold comparisons have already been "
        "performed by PRL code.",

        "The AUTHORITATIVE MINIMUM INTERPRETATION and "
        "AUTHORITATIVE MAXIMUM INTERPRETATION are final.",

        "When answering a question about a minimum or maximum value, "
        "use the corresponding authoritative interpretation exactly "
        "in meaning.",

        "Do NOT independently compare raw numbers.",

        "Do NOT use words such as above, below, exceeded, crossed, "
        "inside, outside, safe, warning, or control-limit excursion "
        "in a way that contradicts an authoritative interpretation.",

        "Do not contradict an authoritative YES/NO comparison.",

        "Never downgrade BAD to WARN.",

        "Clearly distinguish current conditions from events that "
        "occurred earlier in the lookback window.",

        "Use the control-plan reaction plan and process documentation "
        "when suggesting operator checks.",

        "If the available information is insufficient to answer "
        "confidently, say what additional observation or measurement "
        "would help.",

        "",
        "OPERATOR QUESTION:",
        operator_question.strip(),
    ])

    message = "\n".join(lines)

    payload = {
        "session_id": session_id,
        "pdf_id": pdf_id,
        "message": message,
        "system_prompt": system_prompt,
        "model": model_name,
    }

    resp = api_post_json(
        base_url,
        "/chat",
        payload,
        api_key,
        timeout=120,
    )

    return (resp.get("answer") or "").strip()


# =========================================================
# Sidebar / persistent settings
# =========================================================
TIMEZONES = [
    "UTC", "America/New_York", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "Europe/London", "Europe/Berlin",
    "Asia/Tokyo", "Asia/Singapore", "Australia/Sydney",
]

with st.sidebar:
    st.header("System Configuration")
    asset_name = st.text_input("Asset / Process Name", value=str(SETTINGS["asset_name"]))
    asset_type = st.text_input("Asset Type", value=str(SETTINGS["asset_type"]))
    process_desc = st.text_area(
        "Process Description", value=str(SETTINGS["process_description"]), height=90
    )

    st.divider()
    st.subheader("Display Settings")
    saved_timezone = str(SETTINGS["timezone"])
    timezone_index = TIMEZONES.index(saved_timezone) if saved_timezone in TIMEZONES else 0
    timezone_name = st.selectbox("Timezone", TIMEZONES, index=timezone_index)
    refresh_seconds = st.number_input(
        "Dashboard refresh (seconds)", min_value=30, max_value=900,
        value=int(SETTINGS["dashboard_refresh_seconds"]), step=30,
        help="Refreshes local dashboard data only. It does not call the AI backend.",
    )

    st.divider()
    st.subheader("Reasoning Settings")
    lookback_hours = st.number_input(
        "Lookback period (hours)", min_value=1, max_value=168,
        value=int(SETTINGS["lookback_hours"]), step=1,
    )
    reasoning_frequency_minutes = st.selectbox(
        "Scheduled reasoning frequency", [30, 60, 120, 240],
        index=[30, 60, 120, 240].index(int(SETTINGS["reasoning_frequency_minutes"]))
        if int(SETTINGS["reasoning_frequency_minutes"]) in [30, 60, 120, 240] else 1,
        format_func=lambda minutes: f"{minutes} minutes" if minutes < 60 else f"{minutes // 60} hour(s)",
    )
    system_prompt = st.text_area(
        "Monitoring Prompt / Role", value=str(SETTINGS["system_prompt"]), height=180
    )
    model_options = ["gpt-4o-mini", "gpt-4o"]
    saved_model = str(SETTINGS["model_name"])
    model_name = st.selectbox(
        "Model", model_options, index=model_options.index(saved_model) if saved_model in model_options else 0
    )

    st.divider()
    st.subheader("Sources")
    notes_path = st.text_input("Operator Notes File", value=str(SETTINGS["operator_notes_path"]))
    influx_url = st.text_input("Influx URL", value=str(SETTINGS["influx_url"]))
    influx_db = st.text_input("Influx DB", value=str(SETTINGS["influx_db"]))
    control_plan_path = st.text_input("Control Plan CSV", value=str(SETTINGS["control_plan_path"]))
    operator_notes = load_text_file(notes_path)

    backend_base_url = DEFAULT_BACKEND_BASE_URL
    backend_api_key = os.environ.get("PRL_API_KEY", "").strip()
    process_pdf_id = os.environ.get("PRL_PROCESS_PDF_ID", "").strip()

    if st.button("💾 Save Settings", use_container_width=True):
        SETTINGS = save_settings({
            "asset_name": asset_name,
            "asset_type": asset_type,
            "process_description": process_desc,
            "timezone": timezone_name,
            "system_prompt": system_prompt,
            "model_name": model_name,
            "reasoning_frequency_minutes": int(reasoning_frequency_minutes),
            "lookback_hours": int(lookback_hours),
            "dashboard_refresh_seconds": int(refresh_seconds),
            "influx_url": influx_url,
            "influx_db": influx_db,
            "control_plan_path": control_plan_path,
            "operator_notes_path": notes_path,
        })
        st.success("Settings saved.")

    if st.button("🔄 Refresh Now", use_container_width=True):
        st.rerun()

# Reload the latest persisted explanation on every rerun when it is newer.
latest_state = load_latest_explanation()
latest_id = latest_state.get("generated_at_utc") or latest_state.get("ts_local", "")
if st.session_state.get("reasoning_record_id") != latest_id and latest_id:
    st.session_state["reasoning_record_id"] = latest_id
    st.session_state["reasoning_output"] = latest_state.get("answer", "")
    st.session_state["reasoning_ts_local"] = latest_state.get("ts_local", "")
    st.session_state["reasoning_status"] = latest_state.get("global_status", "")
    st.session_state["reasoning_trigger"] = latest_state.get("trigger_type", "scheduled")

if "reasoning_output" not in st.session_state:
    st.session_state["reasoning_output"] = ""

if "operator_chat_messages" not in st.session_state:
    st.session_state["operator_chat_messages"] = []

if "operator_chat_session_id" not in st.session_state:
    st.session_state["operator_chat_session_id"] = start_backend_session()

# =========================================================
# Load control plan + collect data
# =========================================================
control_plan_error = None
channel_rows: List[Dict[str, Any]] = []
cp = pd.DataFrame()

try:
    cp = load_control_plan(control_plan_path)
    cp = cp[cp["enabled"].apply(yesno_to_bool)].copy()

    for _, row in cp.iterrows():
        measurement = str(row["measurement"]).strip()

        latest = None
        stats_24h = {"min": None, "max": None, "avg": None}
        stats_window = {"min": None, "max": None, "avg": None}

        try:
            latest = influx_latest_value(influx_url, influx_db, measurement)
        except Exception:
            latest = None

        try:
            stats_24h = influx_stats_window(influx_url, influx_db, measurement, 24)
        except Exception:
            stats_24h = {"min": None, "max": None, "avg": None}

        try:
            stats_window = influx_stats_window(
                influx_url, influx_db, measurement, int(lookback_hours)
            )
        except Exception:
            stats_window = {"min": None, "max": None, "avg": None}

        current_status = evaluate_value(latest, row)
        window_status = evaluate_window(stats_window, row)
        status = combine_status(current_status, window_status)

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
            "stats_24h": stats_24h,
            "stats_window": stats_window,
            "current_status": current_status,
            "window_status": window_status,
            "status": status,
        })

except Exception as e:
    control_plan_error = str(e)

global_status = compute_global_status(channel_rows)

# =========================================================
# Header
# =========================================================
st.markdown(f"## 🛰️ Monitoring Console — {asset_name}")

utc_now = datetime.now(timezone.utc)
local_now = utc_now.astimezone(ZoneInfo(timezone_name))

st.markdown(
    f'<div class="small-muted">{asset_type} | {process_desc}</div>',
    unsafe_allow_html=True,
)
st.caption(
    f"Local Time: {local_now.strftime('%Y-%m-%d %H:%M:%S')} ({timezone_name}) | "
    f"UTC: {utc_now.strftime('%Y-%m-%d %H:%M:%S')} (UTC)"
)
st.write("")

topL, topR = st.columns([2, 1], vertical_alignment="center")

with topL:
    card(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div>
            <div class="small-muted">Selected Asset</div>
            <div style="font-size:1.3rem; font-weight:800; color:var(--text);">{asset_name}</div>
          </div>
          {status_pill(global_status)}
        </div>
        """
    )

with topR:
    card(
        f"""
        <div class="kpi">
          <div class="label">Active Variables</div>
          <div class="value" style="font-size:1.1rem; font-weight:800;">{len(channel_rows)}</div>
          <div class="small-muted">Source: InfluxDB + Control Plan</div>
        </div>
        """
    )

if control_plan_error:
    st.error(f"Control plan load failed: {control_plan_error}")
    st.stop()


# =========================================================
# Live Values
# =========================================================
st.divider()
st.subheader("Live Values")

if not channel_rows:
    st.warning("No enabled variables found in control plan.")
else:
    for row_start in range(0, len(channel_rows), 4):
        row_group = channel_rows[row_start:row_start + 4]
        cols = st.columns(len(row_group))

        for idx, ch in enumerate(row_group):
            with cols[idx]:
                card(
                    f"""
                    <div class="kpi">
                      <div class="label">{ch['display_name']} ({ch['unit'] or '—'})</div>
                      <div class="value">{fmt_num(ch['latest'], 2)}</div>
                      <div class="small-muted">{status_pill(ch['status'])}</div>
                    </div>
                    """
                )


# =========================================================
# 24h Summary
# =========================================================
st.divider()
st.subheader("24-Hour Summary")

for row_start in range(0, len(channel_rows), 3):
    row_group = channel_rows[row_start:row_start + 3]
    cols = st.columns(len(row_group))

    for idx, ch in enumerate(row_group):
        s = ch["stats_24h"]
        with cols[idx]:
            card(
                f"""
                <div class="kpi">
                  <div class="label">{ch['display_name']} (24h)</div>
                  <div class="small-muted">Min / Max / Avg</div>
                  <div class="value" style="font-size:1.25rem;">
                    {fmt_num(s.get('min'), 2)} / {fmt_num(s.get('max'), 2)} / {fmt_num(s.get('avg'), 2)}
                  </div>
                </div>
                """
            )


# =========================================================
# Variables Requiring Attention
# =========================================================
st.divider()
st.subheader("Variables Requiring Attention")

attention = [r for r in channel_rows if r["status"] in {"warn", "bad", "nodata"}]

if not attention:
    st.success("All enabled variables are currently within defined warning and control limits.")
else:
    for ch in attention:
        title = f"{ch['display_name']} — {ch['status'].upper()}"
        with st.expander(title, expanded=True):
            st.write(f"**Description:** {ch['description']}")
            st.write(f"**Current Value:** {fmt_num(ch['latest'], 2)} {ch['unit']}")
            st.write(f"**Current Status:** {ch['current_status'].upper()}")
            st.write(f"**Lookback Status ({int(lookback_hours)}h):** {ch['window_status'].upper()}")
            w = ch["stats_window"]
            st.write(
                f"**Lookback Min / Max / Avg:** {fmt_num(w.get('min'))} / "
                f"{fmt_num(w.get('max'))} / {fmt_num(w.get('avg'))} {ch['unit']}"
            )
            st.write(
                f"**Limits:** lower={ch['lower_limit']} | upper={ch['upper_limit']} | "
                f"warning_low={ch['warning_low']} | warning_high={ch['warning_high']}"
            )
            st.write(f"**Priority:** {ch['priority']}")
            st.write(f"**Expected Pattern:** {ch['expected_pattern']}")

            if ch["status"] == "nodata":
                st.write(f"**Missing Data Action:** {ch['missing_data_action']}")
            else:
                st.write("**Reaction Plan:**")
                for step in split_semicolon_steps(ch["reaction_plan"]):
                    st.write(f"- {step}")

            st.write(f"**Document Reference:** {ch['document_reference']}")


# =========================================================
# Process Interpretation
# =========================================================
st.divider()
st.subheader("Process Interpretation")

colA, colB = st.columns([1, 2], gap="large")

with colA:
    if st.button("🧠 Explain Current State", use_container_width=True):
        if not backend_base_url.strip():
            st.error("Backend Base URL is required.")
        elif not backend_api_key.strip():
            st.error("API key is required.")
        elif not process_pdf_id.strip():
            st.error("Process Manual PDF ID is required.")
        else:
            try:
                with st.spinner("Generating process explanation..."):
                    answer = explain_current_state(
                        base_url=backend_base_url,
                        api_key=backend_api_key,
                        pdf_id=process_pdf_id,
                        system_prompt=system_prompt,
                        asset_name=asset_name,
                        asset_type=asset_type,
                        process_desc=process_desc,
                        operator_notes=operator_notes,
                        channel_rows=channel_rows,
                        lookback_hours=int(lookback_hours),
                        ts_local=local_now.strftime("%Y-%m-%d %H:%M:%S"),
                        timezone_name=timezone_name,
                        model_name=model_name,
                    )
                    generated_at_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    ts_local = datetime.now(timezone.utc).astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M:%S")
                    persisted = {
                        "generated_at_utc": generated_at_utc,
                        "ts_local": ts_local,
                        "timezone": timezone_name,
                        "trigger_type": "manual",
                        "lookback_hours": int(lookback_hours),
                        "asset_name": asset_name,
                        "global_status": global_status,
                        "channel_rows": channel_rows,
                        "answer": answer,
                        "status": "ok",
                    }
                    write_latest_explanation(persisted)
                    st.session_state["reasoning_record_id"] = generated_at_utc
                    st.session_state["reasoning_output"] = answer
                    st.session_state["reasoning_ts_local"] = ts_local
                    st.session_state["reasoning_status"] = global_status
                    st.session_state["reasoning_trigger"] = "manual"
            except Exception as e:
                st.session_state["reasoning_output"] = f"Explanation failed: {e}"

last_ts = st.session_state.get("reasoning_ts_local", "")
last_status = st.session_state.get("reasoning_status", "")

if last_ts:
    st.caption(
        f"Latest explanation: {last_ts} | Status: {str(last_status).upper()} | "
        f"Trigger: {st.session_state.get('reasoning_trigger', 'unknown')}"
    )

with colB:
    st.text_area(
        "Current Process Explanation",
        st.session_state.get("reasoning_output", ""),
        height=260,
    )

# =========================================================
# Instant Operator Chat
# =========================================================

st.divider()
st.subheader("💬 Ask PRL")

with st.container(border=True):

    st.caption(
        "Ask a question about the current process condition, recent process history, "
        "control plan, or process documentation."
    )

    # -----------------------------------------------------
    # Display existing chat history
    # -----------------------------------------------------
    if not st.session_state["operator_chat_messages"]:
        st.info("No operator chat yet. Ask PRL a question below.")

    for message in st.session_state["operator_chat_messages"]:
        role = message.get("role", "assistant")
        content = message.get("content", "")

        with st.chat_message(role):
            st.markdown(content)

    # -----------------------------------------------------
    # Operator question entry
    # -----------------------------------------------------
    with st.form(
        "operator_chat_form",
        clear_on_submit=True,
    ):
        operator_question = st.text_input(
            "Operator Question",
            placeholder="Ask PRL a question about the process...",
            label_visibility="collapsed",
        )

        send_question = st.form_submit_button(
            "Ask PRL",
            use_container_width=True,
        )

    # -----------------------------------------------------
    # Process operator question
    # -----------------------------------------------------
    if send_question and operator_question.strip():

        question = operator_question.strip()

        # Save operator message
        st.session_state["operator_chat_messages"].append({
            "role": "user",
            "content": question,
        })

        # Validate backend configuration
        if not backend_base_url.strip():

            answer = "Backend Base URL is required."

        elif not backend_api_key.strip():

            answer = "API key is required."

        elif not process_pdf_id.strip():

            answer = "Process Manual PDF ID is required."

        else:

            try:
                with st.spinner("PRL is reviewing the process..."):

                    chat_now = datetime.now(timezone.utc).astimezone(
                        ZoneInfo(timezone_name)
                    )

                    answer = ask_prl(
                        base_url=backend_base_url,
                        api_key=backend_api_key,
                        pdf_id=process_pdf_id,
                        system_prompt=system_prompt,
                        operator_question=question,
                        session_id=st.session_state["operator_chat_session_id"],
                        asset_name=asset_name,
                        asset_type=asset_type,
                        process_desc=process_desc,
                        operator_notes=operator_notes,
                        channel_rows=channel_rows,
                        lookback_hours=int(lookback_hours),
                        ts_local=chat_now.strftime("%Y-%m-%d %H:%M:%S"),
                        timezone_name=timezone_name,
                        model_name=model_name,
                    )

            except Exception as e:
                answer = f"PRL chat failed: {e}"

        # Save PRL response
        st.session_state["operator_chat_messages"].append({
            "role": "assistant",
            "content": answer,
        })

        # Rerun so the complete conversation appears
        # together above the question-entry box.
        st.rerun()

# -----------------------------------------------------
# Chat controls
# -----------------------------------------------------
if st.session_state["operator_chat_messages"]:

    st.divider()

    save_col, clear_col = st.columns([1, 1])

    with save_col:

        if st.button(
            "💾 Save Chat",
            use_container_width=True,
        ):

            try:
                saved_path = save_operator_chat(
                    messages=st.session_state[
                        "operator_chat_messages"
                    ],
                    asset_name=asset_name,
                    timezone_name=timezone_name,
                )

                st.success(
                    f"Chat saved to {saved_path}"
                )

            except Exception as e:
                st.error(
                    f"Could not save chat: {e}"
                )

    with clear_col:

        if st.button(
            "🗑️ Clear Chat",
            use_container_width=True,
        ):

            st.session_state[
                "operator_chat_messages"
            ] = []

            st.session_state[
                "operator_chat_session_id"
            ] = start_backend_session()

            st.rerun()

# =========================================================
# Trends + Notes
# =========================================================
st.divider()

left, right = st.columns([1.4, 1], gap="large")

with left:
    card("<div class='small-muted'>Telemetry Trends (Last 24 Hours)</div>")

    for ch in channel_rows:
        try:
            df = influx_timeseries_last_24h(
                influx_url,
                influx_db,
                ch["measurement"],
                timezone_name=timezone_name,
            )
            if not df.empty:
                # Streamlit title (wraps properly on mobile)
                st.markdown(
                    f"<div style='font-size:14px; font-weight:600; margin-bottom:4px;'>"
                    f"{ch['display_name']}</div>",
                    unsafe_allow_html=True,
                )

                st.markdown(
                    f"<div style='font-size:12px; color:#888; margin-bottom:6px;'>"
                    f"Last 24h ({timezone_name})</div>",
                    unsafe_allow_html=True,
                )

                fig = px.line(
                    df,
                    x="time",
                    y="value",
                )

                fig.update_layout(
                    height=300,
                    margin=dict(l=10, r=10, t=10, b=10),  # smaller top margin
                )   
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info(f"No points found for {ch['display_name']}.")
        except Exception as e:
            st.warning(f"Trend unavailable for {ch['display_name']}: {e}")

with right:
    card("<div class='small-muted'>Operator Notes</div>")
    st.text_area(
        "Notes",
        value=operator_notes,
        height=220,
        disabled=True,
    )

    st.write("")

    card("<div class='small-muted'>Monitoring Prompt / Role</div>")
    st.text_area(
        "Prompt",
        value=system_prompt,
        height=220,
        disabled=True,
    )

# =========================================================
# Local dashboard auto-refresh (no AI call)
# =========================================================
if int(refresh_seconds) > 0:
    components.html(
        f"<script>setTimeout(function(){{window.parent.location.reload();}}, {int(refresh_seconds) * 1000});</script>",
        height=0,
        width=0,
    )

# =========================================================
# Debug / Raw
# =========================================================
st.divider()

with st.expander("Raw Evaluated Variable Data", expanded=False):
    st.json(channel_rows)

with st.expander("Loaded Control Plan", expanded=False):
    st.dataframe(cp, use_container_width=True)
