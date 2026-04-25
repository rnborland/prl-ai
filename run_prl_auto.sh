#!/usr/bin/env bash
set -euo pipefail

# =========================================================
# Easy-edit runtime settings
# =========================================================

# How often cron runs this script:
#   Put that in crontab separately (examples below)

# How much history the AI should consider:
export PRL_LOOKBACK_HOURS="8"

# Display / report timezone:
export PRL_TIMEZONE="UTC"

# Backend / model:
export BACKEND_BASE_URL="https://users.pdf-insights.ai"
export PRL_API_KEY="YOUR_PDF_INSIGHTS_API_KEY_HERE"
export PRL_MODEL="gpt-4o-mini"

# Asset configuration:
export PRL_ASSET_NAME="Demo Asset"
export PRL_ASSET_TYPE="Machine / Facility / Process / Installation"
export PRL_PROCESS_DESC="Steady-state monitored process with defined control limits."

# Control plan + docs:
export PRL_CONTROL_PLAN_PATH="/srv/PRL-ui/control_plan.csv"
export PRL_PROCESS_PDF_ID="bc3c025e-66f7-4353-a9cb-f25238c873d1"

# Data source:
export INFLUX_URL="http://127.0.0.1:8086/query"
export INFLUX_DB="demo_iot"

# Notes / prompt:
export PRL_NOTES=$(cat <<'EOF'
Add site-specific operator notes here.
These notes are sent with each automatic reasoning request.
EOF
)

export PRL_SYSTEM_PROMPT=$(cat <<'EOF'
You are an assistant to the control room operator. Identify any drift from normal behavior, summarize the current state, and provide clear, practical guidance based on the control plan.
EOF
)

# Log location:
export PRL_LOG_DIR="/srv/PRL-ui/logs"

# =========================================================
# Run
# =========================================================
/srv/PRL-ui/venv/bin/python /srv/PRL-ui/prl_auto_runner.py
