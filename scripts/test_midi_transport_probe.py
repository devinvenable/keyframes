import io
import json
from types import SimpleNamespace

import mido
import pytest

import midi_transport_probe as probe
from midi_transport_probe import Recorder, select_ports


def test_probe_preserves_stop_cc_and_mmc_on_both_inputs():
    stream = io.StringIO()
    now = [0.0]
    recorder = Recorder(stream, now=lambda: now[0], epoch=lambda: 100 + now[0])
    for port in ('KeyStep USB', 'TBOX return'):
        recorder.receive(port, mido.Message('clock'))
        now[0] += 0.1
        recorder.receive(port, mido.Message('stop'))
        recorder.receive(port, mido.Message('control_change', control=51, value=127))
        recorder.receive(port, mido.Message('sysex', data=[0x7F, 0x7F, 6, 1]))
        now[0] += 0.1
        recorder.receive(port, mido.Message('clock'))
    recorder.close()
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    for port in ('KeyStep USB', 'TBOX return'):
        events = [r for r in records if r.get('port') == port]
        assert [r.get('type', r.get('event')) for r in events] == [
            'clock_summary', 'stop', 'control_change', 'sysex', 'clock_summary']
        assert events[0]['last'] < events[1]['monotonic'] < events[-1]['first']
        assert events[2]['control'] == 51 and events[2]['value'] == 127
        assert events[3]['data'] == [0x7F, 0x7F, 6, 1]


def test_clock_only_stream_is_reported_before_close():
    stream = io.StringIO()
    now = [0.0]
    recorder = Recorder(stream, now=lambda: now[0])
    for i in range(51):
        now[0] = i / 50
        recorder.receive('TBOX', mido.Message('clock'))
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(records) == 1
    assert records[0]['event'] == 'clock_summary'
    assert records[0]['count'] == 51
    assert records[0]['first'] == 0 and records[0]['last'] == 1


def test_port_selection_does_not_guess_between_tbox_jacks():
    ports = ['KeyStep USB', 'TBOX Midi Out 1', 'TBOX Midi Out 2']
    assert select_ports(ports, ['keystep', 'Midi Out 1', 'KeyStep USB']) == ports[:2]
    with pytest.raises(ValueError, match='exactly one'):
        select_ports(ports, ['TBOX'])
    with pytest.raises(ValueError, match='exactly one'):
        select_ports(ports, ['disconnected'])


def test_cli_captures_callbacks_and_closes_inputs_without_opening_outputs(monkeypatch, tmp_path):
    inputs = {}
    closed = []

    class Input:
        def __init__(self, name, callback):
            inputs[name] = callback
            self.name = name

        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append(self.name)

    def wait(seconds):
        assert seconds == 90
        for callback in inputs.values():
            callback(mido.Message('stop'))

    def no_output(*args, **kwargs):
        pytest.fail('Passive probe must not open MIDI outputs')

    monkeypatch.setattr(mido, 'get_input_names', lambda: ['KeyStep USB', 'TBOX Midi Out 1'])
    monkeypatch.setattr(mido, 'open_input', Input)
    monkeypatch.setattr(mido, 'open_output', no_output)
    monkeypatch.setattr(probe.threading, 'Event', lambda: SimpleNamespace(wait=wait))
    output = tmp_path / 'capture.jsonl'
    assert probe.main(['--output', str(output)]) == 0
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert [r['port'] for r in records if r.get('type') == 'stop'] == list(inputs)
    assert set(closed) == set(inputs)
    assert records[0]['event'] == 'probe_open'
    assert records[-1]['event'] == 'probe_close'
    before = output.read_text()
    with pytest.raises(FileExistsError):
        probe.main(['--output', str(output)])
    assert output.read_text() == before
