import os
import uuid
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json

# =========================================================
# Config
# =========================================================
DEFAULT_INFLUX_URL = os.environ.get("INFLUX_URL", "http://127.0.0.1:8086/query")
DEFAULT_INFLUX_DB = os.environ.get("INFLUX_DB", "demo_iot")
DEFAULT_CONTROL_PLAN_PATH = "/srv/PRL-ui/control_plan.csv"
DEFAULT_BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "https://users.pdf-insights.ai")
DEFAULT_NOTES_PATH = "/srv/PRL-ui/operator_notes.txt"

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
def load_text_file(path: str) -> str:
    try:
        if not os.path.exists(path):
            return ""
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return ""

def load_latest_explanation(path: str = "/srv/PRL-ui/logs/latest_PRL_explanation.json") -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

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


def influx_stats_last_24h(influx_url: str, db: str, measurement: str) -> Dict[str, Optional[float]]:
    q = (
        f"SELECT min(value) AS vmin, max(value) AS vmax, mean(value) AS vavg "
        f"FROM {measurement} WHERE time > now() - 24h"
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


def evaluate_status(latest: Optional[float], row: pd.Series) -> str:
    """
    Status logic:
    - no value -> nodata
    - outside lower/upper -> bad
    - outside warning band -> warn
    - otherwise ok
    """
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
) -> str:
    problem_rows = [r for r in channel_rows if r["status"] in {"warn", "bad", "nodata"}]

    lines: List[str] = []
    lines.append(f"Asset / Process Name: {asset_name}")
    lines.append(f"Asset Type: {asset_type}")
    lines.append(f"Process Description: {process_desc}")
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
        "Using the attached process manual and the structured variable information above, "
        "provide a concise operator-focused explanation of the current state."
    )
    lines.append(
        "Do not guess operating limits. Use the control-plan information provided above as the source of truth."
    )
    lines.append(
        "Explain: 1) what is outside normal or drifting, 2) likely meaning in process terms, "
        "3) what the operator should check first, 4) whether this looks urgent or watch-and-monitor."
    )

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
    model_name: str = "gpt-4o-mini",
) -> str:
    session_id = start_backend_session()

    message = build_explanation_message(
        asset_name=asset_name,
        asset_type=asset_type,
        process_desc=process_desc,
        operator_notes=operator_notes,
        channel_rows=channel_rows,
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


# =========================================================
# Sidebar
# =========================================================
with st.sidebar:
    st.header("System Configuration")

    asset_name = st.text_input("Asset / Process Name", value="Demo Asset")
    asset_type = st.text_input("Asset Type", value="Machine / Facility / Process / Installation")

    process_desc = st.text_area(
        "Process Description",
        value="Steady-state monitored process with defined control limits.",
        height=90,
    )
    st.divider()
    st.subheader("Display Settings")

    timezone_name = st.selectbox(
        "Timezone",
        [
            "UTC",
            "America/New_York",
            "America/Chicago",
            "America/Denver",
            "America/Los_Angeles",
            "Europe/London",
            "Europe/Berlin",
            "Asia/Tokyo",
            "Asia/Singapore",
            "Australia/Sydney",
        ],
        index=0,
        help="Used for display time in the dashboard and charts.",
    )
    system_prompt = st.text_area(
        "Monitoring Prompt / Role",
        value=(
            "You are an assistant to the control room operators. "
            "Identify any drift from normal behaviour, summarize the current state, "
            "and provide clear practical guidance based on the control plan."
        ),
        height=140,
    )

    notes_path = st.text_input(
        "Operator Notes File",
        value=DEFAULT_NOTES_PATH,
        help="Text file read on each rerun to populate operator notes.",
    )

    operator_notes = load_text_file(notes_path)

    st.caption(f"Notes file: {notes_path}")

    st.divider()
    st.subheader("InfluxDB Source")
    influx_url = st.text_input("Influx URL", value=DEFAULT_INFLUX_URL)
    influx_db = st.text_input("Influx DB", value=DEFAULT_INFLUX_DB)

    st.divider()
    st.subheader("Control Plan")
    control_plan_path = st.text_input("Control Plan CSV", value=DEFAULT_CONTROL_PLAN_PATH)


    st.divider()
    st.subheader("Reasoning Layer")

    backend_base_url = st.text_input(
        "Backend Base URL",
        value=DEFAULT_BACKEND_BASE_URL,
    )
    backend_api_key = "YOUR API KEY HERE"

    process_pdf_id = "YOUR PDF_ID HERE"

    model_name = st.selectbox(
        "Model",
        ["gpt-4o-mini", "gpt-4o"],
        index=0,
    )

    st.divider()
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

if "reasoning_output" not in st.session_state:
    latest_state = load_latest_explanation()
    st.session_state["reasoning_output"] = latest_state.get("answer", "")
    st.session_state["reasoning_ts_local"] = latest_state.get("ts_local", "")
    st.session_state["reasoning_status"] = latest_state.get("global_status", "")

st.subheader("Process Interpretation")


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

        try:
            latest = influx_latest_value(influx_url, influx_db, measurement)
        except Exception:
            latest = None

        try:
            stats_24h = influx_stats_last_24h(influx_url, influx_db, measurement)
        except Exception:
            stats_24h = {"min": None, "max": None, "avg": None}

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
            "stats_24h": stats_24h,
            "status": status,
        })

except Exception as e:
    control_plan_error = str(e)

global_status = compute_global_status(channel_rows)

if "reasoning_output" not in st.session_state:
    st.session_state["reasoning_output"] = ""


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
                        model_name=model_name,
                    )
                    st.session_state["reasoning_output"] = answer
                    st.session_state["reasoning_ts_local"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    st.session_state["reasoning_status"] = global_status
                    st.write("DEBUG answer length:", len(answer))
            except Exception as e:
                st.session_state["reasoning_output"] = f"Explanation failed: {e}"

last_ts = st.session_state.get("reasoning_ts_local", "")
last_status = st.session_state.get("reasoning_status", "")

if last_ts:
    st.caption(f"Last saved explanation: {last_ts} | Status: {str(last_status).upper()}")

with colB:
    st.text_area(
        "Current Process Explanation",
        st.session_state.get("reasoning_output", ""),
        height=260,
    )


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
                fig = px.line(
                    df,
                    x="time",
                    y="value",
                    title=f"{ch['display_name']} (last 24h, {timezone_name})",
                )
                fig.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10))
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
# Debug / Raw
# =========================================================
st.divider()

with st.expander("Raw Evaluated Variable Data", expanded=False):
    st.json(channel_rows)

with st.expander("Loaded Control Plan", expanded=False):
    st.dataframe(cp, use_container_width=True)
