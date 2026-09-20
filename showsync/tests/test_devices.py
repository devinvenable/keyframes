from unittest.mock import Mock

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from showsync import appstate, cli, devices
from showsync.device_dialog import DeviceDialog
from test_gui import document


@pytest.fixture
def rig(monkeypatch, tmp_path):
    monkeypatch.setattr(appstate, 'state_file', lambda: tmp_path / 'state.json')
    monkeypatch.setattr(devices, 'midi_outputs', lambda: ['Midi Through', 'TBOX Out 1', 'TBOX Out 2'])
    monkeypatch.setattr(devices, 'audio_outputs', lambda: [(4, 'Speakers (ALSA)'), (8, 'Stage (ALSA)')])


def test_fresh_play(qtbot, window_factory, tmp_path, rig, monkeypatch):
    selection = devices.Devices()
    w = window_factory(document(tmp_path), devices=selection)
    chooser = Mock(side_effect=AssertionError('Play must not prompt'))
    monkeypatch.setattr(w, 'device_preferences', chooser)
    qtbot.mouseClick(w.play_button, Qt.LeftButton)
    assert w.audio is not None
    assert selection.midi_name == 'TBOX Out 1'
    assert selection.audio_index is None
    assert w.midi_status.text() == 'MIDI: TBOX Out 1'
    assert not w.devices_action.isEnabled()
    assert appstate.device_choices() == {'midi': None, 'audio': None}
    chooser.assert_not_called()


def test_preferences_persist(qtbot, window_factory, tmp_path, rig):
    appstate.remember_clock_offset(32)
    w = window_factory(document(tmp_path), devices=devices.Devices())
    seen = []
    def choose():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DeviceDialog)
        seen.append(True)
        dialog.midi.setCurrentIndex(dialog.midi.findData('TBOX Out 2'))
        dialog.audio.setCurrentIndex(dialog.audio.findData('Stage (ALSA)'))
        qtbot.mouseClick(dialog.buttons.button(QDialogButtonBox.Ok), Qt.LeftButton)
    QTimer.singleShot(0, choose)
    w.devices_action.trigger()
    assert seen == [True]
    selection = devices.Devices()
    w2 = window_factory(document(tmp_path), devices=selection)
    w2.play()
    assert (selection.midi_name, selection.audio_index) == ('TBOX Out 2', 8)
    assert appstate.clock_offset_ms() == 32
    assert appstate.device_choices() == {'midi': 'TBOX Out 2', 'audio': 'Stage (ALSA)'}


def test_unplugged_fallback(window_factory, tmp_path, rig):
    appstate.remember_devices(midi='Gone', audio='Gone speaker')
    selection = devices.Devices()
    w = window_factory(document(tmp_path), devices=selection)
    w.play()
    assert w.audio is not None
    assert (selection.midi_name, selection.audio_index) == ('TBOX Out 1', None)
    assert 'Gone' in w.statusBar().currentMessage()
    assert 'system default' in w.statusBar().currentMessage()
    assert appstate.device_choices()['midi'] == 'Gone'


def test_single_and_no_ports(window_factory, tmp_path, rig, monkeypatch):
    selection = devices.Devices()
    monkeypatch.setattr(devices, 'midi_outputs', lambda: ['Midi Through'])
    w = window_factory(document(tmp_path), devices=selection)
    w.play()
    assert selection.midi_name == 'Midi Through'
    w.stop()
    monkeypatch.setattr(devices, 'midi_outputs', lambda: [])
    w.play()
    assert w.audio is not None and selection.midi_name is None
    assert 'audio only' in w.midi_status.text()
    assert 'No MIDI output' in w.statusBar().currentMessage()


def test_refresh_cancel(qtbot, rig, monkeypatch):
    dialog = DeviceDialog(devices.Devices())
    qtbot.addWidget(dialog)
    dialog.show()
    monkeypatch.setattr(devices, 'midi_outputs', lambda: ['New hardware'])
    qtbot.mouseClick(dialog.refresh_button, Qt.LeftButton)
    assert dialog.midi.findData('New hardware') >= 0
    assert dialog.midi.findData('TBOX Out 1') == -1
    dialog.midi.setCurrentIndex(dialog.midi.findData('New hardware'))
    qtbot.mouseClick(dialog.buttons.button(QDialogButtonBox.Cancel), Qt.LeftButton)
    assert appstate.device_choices()['midi'] is None


def test_cli_precedence_and_audio_only(rig, monkeypatch):
    appstate.remember_devices(midi='TBOX Out 1', audio='Speakers (ALSA)')
    captured = []
    audio, midi, clock = Mock(), Mock(), Mock()
    monkeypatch.setattr(cli, 'AudioEngine', audio)
    monkeypatch.setattr(cli, 'open_midi_port', midi)
    monkeypatch.setattr(cli, 'ClockEngine', clock)
    monkeypatch.setattr(cli, 'last_setlist', lambda: None)
    monkeypatch.setattr(cli, 'main_loop', lambda doc, **kw: captured.append(kw) or 0)
    assert cli.main(['--midi-port', '2', '--audio-device', '8']) == 0
    kw = captured[-1]
    selection = kw['devices']
    selection.resolve(devices.midi_outputs(), devices.audio_outputs())
    kw['start_engines'](None)
    midi.assert_called_once_with('TBOX Out 2')
    assert audio.call_args.kwargs['device'] == 8
    selection.choose('TBOX Out 2', 'Stage (ALSA)')
    assert appstate.device_choices() == {'midi': 'TBOX Out 1', 'audio': 'Speakers (ALSA)'}
    selection.resolve([], devices.audio_outputs())
    midi.reset_mock()
    _, _, close = kw['start_engines'](None)
    clock.call_args.args[2](248)
    midi.assert_not_called()
    close()
