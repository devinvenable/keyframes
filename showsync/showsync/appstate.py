"""Tiny per-user app state (last-used setlist) in the platform-native location."""
import json
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


def remember_setlist(setlist_path, path=None):
    """Best-effort: losing the pointer must never take the show down."""
    path = Path(path) if path else state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        replacement = path.with_name(path.name + ".tmp")
        replacement.write_text(json.dumps({"last_setlist": str(Path(setlist_path).resolve())}),
                               encoding="utf-8")
        os.replace(replacement, path)
    except OSError:
        pass
