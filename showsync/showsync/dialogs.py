"""Native file dialogs (stdlib tkinter, withdraw-root) for the pygame editor.

Each call spins up a hidden Tk root, shows one modal dialog, and tears the
root down again, so no Tk event loop ever competes with pygame's. The GUI
treats any failure here (tkinter missing in a frozen build, no display) as
"dialogs unavailable" and falls back to drag-and-drop with a visible notice.
"""
from pathlib import Path

AUDIO_PATTERNS = "*.wav *.aif *.aiff *.flac *.mp3 *.m4a"


def _root():
    import tkinter
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)  # never open behind the pygame window
    return root


def audio_files():
    from tkinter import filedialog
    root = _root()
    try:
        names = filedialog.askopenfilenames(
            parent=root, title="Add songs",
            filetypes=[("Audio files", AUDIO_PATTERNS), ("All files", "*")])
        return [Path(name) for name in names]
    finally:
        root.destroy()


def setlist_path():
    from tkinter import filedialog
    root = _root()
    try:
        name = filedialog.askopenfilename(
            parent=root, title="Open setlist",
            filetypes=[("Setlists", "*.yaml *.yml"), ("All files", "*")])
        return Path(name) if name else None
    finally:
        root.destroy()


def save_path(directory):
    from tkinter import filedialog
    root = _root()
    try:
        name = filedialog.asksaveasfilename(
            parent=root, title="Save setlist", defaultextension=".yaml",
            initialdir=str(directory), initialfile="setlist.yaml",
            filetypes=[("Setlists", "*.yaml *.yml")])
        return Path(name) if name else None
    finally:
        root.destroy()
