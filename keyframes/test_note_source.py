"""Single-source routing through mirrored rig delivery and real main startup."""
import json
import os
from unittest.mock import Mock, patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import mido
import pygame
import pytest

import main
from test_note_echo import FakePort, NOTE, PORT_DIRECT, PORT_MIRROR, no_args_startup

CUE = 'ShowSync:ShowSync Cues 128:0'
PORT_TWO = PORT_MIRROR.replace('Out 1', 'Out 2')


@pytest.fixture
def rig(tmp_path, monkeypatch):
    pygame.init()
    pygame.display.set_mode((64, 64))
    env = no_args_startup(tmp_path, monkeypatch, {'enabled': False})
    yield env
    pygame.quit()


def feed(rig, source, messages, selected, now=10.0, logger=None, clock=None):
    media, scenes, visuals, state = rig
    with patch('time.monotonic', return_value=now):
        main.process_midi_messages(
            FakePort(messages), 36, 99, media, (64, 64), state,
            clock_tracker=clock, latch_mode=False, scenes_config=scenes,
            midi_logger=logger, midi_source=source, visual_control=visuals,
            note_sources=selected)


@pytest.mark.parametrize('port', [PORT_MIRROR, PORT_MIRROR.replace('Out 1', 'In 1'),
                                 'MIDIPLUS TBOX 2x2 MIDI 1', 'TBOX In 1'])
def test_default_selects_only_tbox_port_one(port):
    selected = main.configure_note_source([PORT_TWO, CUE, PORT_DIRECT, port])
    assert selected == {port}


@pytest.mark.parametrize('requested,available,effective', [
    ('tbox', PORT_DIRECT, 'usb'), ('usb', PORT_MIRROR, 'tbox')])
def test_missing_source_falls_back_and_logs(tmp_path, capsys, requested, available, effective):
    path = tmp_path / 'take.jsonl'
    logger = main.MidiEventLogger(path)
    selected = main.configure_note_source([PORT_TWO, CUE, available], requested, logger)
    logger.close()
    assert selected == {available}
    assert 'WARNING: MIDI NOTE SOURCE:' in capsys.readouterr().out
    record = json.loads(path.read_text().splitlines()[1])
    assert record['event'] == 'note_source'
    assert record['requested'] == requested and record['effective'] == effective
    assert record['ports'] == [available]
    assert 'falling back' in record['warning']


def test_neither_source_does_not_select_tbox_two_or_cues(capsys):
    assert main.configure_note_source([PORT_TWO, CUE]) == set()
    assert 'neither TBOX In 1 nor KeyStep USB is open' in capsys.readouterr().out


@pytest.mark.parametrize('mode,accepted,rejected', [
    ('tbox', PORT_MIRROR, PORT_DIRECT), ('usb', PORT_DIRECT, PORT_MIRROR)])
@pytest.mark.parametrize('ignored_first', [True, False])
def test_mirrored_notes_and_controls_only_act_on_selected_source(
        rig, mode, accepted, rejected, ignored_first):
    selected = main.configure_note_source([PORT_DIRECT, PORT_MIRROR, PORT_TWO], mode)
    state = rig[3]
    on = mido.Message('note_on', note=NOTE, velocity=100)
    off = mido.Message('note_off', note=NOTE)
    frames = []
    for hit in range(4):
        # Long gap between mirrored copies defeats echo dedup: only source
        # selection can make this pass. Each real press must toggle once.
        for index, port in enumerate(([rejected, accepted] if ignored_first
                                      else [accepted, rejected])):
            before = dict(state)
            feed(rig, port, [on.copy()], selected, now=10 + hit * 2 + index * .1)
            if port == rejected:
                assert state == before
        assert state['note_active'] == NOTE
        assert state['inverted'] is bool(hit % 2)
        main.draw_performance_frame(pygame.display.get_surface(), state, (64, 64))
        frames.append(bytes(pygame.image.tobytes(pygame.display.get_surface(), 'RGB')))
        # Ignore both ordinary note-off and velocity-zero note-on releases.
        feed(rig, rejected, [off, on.copy(velocity=0)], selected, now=11 + hit * 2)
        assert state['note_active'] == NOTE
        feed(rig, accepted, [off], selected, now=11.1 + hit * 2)
        assert state['note_active'] is None
    assert all(a != b for a, b in zip(frames, frames[1:]))

    controls = [mido.Message('control_change', control=1, value=127),
                mido.Message('pitchwheel', pitch=8191),
                mido.Message('control_change', control=main.SCENE_CC_ENABLED, value=127),
                mido.Message('program_change', program=2)]
    for port in (rejected, PORT_TWO):
        feed(rig, port, controls, selected)
        assert state['pan'] == 0.0 and state['bend_zoom'] == 1.0
        assert rig[2].scenes()['enabled'] is False
        assert rig[2].take_pending_program() is None
    feed(rig, accepted, controls, selected)
    assert state['pan'] == 1.0 and state['bend_zoom'] > 1.0
    assert rig[2].scenes()['enabled'] is True
    assert rig[2].take_pending_program() == 2


def test_all_keeps_legacy_echo_dedup(rig):
    selected = main.configure_note_source([PORT_DIRECT, PORT_MIRROR], 'all')
    assert selected is None
    on = mido.Message('note_on', note=NOTE, velocity=100)
    for hit in range(4):
        feed(rig, PORT_DIRECT, [on], selected, now=10 + hit)
        feed(rig, PORT_MIRROR, [on.copy()], selected, now=10.002 + hit)
        assert rig[3]['inverted'] is bool(hit % 2)


def test_clock_transport_and_reconnected_cues_bypass_selection(rig):
    selected = main.configure_note_source([PORT_DIRECT, PORT_MIRROR, CUE])
    clock = Mock()
    handler = Mock(wraps=rig[2].handle)
    rig[2].handle = handler
    messages = [mido.Message(kind) for kind in ('clock', 'start', 'stop', 'continue')]
    for source in (PORT_DIRECT, PORT_MIRROR, CUE):
        feed(rig, source, messages, selected, clock=clock)
    assert clock.tick.call_count == 3
    assert [call.args[0].type for call in handler.call_args_list] == [
        'start', 'stop', 'continue'] * 3
    # A cue port can reappear with a new ALSA id after ShowSync relaunches.
    feed(rig, CUE.replace('128:0', '129:0'), [
        mido.Message('program_change', program=3),
        mido.Message('control_change', control=main.SCENE_CC_ENABLED, value=127)],
        selected)
    assert rig[2].take_pending_program() == 3
    assert rig[2].scenes()['enabled'] is True


def test_ignored_arrivals_have_bounded_summaries_and_close_flush(rig, tmp_path):
    path = tmp_path / 'take.jsonl'
    logger = main.MidiEventLogger(path)
    selected = main.configure_note_source([PORT_DIRECT, PORT_MIRROR], midi_logger=logger)
    on = mido.Message('note_on', note=NOTE, velocity=100)
    for now in (10.0, 11.0, 12.0, 15.0, 16.0):
        feed(rig, PORT_DIRECT, [on], selected, now=now, logger=logger)
    feed(rig, PORT_MIRROR, [on], selected, now=16.002, logger=logger)
    before_close = [json.loads(line) for line in path.read_text().splitlines()]
    assert len([r for r in before_close if r.get('event') == 'note_source_filtered']) == 2
    logger.close()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    summaries = [r for r in records if r.get('event') == 'note_source_filtered']
    assert [r['counts'] for r in summaries] == [{'note_on': 1}, {'note_on': 3}, {'note_on': 1}]
    assert all(r['port'] == PORT_DIRECT for r in summaries)
    raw = [r for r in records if r.get('type') == 'note_on']
    assert len(raw) == 1 and raw[0]['port'] == PORT_MIRROR and raw[0]['mapped']


@pytest.mark.parametrize('args,missing,expected', [
    ([], None, PORT_MIRROR), (['--note-source', 'usb'], None, PORT_DIRECT),
    ([], PORT_MIRROR, PORT_DIRECT),
    (['--note-source', 'usb'], PORT_DIRECT, PORT_MIRROR)])
def test_main_wires_default_cli_and_open_failure_fallback(
        rig, tmp_path, monkeypatch, args, missing, expected):
    """Run a headless frame through actual argparse/startup/main-loop wiring.

    Fake inputs only: never attach to or send to the live rig/cue port.
    """
    path = tmp_path / 'main.jsonl'
    monkeypatch.setenv('KEYFRAMES_MIDI_LOG', str(path))
    monkeypatch.delenv('KEYFRAMES_STALL_LOG', raising=False)
    monkeypatch.delenv('KEYFRAMES_BANK_STATE', raising=False)
    monkeypatch.setattr('sys.argv', ['keyframes', '--windowed', '--size', '64x64'] + args)
    monkeypatch.setattr(main.mido, 'get_input_names', lambda: [PORT_DIRECT, PORT_MIRROR, CUE])

    def open_input(name):
        if name == missing:
            raise OSError('test disconnected port')
        port = FakePort([mido.Message('note_on', note=NOTE, velocity=100)])
        port.name = name
        port.close = lambda: None
        return port

    monkeypatch.setattr(main.mido, 'open_input', open_input)
    monkeypatch.setattr(main, 'drain_startup_midi', lambda ports: 0)
    monkeypatch.setattr(pygame.event, 'get', lambda: [
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_z, mod=0),
        pygame.event.Event(pygame.QUIT)])
    main.main()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    selection = next(r for r in records if r.get('event') == 'note_source')
    assert selection['ports'] == [expected]
    raw_ports = {r['port'] for r in records if r.get('type') == 'note_on'}
    assert raw_ports == {expected, CUE, 'keyboard'}
    if missing:
        assert 'falling back' in selection['warning']
