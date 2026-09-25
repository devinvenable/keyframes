from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from showsync.audio import Anchor, AudioEngine
from showsync.clock import ClockEngine, START, STOP
from showsync.document import Document, Row
from showsync.gui import timestamp
from showsync.tempomap import TempoEvent
from conftest import Dialogs, TONE


def document(tmp_path, *, ramp=False):
    return Document(tmp_path / 'set.yaml', title='Stage test', rows=[
        Row('Ambient', TONE, 120, duration=1, tempo=(TempoEvent(0, 140, .5),) if ramp else ()),
        Row('Next song', TONE, 100, duration=1), Row('Last song', TONE, 90, duration=1)])


def position(audio, frame, *, playing=True):
    audio.frames_played = frame
    audio._anchors.append(Anchor(frame, frame, audio.now(), playing, 0))


def test_dashboard_buttons_mode_switch_end_restart_editor(qtbot, window_factory, tmp_path):
    w = window_factory(document(tmp_path, ramp=True))
    assert w.stack.currentWidget() is w.editor
    qtbot.mouseClick(w.play_button, Qt.LeftButton)
    audio = w.audio
    position(audio, 0)
    w.refresh()
    assert w.stack.currentWidget() is w.playback
    assert w.song_label.text() == 'Ambient'
    assert w.bpm_label.text() == '120.0 BPM  → 140'
    assert 'Next song' in w.next_label.text()
    qtbot.mouseClick(w.pause_button, Qt.LeftButton)
    assert audio._requested == (True, 0, 0)
    qtbot.mouseClick(w.pause_button, Qt.LeftButton)
    assert audio._requested == (False, 0, 0)
    qtbot.mouseClick(w.skip_button, Qt.LeftButton)
    assert audio._requested == (True, 1, 1)
    position(audio, audio.total_frames, playing=False)
    w.refresh()
    assert w.state_label.text() == 'End of set'
    assert w.restart_button.isEnabled() and w.editor_button.isEnabled()
    assert not w.pause_button.isEnabled() and not w.skip_button.isEnabled()
    qtbot.mouseClick(w.restart_button, Qt.LeftButton)
    assert audio._requested == (True, 2, 0)
    qtbot.mouseClick(w.editor_button, Qt.LeftButton)
    assert w.stack.currentWidget() is w.editor
    assert w.audio is None and w.closed_engines == [True]
    assert timestamp(95.5) == '01:35'


def test_reorder_upcoming_and_live_restart_confirmation(qtbot, window_factory, monkeypatch, tmp_path):
    w = window_factory(document(tmp_path))
    qtbot.mouseClick(w.play_button, Qt.LeftButton)
    w.queue.setCurrentRow(2)
    w.move_upcoming(-1)
    assert w.audio.order == (0, 2, 1)
    assert [r.name for r in Document.load(w.document.path).rows] == ['Ambient', 'Last song', 'Next song']
    w.move_upcoming(-1)
    assert w.audio.order == (0, 2, 1)
    assert 'cannot move now' in w.statusBar().currentMessage()
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.No)
    qtbot.mouseClick(w.restart_button, Qt.LeftButton)
    assert w.audio._requested == (False, 0, 0)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Yes)
    qtbot.mouseClick(w.restart_button, Qt.LeftButton)
    assert w.audio._requested == (True, 1, 0)


def test_confirm_close_while_playing_sends_stop_before_audio_close(qtbot, window_factory, monkeypatch, tmp_path):
    events = []
    def start(setlist):
        audio = AudioEngine(setlist)
        position(audio, 0)
        clock = ClockEngine(audio.maps, audio.position, events.append)
        clock.step()
        def close():
            clock.close()
            events.append('audio close')
            audio.close()
            events.append('midi close')
        return audio, clock, close
    w = window_factory(document(tmp_path), start_engines=start)
    qtbot.mouseClick(w.play_button, Qt.LeftButton)
    assert events[0] == START
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.No)
    w.close()
    assert w.isVisible() and w.audio is not None and STOP not in events
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Yes)
    w.close()
    assert not w.isVisible() and w.audio is None
    assert events[-3:] == [STOP, 'audio close', 'midi close']


def test_menu_fullscreen_stop_and_return_confirmation(qtbot, window_factory, monkeypatch, tmp_path):
    w = window_factory(document(tmp_path))
    assert [a.text() for a in w.menuBar().actions()] == ['&File', '&Set', '&View', '&Help']
    assert w.open_action.shortcut().toString() == 'Ctrl+O'
    assert w.pause_action.shortcut().toString() == 'Space'
    w.fullscreen_action.trigger()
    assert w.isFullScreen()
    w.fullscreen_action.trigger()
    assert not w.isFullScreen()
    w.play_action.trigger()
    assert not w.new_action.isEnabled() and not w.open_action.isEnabled()
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.No)
    w.editor_action.trigger()
    assert w.audio is not None
    w.stop_action.trigger()
    assert w.audio is None and w.stack.currentWidget() is w.editor
    assert w.closed_engines == [True]


def test_snapshot_refresh_is_reader_and_displays_lead_in_paused_gap(window_factory, tmp_path):
    doc = document(tmp_path)
    doc.rows[0].offset = .5
    doc.rows[0].gap = .5
    w = window_factory(doc)
    w.play()
    audio = w.audio
    original = audio._requested
    for frame, playing, label in ((0, True, 'Lead-in'), (24000, False, 'Paused'), (50000, True, 'Gap')):
        position(audio, frame, playing=playing)
        w.refresh()
        assert w.state_label.text() == label
        assert audio._requested == original
    assert 'background:' not in w.playback.styleSheet()


def test_failed_start_and_runtime_failure_return_to_editor(qtbot, window_factory, tmp_path):
    def fail(setlist):
        raise RuntimeError('MIDI unavailable')
    w = window_factory(document(tmp_path), start_engines=fail)
    w.play()
    assert w.audio is None and 'MIDI unavailable' in w.statusBar().currentMessage()
    w2 = window_factory(document(tmp_path))
    w2.play()
    w2.clock.error = 'MIDI disconnected'
    w2.refresh()
    qtbot.waitUntil(lambda: w2.audio is None)
    assert w2.stack.currentWidget() is w2.editor
    assert w2.statusBar().currentMessage() == 'MIDI disconnected'
    assert w2.closed_engines == [True]


def test_no_argument_cli_keeps_existing_appstate_startup(monkeypatch, tmp_path):
    from showsync import cli
    path = tmp_path / 'existing.yaml'
    document(tmp_path).save()
    path.write_text((tmp_path / 'set.yaml').read_text())
    captured = []
    monkeypatch.setattr(cli, 'last_setlist', lambda: path)
    monkeypatch.setattr(cli, 'remember_setlist', lambda p: None)
    monkeypatch.setattr(cli, 'main_loop', lambda doc, **kw: captured.append((doc, kw)) or 0)
    assert cli.main([]) == 0
    assert captured[0][0].path == path
    assert not captured[0][1].get('autoplay', False)
    assert cli.main([str(path)]) == 0
    assert not captured[1][1].get('autoplay', False)


@pytest.fixture
def cli_window(monkeypatch, tmp_path, qtbot, window_factory):
    from unittest.mock import Mock
    from showsync import appstate, cli, gui

    monkeypatch.setattr(appstate, 'state_file', lambda: tmp_path / 'state.json')
    engines = Mock(side_effect=RuntimeError('Unexpected engine startup'))
    monkeypatch.setattr(cli, 'AudioEngine', engines)
    windows = []

    def build(doc, **kwargs):
        window = window_factory(doc, **kwargs)
        windows.append(window)
        return window

    def exec_():
        # Process startup callbacks too: a scheduled Play must not escape this check.
        qtbot.wait(50)
        return 0

    monkeypatch.setattr(gui, 'MainWindow', build)
    monkeypatch.setattr(gui, 'QApplication', SimpleNamespace(
        instance=lambda: SimpleNamespace(exec=exec_)))

    def launch(args):
        assert cli.main(args) == 0
        window = windows[-1]
        assert window.isVisible()
        assert window.stack.currentWidget() is window.editor
        assert window.open_action.isEnabled()
        engines.assert_not_called()
        return window

    return launch


@pytest.mark.parametrize('content, problem', [
    (f'songs: [{{name: Song, file: {TONE}, bpm: 120}}]', None),
    (f'songs: [{{name: Song, file: {TONE}}}]', 'BPM not set'),
    ('songs: [{name: Song, file: missing.wav, bpm: 120}]', 'audio file not found'),
    ('songs: []', 'the set has no songs'),
])
def test_cli_setlist_opens_editor_and_records_recent(cli_window, tmp_path, content, problem):
    from showsync import appstate

    path = tmp_path / 'set.yaml'
    path.write_text(content)
    window = cli_window([str(path)])
    assert window.document.path == path
    assert appstate.last_setlist() == path
    assert window.settings.value('recentSets', [], type=list) == [str(path)]
    assert window.play_button.isEnabled()
    if problem:
        assert problem in window.statusBar().currentMessage()
        if window.document.rows:
            assert window.model.data(window.model.index(0, 0), Qt.ToolTipRole) == problem
        window.play_button.click()
        assert window.audio is None
        assert problem in window.statusBar().currentMessage()
    else:
        assert window.model.rowCount() == 1
        assert window.document.rows[0].bpm == 120


@pytest.mark.parametrize('content', [None, 'songs: [', 'songs: not-a-list'])
def test_cli_unreadable_setlist_keeps_gui_open(cli_window, tmp_path, content):
    from showsync import appstate

    previous = tmp_path / 'previous.yaml'
    previous.write_text('songs: []')
    appstate.remember_setlist(previous)
    path = tmp_path / 'bad.yaml'
    if content is not None:
        path.write_text(content)
    window = cli_window([str(path)])
    assert 'COULD NOT OPEN SETLIST:' in window.statusBar().currentMessage()
    assert str(path) in window.statusBar().currentMessage()
    assert window.document.path is None
    assert appstate.last_setlist() == previous
    assert str(path) not in window.settings.value('recentSets', [], type=list)
    window.play_button.click()
    assert window.audio is None
    assert 'the set has no songs' in window.statusBar().currentMessage()


def test_live_offset_control_does_not_touch_audio(window_factory, tmp_path):
    changes = []
    w = window_factory(document(tmp_path), offset_changed=changes.append)
    w.play()
    requested = w.audio._requested
    w.clock.clock_offset_ms = 0
    w.offset_spin.setValue(32)
    assert w.clock.clock_offset_ms == 32
    assert changes[-1] == 32
    assert w.audio._requested == requested
    assert 'Positive = earlier' in w.offset_spin.toolTip()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDoubleSpinBox
    def adjust_dialog():
        dialog = QApplication.activeModalWidget()
        dialog.findChild(QDoubleSpinBox).setValue(-32)
        dialog.accept()
    QTimer.singleShot(0, adjust_dialog)
    w.offset_action.trigger()
    assert w.offset_spin.value() == w.clock.clock_offset_ms == -32
    assert w.audio._requested == requested


def test_cli_clock_offset_override_is_temporary(monkeypatch):
    from showsync import cli
    from unittest.mock import Mock
    captured = []
    save = Mock()
    engine = Mock()
    monkeypatch.setattr(cli, 'AudioEngine', Mock())
    monkeypatch.setattr(cli, 'open_midi_port', Mock())
    monkeypatch.setattr(cli, 'ClockEngine', engine)
    monkeypatch.setattr(cli, 'clock_offset_ms', lambda: 17)
    monkeypatch.setattr(cli, 'last_setlist', lambda: None)
    monkeypatch.setattr(cli, 'remember_clock_offset', save)
    monkeypatch.setattr(cli, 'main_loop', lambda doc, **kw: captured.append(kw) or 0)
    assert cli.main(['--clock-offset', '32']) == 0
    assert captured[-1]['clock_offset_ms'] == 32
    captured[-1]['offset_changed'](33)
    save.assert_not_called()
    captured[-1]['start_engines'](None)
    assert engine.call_args.kwargs['clock_offset_ms'] == 33
    assert cli.main([]) == 0
    assert captured[-1]['clock_offset_ms'] == 17
    captured[-1]['offset_changed'](-12)
    save.assert_called_once_with(-12)


def test_export_bundle_menu_zips_saved_set(qtbot, window_factory, tmp_path):
    import zipfile
    doc = document(tmp_path)
    doc.save()
    w = window_factory(doc, dialogs=Dialogs(bundle=tmp_path / 'out.zip'))
    w.export_bundle()
    assert w.dialogs.bundle_stems == ['set']
    assert sorted(zipfile.ZipFile(tmp_path / 'out.zip').namelist()) == ['set.yaml', 'tone.wav']
    assert 'Exported out.zip' in w.statusBar().currentMessage()


def test_export_bundle_saves_unsaved_set_first(qtbot, window_factory, tmp_path):
    import zipfile
    doc = document(tmp_path)
    doc.path = None
    w = window_factory(doc, dialogs=Dialogs(save=tmp_path / 'named.yaml', bundle=tmp_path / 'out.zip'))
    w.dirty = True
    w.export_bundle()
    assert (tmp_path / 'named.yaml').is_file()
    assert 'set.yaml' not in zipfile.ZipFile(tmp_path / 'out.zip').namelist()
    assert 'named.yaml' in zipfile.ZipFile(tmp_path / 'out.zip').namelist()


def test_export_bundle_aborts_when_save_declined(qtbot, window_factory, tmp_path):
    doc = document(tmp_path)
    doc.path = None
    w = window_factory(doc, dialogs=Dialogs(bundle=tmp_path / 'out.zip'))
    w.dirty = True
    w.export_bundle()
    assert w.dialogs.bundle_stems == []
    assert not (tmp_path / 'out.zip').exists()


def test_import_bundle_menu_extracts_and_opens_setlist(qtbot, window_factory, tmp_path):
    from showsync.bundle import export_bundle
    doc = document(tmp_path)
    doc.save()
    zip_path = tmp_path / 'tour.zip'
    export_bundle(doc.path, zip_path)
    w = window_factory(Document(), dialogs=Dialogs(import_zip=zip_path))
    w.import_bundle()
    assert w.dialogs.import_defaults == [tmp_path / 'tour']
    assert w.document.path == tmp_path / 'tour' / 'set.yaml'
    assert w.document.title == 'Stage test'
    assert str(tmp_path / 'tour' / 'set.yaml') in w.settings.value('recentSets', [], type=list)
    assert 'Imported tour.zip' in w.statusBar().currentMessage()


def test_import_bundle_error_is_a_notice_not_a_crash(qtbot, window_factory, tmp_path):
    bad = tmp_path / 'not-a-bundle.zip'
    bad.write_bytes(b'PK\x03\x04 garbage')
    w = window_factory(Document(), dialogs=Dialogs(import_zip=bad))
    before = w.document
    w.import_bundle()
    assert 'Import failed' in w.statusBar().currentMessage()
    assert w.document is before


def test_import_bundle_cancelled_dialog_changes_nothing(qtbot, window_factory, tmp_path):
    w = window_factory(Document(), dialogs=Dialogs(import_zip=None))
    before = w.document
    w.import_bundle()
    assert w.document is before
    assert w.dialogs.import_defaults == []


def test_align_to_one_confirms_before_writing_trim(window_factory, tmp_path):
    from showsync.bpmdetect import TrimSuggestion
    doc = Document(tmp_path / 'set.yaml', rows=[Row('Divider', TONE, 106, duration=1, offset=.163)])
    suggested = [TrimSuggestion(.653, .73, .653)]
    dialogs = Dialogs(align=False)
    w = window_factory(doc, dialogs=dialogs,
                       trim_suggester=lambda path, grid: suggested[0])
    doc.save()
    before = doc.path.read_text()
    w.table.selectRow(0)
    w.align_to_one()
    # Declined: nothing written, but the dialog was offered with a preview.
    assert doc.rows[0].trim == 0
    assert doc.path.read_text() == before
    assert len(dialogs.align_calls) == 1
    name, message, preview = dialogs.align_calls[0]
    assert name == 'Divider' and '0.653' in message and callable(preview)
    assert 'not applied' in w.statusBar().currentMessage()
    dialogs.align = True
    w.align_to_one()
    assert doc.rows[0].trim == .653
    assert 'trim: 0.653' in doc.path.read_text()
    assert 'starts at 0.653s' in w.statusBar().currentMessage()


def test_align_to_one_guards_grid_and_zero_trim(window_factory, tmp_path):
    from showsync.bpmdetect import TrimSuggestion
    doc = Document(tmp_path / 'set.yaml', rows=[
        Row('NoBpm', TONE, None, duration=1),
        Row('Aligned', TONE, 120, duration=1),
        Row('Ramped', TONE, 120, duration=1, tempo=(TempoEvent(0, 140, .5),))])
    dialogs = Dialogs(align=True)
    w = window_factory(doc, dialogs=dialogs,
                       trim_suggester=lambda path, grid: TrimSuggestion(0, .1, 0))
    w.table.selectRow(0)
    w.align_to_one()
    assert 'Set or estimate a BPM' in w.statusBar().currentMessage()
    w.table.selectRow(2)
    w.align_to_one()
    assert 'constant tempo' in w.statusBar().currentMessage()
    w.table.selectRow(1)
    w.align_to_one()
    assert 'already starts on the one' in w.statusBar().currentMessage()
    assert not dialogs.align_calls and all(row.trim == 0 for row in doc.rows)


def test_video_window_follows_trim(qtbot, tmp_path):
    from PySide6.QtCore import QSettings
    from showsync.audio import Position
    from showsync.setlist import Setlist, Song
    from showsync.video_window import VideoWindow

    class FakeWorker:
        def __init__(self):
            self.submitted = []
            self.result = None
        def submit(self, key, seconds=0):
            self.submitted.append((key, seconds))
        def close(self):
            pass

    song = Song('clip', tmp_path / 'clip.mp4', 120, trim=8.656)
    audio = SimpleNamespace(
        position=lambda: Position(0, 1.5, True),
        setlist=Setlist('trimmed', (song,)))
    window = VideoWindow(QSettings(str(tmp_path / 's.ini'), QSettings.IniFormat))
    qtbot.addWidget(window)
    window.audio = audio
    window.worker = FakeWorker()
    window.refresh()
    (key, seconds), = window.worker.submitted
    assert key[0] == song.file
    assert seconds == pytest.approx(1.5 + 8.656)
    window.timer.stop()


def test_midi_transport_flag_drives_set_like_gui(qtbot, window_factory, monkeypatch, tmp_path):
    import showsync.transport as transport

    class FakeInput:
        callback = None
        closed = False

        def set_callback(self, callback):
            self.callback = callback

        def close_port(self):
            self.closed = True

    fake = FakeInput()
    monkeypatch.setattr(transport, 'open_midi_inputs', lambda preferred=None: [fake])
    w = window_factory(document(tmp_path), midi_transport=True)
    assert w.midi_input is not None and fake.callback is not None
    fake.callback(([0xF8], 0.0))  # clock ticks never reach the handler
    assert w.audio is None
    fake.callback(([0xFA], 0.0))  # KeyStep Play
    assert w.audio is not None and w.stack.currentWidget() is w.playback
    audio = w.audio
    position(audio, 0)
    fake.callback(([0xFA], 0.0))  # echoed Start while playing: idempotent
    assert w.audio is audio
    fake.callback(([0xFC], 0.0))  # KeyStep Stop
    assert w.audio is None and w.closed_engines == [True]
    assert w.stack.currentWidget() is w.editor
    fake.callback(([0xFC], 0.0))  # echoed Stop while stopped: idempotent
    assert w.closed_engines == [True]


def test_transport_keys_win_over_focused_offset_spinbox(qtbot, window_factory, tmp_path):
    """Live transport shortcuts must fire even while the MIDI clock offset
    spinbox holds keyboard focus: its line edit otherwise claims Ctrl+Right
    (cursor word-move) and Space (text input) via ShortcutOverride, leaving
    Skip and Pause silently dead until something else is clicked."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    w = window_factory(document(tmp_path))
    qtbot.mouseClick(w.play_button, Qt.LeftButton)
    audio = w.audio
    position(audio, 0)
    w.refresh()
    QApplication.setActiveWindow(w)

    def press(key, modifier=Qt.NoModifier):
        # Deliver where the window system would: the focus widget if any.
        QTest.keyClick(w.focusWidget() or w, key, modifier)

    press(Qt.Key_Right, Qt.ControlModifier)
    assert audio._requested == (True, 1, 1)
    w.offset_spin.setFocus()
    assert w.focusWidget() in (w.offset_spin, w.offset_spin.lineEdit())
    press(Qt.Key_Right, Qt.ControlModifier)  # Skip, not a cursor word-move
    assert audio._requested == (True, 2, 2)
    press(Qt.Key_Space)                      # Pause, not typed text
    assert audio._requested == (False, 2, 2)
    press(Qt.Key_Space)
    assert audio._requested == (True, 2, 2)
    # Finishing the edit releases focus, restoring every other shortcut too.
    press(Qt.Key_Enter)
    assert w.focusWidget() is not w.offset_spin
    assert not w.offset_spin.hasFocus()
    # Clicked live buttons never keep focus, so the keyboard stays global.
    assert w.skip_button.focusPolicy() == Qt.NoFocus
