import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

SETTINGS_PATH = Path(os.environ.get("PRL_SETTINGS_PATH", "/srv/PRL-ui/config/settings.json"))

DEFAULT_SETTINGS: Dict[str, Any] = {
    "asset_name": "Demo Asset",
    "asset_type": "Machine / Facility / Process / Installation",
    "process_description": "Steady-state monitored process with defined control limits.",
    "timezone": "America/New_York",
    "system_prompt": (
        "You are an assistant to the control room operator. Evaluate both the current process state "
        "and the complete telemetry lookback window. Report every warning-limit or control-limit "
        "excursion during the lookback period, even if the latest value has returned to normal. "
        "Clearly distinguish current conditions from recent historical events. Use only the monitored "
        "variables and control-plan limits supplied in the request, and provide practical guidance "
        "supported by the process documentation."
    ),
    "model_name": "gpt-4o-mini",
    "reasoning_frequency_minutes": 60,
    "lookback_hours": 4,
    "dashboard_refresh_seconds": 60,
    "influx_url": "http://127.0.0.1:8086/query",
    "influx_db": "demo_iot",
    "control_plan_path": "/srv/PRL-ui/control_plan.csv",
    "operator_notes_path": "/srv/PRL-ui/operator_notes.txt",
}


def _merge_defaults(raw: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(DEFAULT_SETTINGS)
    for key in merged:
        if key in raw:
            merged[key] = raw[key]
    return merged


def load_settings(path: Path = SETTINGS_PATH) -> Dict[str, Any]:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                return _merge_defaults(raw)
    except (OSError, json.JSONDecodeError):
        pass
    return deepcopy(DEFAULT_SETTINGS)


def save_settings(settings: Dict[str, Any], path: Path = SETTINGS_PATH) -> Dict[str, Any]:
    clean = _merge_defaults(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="settings-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2)
            f.write("\n")
        os.chmod(temp_name, 0o664)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return clean
