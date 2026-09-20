"""Tiny per-user app state (last-used setlist) in the platform-native location."""
import json
import math
import os
from pathlib import Path
import sys


def state_file():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", "") or Path.home() / ".local" / "state")
    return base / "showsync" / "state.json"


def last_setlist(path=None):
    """The last setlist saved/opened, or None if unrecorded or gone."""
    path = Path(path) if path else state_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("last_setlist") if isinstance(data, dict) else None
    if not isinstance(value, str):
        return None
    value = Path(value)
    return value if value.is_file() else None


def _read_state(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def clock_offset_ms(path=None):
    value = _read_state(Path(path) if path else state_file()).get("clock_offset_ms", 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return value if math.isfinite(value) and -250 <= value <= 250 else 0


def remember_clock_offset(value, path=None):
    _update_state({"clock_offset_ms": value}, path)


def remember_setlist(setlist_path, path=None):
    _update_state({"last_setlist": str(Path(setlist_path).resolve())}, path)


def _update_state(values, path=None):
    """Best-effort state merge: preferences must never take the show down."""
    path = Path(path) if path else state_file()
    try:
        data = _read_state(path)
        data.update(values)
        path.parent.mkdir(parents=True, exist_ok=True)
        replacement = path.with_name(path.name + ".tmp")
        replacement.write_text(json.dumps(data), encoding="utf-8")
        os.replace(replacement, path)
    except OSError:
        pass
