"""--headless engine+projector mode and --autostart (task 143)."""
import signal
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QSettings

from showsync import cli
from showsync.audio import Anchor, AudioEngine, Position
from showsync.document import Document, Row
from showsync.headless import HeadlessShow, headless_loop
from showsync.transport import START, STOP
from showsync.video_window import VideoWindow
from conftest import TONE


def document(tmp_path):
    return Document(tmp_path / 'set.yaml', title='Take', rows=[
        Row('Ambient', TONE, 120, duration=1), Row('Closer', TONE, 100, duration=1)])


def saved_setlist(tmp_path):
    doc = document(tmp_path)
    doc.save()
    return str(doc.path)


# --- CLI parsing and dispatch ---

def loop_recorder(monkeypatch, name):
    seen = {}

    def fake(document, **kwargs):
        seen.update(kwargs, document=document)
        return 0

    monkeypatch.setattr(cli, name, fake)
    return seen


def test_cli_headless_dispatches_to_headless_loop(monkeypatch, tmp_path):
    headless = loop_recorder(monkeypatch, 'headless_loop')
    gui = loop_recorder(monkeypatch, 'main_loop')
    assert cli.main(['--headless', '--autostart', '5', saved_setlist(tmp_path)]) == 0
    assert not gui
    assert headless['autostart'] == 5.0
    assert headless['midi_transport'] is False
    assert headless['document'].display_title == 'Take'


def test_cli_headless_passes_midi_transport(monkeypatch, tmp_path):
    headless = loop_recorder(monkeypatch, 'headless_loop')
    assert cli.main(['--headless', '--midi-transport', saved_setlist(tmp_path)]) == 0
    assert headless['midi_transport'] is True
    assert headless['autostart'] is None


def test_cli_autostart_bare_defaults_to_three_seconds(monkeypatch, tmp_path):
    headless = loop_recorder(monkeypatch, 'headless_loop')
    # nargs='?': a bare --autostart must follow the setlist path.
    assert cli.main([saved_setlist(tmp_path), '--headless', '--autostart']) == 0
    assert headless['autostart'] == 3.0


def test_cli_autostart_reaches_gui_mode_too(monkeypatch, tmp_path):
    gui = loop_recorder(monkeypatch, 'main_loop')
    assert cli.main(['--autostart', '1.5', saved_setlist(tmp_path)]) == 0
    assert gui['autostart'] == 1.5
    assert cli.main([saved_setlist(tmp_path)]) == 0
    assert gui['autostart'] is None


def test_cli_autostart_rejects_bad_values(monkeypatch, tmp_path):
    # Stub both loops so a missing bounds check fails the assertion below
    # instead of launching a real Qt event loop.
    loop_recorder(monkeypatch, 'headless_loop')
    loop_recorder(monkeypatch, 'main_loop')
    for bad in ('-1', 'nan', '3601'):
        with pytest.raises(SystemExit):
            cli.main(['--autostart', bad, saved_setlist(tmp_path)])


def test_cli_headless_without_any_setlist_errors(monkeypatch):
    monkeypatch.setattr(cli, 'last_setlist', lambda: None)
    with pytest.raises(SystemExit):
        cli.main(['--headless'])


def test_cli_headless_refuses_unplayable_set(monkeypatch, tmp_path):
    headless = loop_recorder(monkeypatch, 'headless_loop')
    doc = Document(tmp_path / 'set.yaml', rows=[Row('No tempo', TONE, None, duration=1)])
    doc.save()
    assert cli.main(['--headless', str(doc.path)]) == 1
    assert not headless


def test_cli_headless_refuses_unloadable_set(monkeypatch, tmp_path):
    headless = loop_recorder(monkeypatch, 'headless_loop')
    assert cli.main(['--headless', str(tmp_path / 'missing.yaml')]) == 1
    assert not headless


# --- HeadlessShow lifecycle ---

@pytest.fixture
def show_factory(qtbot, tmp_path):
    shows = []

    def build(doc=None, start=None, **kwargs):
        closed = []
        quits = []

        def default_start(setlist):
            audio = AudioEngine(setlist)
            return audio, SimpleNamespace(error=None), lambda: (closed.append(True), audio.close())

        settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat)
        show = HeadlessShow(doc if doc is not None else document(tmp_path),
                            start_engines=start or default_start, settings=settings,
                            quit=quits.append, **kwargs)
        show.closed_engines, show.quits = closed, quits
        shows.append(show)
        return show

    yield build
    for show in shows:
        show.shutdown()
        show.video_window.deleteLater()


def ended_position(audio):
    frame = audio.total_frames
    audio._anchors.append(Anchor(frame, frame, audio.now(), False, 0))


def test_autostart_plays_and_wires_projector(qtbot, show_factory):
    show = show_factory(autostart=0.0)
    qtbot.waitUntil(lambda: show.audio is not None)
    assert show.video_window.audio is show.audio
    assert show.quits == []


def test_set_end_quits_cleanly(qtbot, show_factory):
    show = show_factory(autostart=0.0)
    qtbot.waitUntil(lambda: show.audio is not None)
    ended_position(show.audio)
    show.refresh()
    assert show.quits == [0]


def test_engine_error_quits_with_failure(qtbot, show_factory):
    show = show_factory(autostart=0.0)
    qtbot.waitUntil(lambda: show.audio is not None)
    show.clock.error = 'clock thread died'
    show.refresh()
    qtbot.waitUntil(lambda: show.quits == [1])


def test_transport_start_and_stop_drive_the_set(qtbot, show_factory, monkeypatch):
    import showsync.transport as transport
    monkeypatch.setattr(transport, 'open_midi_inputs', lambda preferred=None: [])
    show = show_factory(midi_transport=True)
    assert show.transport.handle(START) == 'started set'
    assert show.audio is not None
    # Set the playing anchor so STOP sees a genuinely playing set.
    show.audio._anchors.append(Anchor(0, 0, show.audio.now(), True, 0))
    assert show.transport.handle(STOP) == 'stopped set'
    assert show.audio is None
    assert show.closed_engines == [True]
    assert show.quits == []  # process stays up for another Start


def test_stop_set_without_engines_is_a_noop(show_factory):
    show = show_factory()
    show.stop_set()
    assert show.closed_engines == []


# --- Esc on the projector ---

def test_projector_escape_quits_only_when_hooked(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / 'vw.ini'), QSettings.IniFormat)
    quits = []
    hooked = VideoWindow(settings, on_escape=lambda: quits.append(True))
    qtbot.addWidget(hooked)
    qtbot.keyClick(hooked, Qt.Key_Escape)
    assert quits == [True]

    plain = VideoWindow(settings)
    qtbot.addWidget(plain)
    qtbot.keyClick(plain, Qt.Key_Escape)  # GUI mode: no crash, no quit hook
    assert quits == [True]


# --- headless_loop: full Qt lifecycle without a MainWindow ---

def test_headless_loop_runs_set_to_completion_and_restores_signals(qtbot, tmp_path):
    doc = document(tmp_path)
    setlist = doc.setlist()
    position = Position(0, 0.0, False, ended=True)
    audio = SimpleNamespace(error=None, setlist=setlist, position=lambda: position)
    closed = []

    def start(_setlist):
        return audio, SimpleNamespace(error=None), lambda: closed.append(True)

    before = signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)
    remembered = []
    code = headless_loop(doc, start_engines=start, remember=remembered.append,
                         settings=QSettings(str(tmp_path / 'hl.ini'), QSettings.IniFormat),
                         autostart=0.0)
    assert code == 0
    assert closed == [True]
    assert remembered == [doc.path]
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == before


# --- GUI-mode autostart ---

def test_gui_autostart_starts_the_set(qtbot, window_factory, tmp_path):
    w = window_factory(document(tmp_path), autostart=0.0)
    qtbot.waitUntil(lambda: w.audio is not None)
    assert w.stack.currentWidget() is w.playback
