import logging
from unittest.mock import Mock

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog
import pytest

from showsync import cli, devices, transport
from showsync.config_dialog import SetSettingsDialog, SongSettingsDialog
from showsync.device_dialog import DeviceDialog
from showsync.document import Document
from showsync.setlist import EgressFilter
from showsync.visuals import KeyframesCue, song_controls
from test_devices import rig
from test_gui import document


def test_set_settings_menu_saves_filters_setup_and_title(window_factory, tmp_path, qtbot, rig):
    doc = document(tmp_path)
    doc.save()
    doc.path.write_text('# keep set comment\n' + doc.path.read_text() + '\nkeyframes: null\n')
    doc = Document.load(doc.path)
    w = window_factory(doc, devices=devices.Devices())
    def edit():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, SetSettingsDialog)
        dialog.title.setText('New title')
        dialog.banks.setText('aged, insect')
        dialog.channel.setValue(7)
        dialog.outputs.add_output('TBOX Out 2')
        dialog.outputs.table.item(0, 2).setCheckState(Qt.Unchecked)
        dialog.outputs.table.item(0, 3).setCheckState(Qt.Unchecked)
        dialog.accept()
    QTimer.singleShot(0, edit)
    w.set_settings_action.trigger()
    reopened = Document.load(doc.path)
    assert reopened.title == 'New title'
    assert reopened.keyframes == (('aged', 'insect'), 7)
    assert reopened.setlist().midi_outputs == (EgressFilter('TBOX Out 2', ('clock',)),)
    assert '# keep set comment' in doc.path.read_text()
    unchanged = doc.path.read_text()
    reopened.save()
    assert doc.path.read_text() == unchanged
    assert 'TBOX Out 2 (clock)' in w.midi_status.text()
    w.play()
    assert not w.set_settings_action.isEnabled() and not w.song_settings_action.isEnabled()


def test_song_settings_save_cues_video_gap_and_loop(window_factory, tmp_path, qtbot, rig):
    doc = document(tmp_path)
    video = tmp_path / 'visual.mp4'
    video.touch()  # GUI checks paths, playback tests separately cover decoding.
    row = doc.rows[0]
    row.file = video
    row.midi = tmp_path / 'notes.mid'
    row.midi_loop = True
    doc.keyframes = (('aged', 'insect'), 16)
    w = window_factory(doc)
    w.table.selectRow(0)
    w.refresh()
    def edit():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, SongSettingsDialog)
        dialog.gap.setValue(2.5)
        dialog.video.setText(str(video))
        dialog.mute.setChecked(True)
        dialog.midi_beats.setValue(16)
        dialog.cue.setChecked(True)
        dialog.bank.setCurrentIndex(dialog.bank.findData('insect'))
        dialog.scenes.setCurrentIndex(1)
        dialog.probability_override.setChecked(True)
        dialog.probability.setValue(.25)
        dialog.allow_override.setChecked(True)
        dialog.allow['four-bar-sweep'].setChecked(True)
        dialog.accept()
    QTimer.singleShot(0, edit)
    w.song_settings_action.trigger()
    reopened = Document.load(doc.path, probe=lambda path: 10)
    saved = reopened.rows[0]
    assert (saved.gap, saved.video, saved.mute, saved.midi_beats) == (2.5, video, True, 16)
    assert saved.keyframes == KeyframesCue('insect', True, .25, ('four-bar-sweep',))
    assert song_controls(reopened.setlist())[0] == ((0xCF, 2), (0xBF, 102, 0),
        (0xBF, 103, 127), (0xBF, 104, 32), (0xBF, 105, 0))
    for cue_enabled, expected in ((True, KeyframesCue()), (False, None)):
        dialog = SongSettingsDialog(saved, reopened.keyframes[0])
        qtbot.addWidget(dialog)
        dialog.cue.setChecked(cue_enabled)
        dialog.bank.setCurrentIndex(0)
        dialog.scenes.setCurrentIndex(0)
        dialog.probability_override.setChecked(False)
        dialog.allow_override.setChecked(False)
        dialog.accept()
        reopened.save()
        assert Document.load(doc.path, probe=lambda path: 10).rows[0].keyframes == expected


def test_invalid_or_cancelled_configuration_does_not_mutate(tmp_path, qtbot):
    doc = document(tmp_path)
    doc.keyframes = (('aged',), 16)
    doc.rows[0].keyframes = KeyframesCue(bank='aged')
    dialog = SetSettingsDialog(doc)
    qtbot.addWidget(dialog)
    dialog.title.setText('Changed')
    dialog.banks.clear()
    dialog.accept()
    assert dialog.result() != QDialog.Accepted
    assert 'not in' in dialog.error.text()
    assert doc.title == 'Stage test'
    dialog.banks.setText('aged')
    dialog.outputs.add_output('TBOX')
    for column in (1, 2, 3):
        dialog.outputs.table.item(0, column).setCheckState(Qt.Unchecked)
    dialog.accept()
    assert 'nonempty' in dialog.error.text() and doc.midi_outputs == ()
    song = SongSettingsDialog(doc.rows[0], doc.keyframes[0])
    qtbot.addWidget(song)
    song.gap.setValue(12)
    song.allow_override.setChecked(True)
    song.accept()
    assert 'nonempty' in song.error.text() and doc.rows[0].gap == 0
    song.reject()
    assert doc.rows[0].keyframes == KeyframesCue(bank='aged')


def test_run_override_dialog_reaches_cli_engine_and_can_be_cleared(rig, monkeypatch, qtbot, tmp_path):
    captured = []
    egress = Mock()
    monkeypatch.setattr(cli, 'AudioEngine', Mock())
    monkeypatch.setattr(cli, 'ClockEngine', Mock())
    monkeypatch.setattr(cli, 'open_egress', egress)
    monkeypatch.setattr(cli, 'open_virtual_cue_port', lambda: None)
    monkeypatch.setattr(cli, 'last_setlist', lambda: None)
    monkeypatch.setattr(cli, 'load_setlist_events', lambda _: ())
    monkeypatch.setattr(cli, 'main_loop', lambda doc, **kw: captured.append(kw) or 0)
    assert cli.main(['--midi-outputs', 'CLI port']) == 0
    kw = captured[0]
    selection = kw['devices']
    dialog = DeviceDialog(selection)
    qtbot.addWidget(dialog)
    assert dialog.override_outputs.isChecked()
    dialog.outputs.table.item(0, 0).setText('TBOX Out 2')
    dialog.outputs.table.item(0, 2).setCheckState(Qt.Unchecked)
    dialog.outputs.table.item(0, 3).setCheckState(Qt.Unchecked)
    dialog.accept()
    doc = document(tmp_path)
    doc.midi_outputs = ('Set port',)
    _, _, close = kw['start_engines'](doc.setlist())
    close()
    assert tuple(egress.call_args.args[0]) == (EgressFilter('TBOX Out 2', ('clock',)),)
    dialog.override_outputs.setChecked(False)
    dialog.accept()
    _, _, close = kw['start_engines'](doc.setlist())
    close()
    assert egress.call_args.args[0] == ['Set port']
    assert devices.Devices().egress_override is None  # run-only, never saved


@pytest.mark.parametrize('cli_flag,saved,enabled,source', [
    (True, False, True, 'CLI flag'),
    (None, True, True, 'remembered GUI preference'),
    (None, False, False, 'remembered GUI preference'),
])
def test_transport_effective_source_and_precedence(window_factory, monkeypatch, tmp_path,
                                                   caplog, cli_flag, saved, enabled, source):
    caplog.set_level(logging.INFO)
    opened = []
    def inputs(preferred):
        port = Mock()
        opened.append(port)
        return [port]
    monkeypatch.setattr(transport, 'open_midi_inputs', inputs)
    settings = QSettings(str(tmp_path / 'receive.ini'), QSettings.IniFormat)
    settings.setValue('receiveMidiTransport', saved)
    args = cli.build_parser().parse_args(['--midi-transport'] if cli_flag else [])
    w = window_factory(settings=settings, midi_transport=args.midi_transport)
    assert w.transport_action.isChecked() == enabled
    expected = f'Receive MIDI transport: {"ON" if enabled else "OFF"} — {source}'
    assert w.transport_status.text() == expected
    assert expected in caplog.text
    assert bool(opened) == enabled
    assert settings.value('receiveMidiTransport', type=bool) == saved  # CLI does not persist
    w.close()


def test_transport_toggle_disconnects_handlers_and_persists(window_factory, monkeypatch):
    port = Mock()
    monkeypatch.setattr(transport, 'open_midi_inputs', lambda preferred: [port])
    w = window_factory()
    w.transport_action.trigger()  # on
    w.transport_action.trigger()  # off
    assert w.settings.value('receiveMidiTransport', type=bool) is False
    port.close_port.assert_called_once()
    w.transport_action.trigger()  # on again
    starts = Mock()
    monkeypatch.setattr(w, 'play', starts)
    w.transport.start = starts
    w.transport_received.emit(transport.START)
    assert starts.call_count == 1
    assert 'GUI choice (remembered)' in w.transport_status.text()
    assert w.settings.value('receiveMidiTransport', type=bool) is True
    w.close()
