"""Qt tests use isolated settings and engines without opening devices."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSettings

from showsync.audio import AudioEngine
from showsync.document import Document
from showsync.gui import MainWindow

FIXTURES = Path(__file__).parent / 'fixtures'
TONE = FIXTURES / 'tone.wav'


class Dialogs:
    def __init__(self, save=None, open_=None, files=(), bundle=None,
                 import_zip=None, import_dest=None, align=False):
        self.save, self.open_, self.files = save, open_, list(files)
        self.bundle = bundle
        self.import_zip, self.import_dest = import_zip, import_dest
        self.align = align
        self.save_dirs = []
        self.bundle_stems = []
        self.import_defaults = []
        self.align_calls = []

    def save_path(self, directory):
        self.save_dirs.append(Path(directory))
        return self.save

    def align_trim(self, name, message, preview):
        self.align_calls.append((name, message, preview))
        return self.align

    def setlist_path(self):
        return self.open_

    def audio_files(self):
        return self.files

    def bundle_path(self, directory, stem):
        self.bundle_stems.append(stem)
        return self.bundle

    def import_bundle_path(self):
        return self.import_zip

    def import_destination(self, default):
        self.import_defaults.append(Path(default))
        return self.import_dest or default


@pytest.fixture
def window_factory(qtbot, tmp_path):
    def cleanup(window):
        window.timer.stop()
        window.suggestions.close()
        window.shutdown_engines()
        window.dirty = False  # teardown must not open a modal prompt

    def build(document=None, **kwargs):
        closed = []
        def start(setlist):
            audio = AudioEngine(setlist)
            return audio, SimpleNamespace(error=None), lambda: (closed.append(True), audio.close())
        kwargs.setdefault('start_engines', start)
        kwargs.setdefault('dialogs', Dialogs())
        kwargs.setdefault('estimator', lambda path, **kw: None)
        kwargs.setdefault('settings', QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat))
        window = MainWindow(document or Document(), **kwargs)
        window.closed_engines = closed
        qtbot.addWidget(window, before_close_func=cleanup)
        window.show()
        return window
    return build
