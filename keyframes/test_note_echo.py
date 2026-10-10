"""Cross-port note-echo suppression (task 269).

One physical key press reaches Keyframes on TWO ports at once in the live
rig: the KeyStep's USB port directly, and its DIN OUT mirrored through the
thru box into a TBOX input. No-args startup auto-opens both, so the duplicate
note-on toggled the same-note invert a second time within milliseconds —
every press parked on the negative copy and hammering a key never visibly
toggled, with scenes enabled OR disabled (which is why the task-250 fix and
its single-source tests didn't catch it).

These tests go through the REAL no-args startup path: MediaBanks.load of the
default bank from a temp APP_DIR layout, scenes config read from a real
scenes.json carrying Devin's live values, the exact initial state dict from
main(), and a VisualControl — then feed the same note through two port
sources the way the main loop polls its inports.
"""
import json
import os
import queue
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

import mido
import pygame
import pytest

import main
from main import (
    MediaBanks,
    MidiClockTracker,
    VisualControl,
    draw_performance_frame,
    process_midi_messages,
)

PORT_DIRECT = 'Arturia KeyStep 32:Arturia KeyStep 32 MIDI 1 44:0'
PORT_MIRROR = 'MIDIPLUS TBOX 2x2:MIDIPLUS TBOX 2x2 Midi Out 1 36:0'
NOTE = 41  # KeyStep bottom key


class FakePort:
    """Stands in for a mido input: iter_pending drains once, like the loop."""

    def __init__(self, msgs):
        self.msgs = list(msgs)

    def iter_pending(self):
        msgs, self.msgs = self.msgs, []
        return iter(msgs)


@pytest.fixture
def screen():
    pygame.init()
    return pygame.display.set_mode((64, 64))


def no_args_startup(tmp_path, monkeypatch, scenes_json):
    """Replicate main()'s bank='default' startup against a temp APP_DIR."""
    images = tmp_path / 'images'
    images.mkdir()
    surf = pygame.Surface((32, 32))
    surf.fill((200, 30, 30))
    pygame.draw.rect(surf, (20, 200, 20), (8, 8, 16, 16))
    pygame.image.save(surf, str(images / 'still.png'))
    (tmp_path / 'mapping.json').write_text(json.dumps({str(NOTE): 'still.png'}))
    (tmp_path / 'scenes.json').write_text(json.dumps(scenes_json))

    monkeypatch.setattr(main, 'IMAGES_DIR', str(images))
    monkeypatch.setattr(main, 'MAPPING_PATH', str(tmp_path / 'mapping.json'))
    monkeypatch.setattr(main, 'SCENES_CONFIG_PATH', str(tmp_path / 'scenes.json'))
    monkeypatch.setattr(main, 'OVERLAYS_CONFIG_PATH', str(tmp_path / 'overlays.json'))
    monkeypatch.setattr(main, 'BANKS_DIR', tmp_path / 'banks')

    banks = MediaBanks(main.DEFAULT_START_NOTE,
                       main.DEFAULT_START_NOTE + main.DEFAULT_NUM_KEYS - 1)
    note_to_media, _cells, scenes_config = banks.load('default', startup=True)
    assert note_to_media[NOTE]['type'] == 'image'

    state = {'surface': None, 'video_player': None, 'note_active': None,
             'note_on_time': None, 'hold_until': None, 'zoom_scale': 1.0,
             'bend_zoom': 1.0, 'pan': 0.0, 'pan_cc_time': None, 'pan_ease': None,
             'inverted': False, 'surface_media': None, 'last_note': None,
             'active_scene': None}
    return note_to_media, scenes_config, VisualControl(scenes_config), state


def deliver(state, msgs, source, env, now):
    note_to_media, scenes_config, visuals, clock_tracker = env
    with patch('time.monotonic', return_value=now):
        return process_midi_messages(
            FakePort(msgs), main.DEFAULT_START_NOTE,
            main.DEFAULT_START_NOTE + main.DEFAULT_NUM_KEYS - 1,
            note_to_media, (64, 64), state, None, clock_tracker, None, False,
            {}, None, True, 'fill', scenes_config, None, source,
            visual_control=visuals)


def hammer(state, env, screen, hits, dt=0.15, mirror_dt=0.002):
    """Press NOTE `hits` times; each press lands on both ports like the rig.

    Returns (inverted flags, rendered frame bytes), one entry per press."""
    inverts, frames = [], []
    for i in range(hits):
        t = 10.0 + i * dt
        on = mido.Message('note_on', note=NOTE, velocity=100)
        state = deliver(state, [on], PORT_DIRECT, env, t)
        state = deliver(state, [on.copy()], PORT_MIRROR, env, t + mirror_dt)
        draw_performance_frame(screen, state, (64, 64), now=t + 0.01)
        inverts.append(state['inverted'])
        frames.append(bytes(pygame.image.tobytes(screen, 'RGB')))
        off = mido.Message('note_off', note=NOTE, velocity=0)
        state = deliver(state, [off], PORT_DIRECT, env, t + 0.05)
        state = deliver(state, [off.copy()], PORT_MIRROR, env, t + 0.052)
    return state, inverts, frames


def test_no_args_two_port_hammering_toggles_invert_scenes_disabled(
        tmp_path, monkeypatch, screen):
    """Devin's live repro: scenes.json {"enabled": false}, one key hammered,
    every press mirrored onto a second port. Each press must alternate
    normal/negative — on state AND on the rendered pixels."""
    note_to_media, scenes_config, visuals, state = no_args_startup(
        tmp_path, monkeypatch, {'enabled': False})
    env = (note_to_media, scenes_config, visuals, MidiClockTracker())
    state, inverts, frames = hammer(state, env, screen, 12)
    assert inverts == [bool(i % 2) for i in range(12)]
    for i in range(1, 12):
        assert frames[i] != frames[i - 1]


def test_no_args_two_port_hammering_toggles_invert_scenes_low_probability(
        tmp_path, monkeypatch, screen):
    """Same with his stashed scenes config values {enabled: true, 0.05},
    rng pinned above the threshold so no scene takes over the frame — the
    scenes-enabled trigger path itself must keep the toggle alive."""
    note_to_media, scenes_config, visuals, state = no_args_startup(
        tmp_path, monkeypatch, {'enabled': True, 'probability': 0.05})
    assert scenes_config == {'enabled': True, 'probability': 0.05}
    env = (note_to_media, scenes_config, visuals, MidiClockTracker())
    with patch('main.random.random', return_value=0.9):
        state, inverts, frames = hammer(state, env, screen, 12)
    assert inverts == [bool(i % 2) for i in range(12)]
    for i in range(1, 12):
        assert frames[i] != frames[i - 1]


def test_same_port_fast_repeats_are_not_suppressed(
        tmp_path, monkeypatch, screen):
    """Echo suppression is cross-port only: genuine fast retriggers on ONE
    port — faster than the echo window — must all process and keep toggling."""
    note_to_media, scenes_config, visuals, state = no_args_startup(
        tmp_path, monkeypatch, {'enabled': False})
    env = (note_to_media, scenes_config, visuals, MidiClockTracker())
    for i in range(4):
        on = mido.Message('note_on', note=NOTE, velocity=100)
        state = deliver(state, [on], PORT_DIRECT, env, 10.0 + i * 0.01)
        assert state['inverted'] is bool(i % 2)


def test_different_notes_across_ports_both_display(
        tmp_path, monkeypatch, screen):
    """Two performers on two ports (KeyStep + David via TBOX In 2): different
    notes near-simultaneously are NOT echoes and must both trigger."""
    note_to_media, scenes_config, visuals, state = no_args_startup(
        tmp_path, monkeypatch, {'enabled': False})
    other = NOTE + 1
    note_to_media[other] = {'type': 'image',
                            'surface': note_to_media[NOTE]['surface'],
                            'name': 'still.png'}
    env = (note_to_media, scenes_config, visuals, MidiClockTracker())
    state = deliver(state, [mido.Message('note_on', note=NOTE, velocity=100)],
                    PORT_DIRECT, env, 10.0)
    assert state['note_active'] == NOTE
    state = deliver(state, [mido.Message('note_on', note=other, velocity=100)],
                    PORT_MIRROR, env, 10.002)
    assert state['note_active'] == other
    assert state['inverted'] is False


def test_mirrored_note_off_is_suppressed_and_logged(
        tmp_path, monkeypatch, screen):
    """Non-latch: the release pair must also dedup — exactly one note_off
    acts — and every suppressed echo is written to the MIDI event log."""
    note_to_media, scenes_config, visuals, state = no_args_startup(
        tmp_path, monkeypatch, {'enabled': False})
    clock_tracker = MidiClockTracker()
    logger = main.MidiEventLogger(str(tmp_path / 'take.midi.jsonl'))

    def send(state, msg, source, now):
        with patch('time.monotonic', return_value=now):
            return process_midi_messages(
                FakePort([msg]), main.DEFAULT_START_NOTE,
                main.DEFAULT_START_NOTE + main.DEFAULT_NUM_KEYS - 1,
                note_to_media, (64, 64), state, None, clock_tracker, None,
                False, {}, None, False, 'fill', scenes_config, logger, source,
                visual_control=visuals)

    state = send(state, mido.Message('note_on', note=NOTE, velocity=100),
                 PORT_DIRECT, 10.0)
    state = send(state, mido.Message('note_on', note=NOTE, velocity=100),
                 PORT_MIRROR, 10.002)
    assert state['note_active'] == NOTE
    state = send(state, mido.Message('note_off', note=NOTE, velocity=0),
                 PORT_DIRECT, 11.0)
    assert state['note_active'] is None
    state = send(state, mido.Message('note_off', note=NOTE, velocity=0),
                 PORT_MIRROR, 11.002)
    assert state['note_active'] is None
    logger.close()

    records = [json.loads(line)
               for line in (tmp_path / 'take.midi.jsonl').read_text().splitlines()]
    suppressed = [r for r in records if r.get('event') == 'note_echo_suppressed']
    assert [(r['type'], r['port'], r['echo_of_port']) for r in suppressed] == [
        ('note_on', PORT_MIRROR, PORT_DIRECT),
        ('note_off', PORT_MIRROR, PORT_DIRECT),
    ]
    # Ground truth is intact: all four raw arrivals were still logged.
    raw = [r for r in records if 'event' not in r and r.get('note') == NOTE]
    assert len(raw) == 4


def test_echo_window_expires_so_next_press_on_other_port_triggers(
        tmp_path, monkeypatch, screen):
    """A press on port A followed WELL after the window by a press on port B
    (e.g. performer switches controllers) is two real presses: the second is
    a same-note repeat and must invert."""
    note_to_media, scenes_config, visuals, state = no_args_startup(
        tmp_path, monkeypatch, {'enabled': False})
    env = (note_to_media, scenes_config, visuals, MidiClockTracker())
    state = deliver(state, [mido.Message('note_on', note=NOTE, velocity=100)],
                    PORT_DIRECT, env, 10.0)
    assert state['inverted'] is False
    state = deliver(state, [mido.Message('note_on', note=NOTE, velocity=100)],
                    PORT_MIRROR, env, 11.0)
    assert state['inverted'] is True
