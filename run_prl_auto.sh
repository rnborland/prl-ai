#!/usr/bin/env bash
set -euo pipefail

# Protected backend credentials and PDF ID.
set -a
source /etc/prl.env
set +a

# Technical runtime paths only. Operator-adjustable settings are loaded from:
#   /srv/PRL-ui/config/settings.json
export PRL_SETTINGS_PATH="/srv/PRL-ui/config/settings.json"
export PRL_LOG_DIR="/srv/PRL-ui/logs"

/srv/PRL-ui/venv/bin/python /srv/PRL-ui/prl_auto_runner.py
