from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from showsync.audio import Anchor, AudioEngine
from showsync.clock import ClockEngine, START, STOP
from showsync.document import Document, Row
from showsync.gui import timestamp
from showsync.tempomap import TempoEvent
from conftest import TONE


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
    assert captured[0][1]['autoplay'] is False
    assert cli.main([str(path)]) == 0
    assert captured[1][1]['autoplay'] is True
