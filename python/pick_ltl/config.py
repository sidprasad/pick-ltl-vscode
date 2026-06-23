from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


APP_NAME = "pick-ltl"
DEFAULT_SETTINGS = {
    "kind": "ollama",
    "base_url": "http://localhost:11434",
    "model": "",
    "api_key": "",
    "timeout_seconds": 60,
}


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_config_dir() -> Path:
    override = os.environ.get("PICK_LTL_CONFIG_DIR")
    if override:
        return Path(override).expanduser()

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser() / APP_NAME

    return Path.home() / ".config" / APP_NAME


def get_settings_path() -> Path:
    return get_config_dir() / "settings.json"


def load_settings() -> dict[str, Any]:
    path = get_settings_path()
    if not path.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(path.read_text())
    except Exception:
        return dict(DEFAULT_SETTINGS)
    merged = dict(DEFAULT_SETTINGS)
    merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    return merged


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_SETTINGS)
    merged.update({k: v for k, v in settings.items() if k in DEFAULT_SETTINGS})
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2))
    return merged

