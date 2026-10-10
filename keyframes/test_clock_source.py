"""Clock selection regressions: fake inputs only, never ALSA/virtual ports."""
import json
import queue
from unittest.mock import Mock, patch

import mido
import pygame
import pytest

import main
from test_note_echo import FakePort, PORT_DIRECT, PORT_MIRROR
from test_note_source import rig, CUE, PORT_TWO

RAW = 'RtMidiOut Client:RtMidi output 132:0'
RAW_TWO = RAW.replace('132', '133')


@pytest.mark.parametrize('requested,ports,expected', [
    ('tbox', [RAW, CUE, PORT_DIRECT, PORT_TWO, PORT_MIRROR], PORT_MIRROR),
    ('tbox', [PORT_DIRECT, CUE], CUE),
    ('tbox', [RAW, PORT_TWO, PORT_DIRECT], PORT_DIRECT),
    ('tbox', [RAW, RAW_TWO, PORT_TWO], None),
    ('cues', [PORT_MIRROR, CUE, PORT_DIRECT], CUE),
    ('cues', [PORT_DIRECT, PORT_MIRROR], PORT_MIRROR),
    ('usb', [CUE, PORT_MIRROR, PORT_DIRECT], PORT_DIRECT),
    ('usb', [CUE, PORT_MIRROR], PORT_MIRROR),
    ('tbox', ['TBOX In 1', 'TBOX Out 1'], 'TBOX In 1'),
    ('tbox', ['MIDIPLUS TBOX 2x2 MIDI 1'], 'MIDIPLUS TBOX 2x2 MIDI 1'),
])
def test_selection_and_explicit_fallback_log(tmp_path, capsys, requested, ports, expected):
    path = tmp_path / 'clock.jsonl'
    logger = main.MidiEventLogger(path)
    selected = main.configure_clock_source(ports, requested, logger)
    logger.close()
    assert selected == ({expected} if expected else set())
    record = json.loads(path.read_text().splitlines()[1])
    assert record['event'] == 'clock_source'
    assert record['ports'] == ([expected] if expected else [])
    order = [requested] + [p for p in ('tbox', 'cues', 'usb') if p != requested]
    assert record['fallback_order'] == order
    assert ' > '.join(order) + ' > fallback BPM' in capsys.readouterr().out
    assert bool(record['warning']) == (record['effective'] != requested)


def feed(rig, source, messages, selected, tracker, logger=None):
    media, scenes, visuals, state = rig
    main.process_midi_messages(
        FakePort(messages), 36, 99, media, (64, 64), state,
        clock_tracker=tracker, scenes_config=scenes, visual_control=visuals,
        midi_source=source, midi_logger=logger, note_sources={PORT_DIRECT},
        clock_sources=selected)


@pytest.mark.parametrize('requested', ['tbox', 'cues'])
@pytest.mark.parametrize('reverse', [False, True])
def test_four_mirrored_streams_produce_one_120_bpm_clock(rig, requested, reverse):
    ports = [PORT_MIRROR, CUE, RAW, RAW_TWO]
    selected = main.configure_clock_source(ports, requested)
    tracker = main.MidiClockTracker()
    handler = Mock(wraps=rig[2].handle)
    rig[2].handle = handler
    for tick in range(12):
        for index, port in enumerate(reversed(ports) if reverse else ports):
            with patch('time.monotonic', return_value=10 + tick / 48 + index * .001):
                feed(rig, port, [mido.Message('clock')], selected, tracker)
    assert len(tracker._clock_times) == 12
    assert tracker.bpm == pytest.approx(120)
    # Transport and cues bypass clock selection, even on a rejected port.
    for port in ports:
        feed(rig, port, [mido.Message(kind) for kind in ('start', 'stop', 'continue')],
             selected, tracker)
    feed(rig, CUE, [mido.Message('program_change', program=3)], selected, tracker)
    assert rig[2].take_pending_program() == 3
    assert [c.args[0].type for c in handler.call_args_list] == [
        'start', 'stop', 'continue'] * 4 + ['program_change']


@pytest.mark.parametrize('use_queue', [False, True])
def test_filter_precedes_process_cap_but_keeps_read_bound(use_queue):
    class PendingPort(FakePort):
        def iter_pending(self):
            while self.msgs:
                yield self.msgs.pop(0)

    messages = [mido.Message('clock')] * 4 + [mido.Message('active_sensing'),
                                            mido.Message('stop')]
    source = queue.Queue() if use_queue else PendingPort(messages)
    if use_queue:
        for msg in messages:
            source.put(msg)
    logger = Mock()
    accepted, dropped = main.read_midi_messages(
        source, process_cap=1, read_cap=5, clock_source_allowed=False,
        midi_logger=logger, midi_source=RAW)
    # Without early filtering, active_sensing is flood-shed. The final Stop
    # stays unread: ignored clocks still count against the raw-read bound.
    assert accepted == [mido.Message('active_sensing')]
    assert dropped == {}
    assert logger.log_filtered_source.call_count == 4
    if use_queue:
        assert source.get_nowait().type == 'stop'
    else:
        assert list(source.iter_pending()) == [mido.Message('stop')]


def test_rejected_clocks_have_bounded_summaries_and_close_flush(rig, tmp_path):
    path = tmp_path / 'clock.jsonl'
    logger = main.MidiEventLogger(path)
    tracker = main.MidiClockTracker()
    for now in (10, 11, 12, 15, 16):
        with patch('time.monotonic', return_value=now):
            feed(rig, RAW, [mido.Message('clock')], {PORT_MIRROR}, tracker, logger)
    feed(rig, PORT_MIRROR, [mido.Message('clock')], {PORT_MIRROR}, tracker, logger)
    before = [json.loads(line) for line in path.read_text().splitlines()]
    assert len([r for r in before if r.get('event') == 'clock_source_filtered']) == 2
    logger.close()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    summaries = [r for r in records if r.get('event') == 'clock_source_filtered']
    assert [r['counts'] for r in summaries] == [{'clock': 1}, {'clock': 3}, {'clock': 1}]
    assert all(r['port'] == RAW for r in summaries)
    assert [r['port'] for r in records if r.get('type') == 'clock'] == [PORT_MIRROR]


@pytest.mark.parametrize('mode', ['inproc', 'process'])
@pytest.mark.parametrize('args,missing,expected', [
    ([], None, PORT_MIRROR), (['--clock-source', 'usb'], None, PORT_DIRECT),
    ([], PORT_MIRROR, CUE), (['--clock-source', 'cues'], None, CUE)])
def test_main_wires_clock_selection(rig, tmp_path, monkeypatch, mode, args, missing, expected):
    path = tmp_path / 'main.jsonl'
    monkeypatch.setenv('KEYFRAMES_MIDI_LOG', str(path))
    monkeypatch.delenv('KEYFRAMES_STALL_LOG', raising=False)
    monkeypatch.delenv('KEYFRAMES_BANK_STATE', raising=False)
    monkeypatch.setattr('sys.argv', ['keyframes', '--midi-io', mode,
                                   '--windowed', '--size', '64x64'] + args)
    ports = [PORT_DIRECT, PORT_MIRROR, CUE, RAW, RAW_TWO]
    monkeypatch.setattr(main.mido, 'get_input_names', lambda: ports)

    def open_input(name):
        if name == missing:
            raise OSError('disconnected test port')
        port = FakePort([mido.Message('clock')])
        port.name = name
        port.close = lambda: None
        return port

    monkeypatch.setattr(main.mido, 'open_input', open_input)
    proxy = Mock()
    proxy.sources = {p: open_input(p) for p in ports if p != missing}
    proxy.poll.return_value = [{'kind': 'ports', 'names': list(proxy.sources)}]
    monkeypatch.setattr(main, 'MidiInputs', lambda *args: proxy)
    monkeypatch.setattr(main, 'drain_startup_midi', lambda ports: 0)
    monkeypatch.setattr(pygame.event, 'get', lambda: [pygame.event.Event(pygame.QUIT)])
    main.main()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    selected = next(r for r in records if r.get('event') == 'clock_source')
    assert selected['ports'] == [expected]
    assert [r['port'] for r in records if r.get('type') == 'clock'] == [expected]


@pytest.mark.parametrize('mode', ['inproc', 'process'])
def test_main_reselects_fallback_after_cue_disappears_and_returns(
        rig, tmp_path, monkeypatch, mode):
    path = tmp_path / 'reconnect.jsonl'
    monkeypatch.setenv('KEYFRAMES_MIDI_LOG', str(path))
    monkeypatch.delenv('KEYFRAMES_STALL_LOG', raising=False)
    monkeypatch.delenv('KEYFRAMES_BANK_STATE', raising=False)
    monkeypatch.setattr('sys.argv', ['keyframes', '--midi-io', mode,
                                   '--windowed', '--size', '64x64'])
    renamed = CUE.replace('128:0', '129:0')
    snapshots = iter([[CUE, RAW], [RAW], [renamed, RAW], [renamed, RAW]])
    monkeypatch.setattr(main.mido, 'get_input_names', lambda: next(snapshots))

    def open_input(name):
        port = FakePort([mido.Message('clock')])
        port.name = name
        port.close = lambda: None
        return port

    monkeypatch.setattr(main.mido, 'open_input', open_input)
    proxy = Mock()

    def poll():
        names = next(snapshots)
        proxy.sources = {p: open_input(p) for p in names}
        return [{'kind': 'ports', 'names': names}]

    proxy.poll.side_effect = poll
    monkeypatch.setattr(main, 'MidiInputs', lambda *args: proxy)
    monkeypatch.setattr(main, 'CUE_PORT_RESCAN_S', 0)
    monkeypatch.setattr(main, 'drain_startup_midi', lambda ports: 0)
    events = iter([[], [], [pygame.event.Event(pygame.QUIT)]])
    monkeypatch.setattr(pygame.event, 'get', lambda: next(events))
    main.main()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    selections = [r['ports'] for r in records if r.get('event') == 'clock_source']
    assert selections == [[CUE], [], [renamed]]
    assert [r['port'] for r in records if r.get('type') == 'clock'] == [CUE, renamed]
