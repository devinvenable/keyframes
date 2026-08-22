"""Headless coverage for the default latch and per-hit strobe behavior."""
import os
import queue
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

import mido
import pygame

from main import (
    DEFAULT_STROBE_MS,
    draw_performance_frame,
    process_midi_messages,
    strobe_is_active,
    toggle_latch_mode,
)


def make_state():
    return {
        'surface': None,
        'video_player': None,
        'note_active': None,
        'note_on_time': None,
        'hold_until': None,
        'zoom_scale': 1.0,
        'strobe_until': 0,
    }


def trigger(queue_, state, note_to_media, now, note):
    with patch('time.monotonic', return_value=now):
        queue_.put(mido.Message('note_on', note=note, velocity=100))
        return process_midi_messages(queue_, 36, 99, note_to_media, (8, 8), state)


def test_default_latch_keeps_media_after_note_off_and_next_hit_swaps_it():
    q = queue.Queue()
    state = make_state()
    media = {
        60: {'type': 'image', 'surface': 'first'},
        62: {'type': 'image', 'surface': 'second'},
    }

    state = trigger(q, state, media, 10.0, 60)
    q.put(mido.Message('note_off', note=60, velocity=0))
    state = process_midi_messages(q, 36, 99, media, (8, 8), state)
    assert state['surface'] == 'first'
    assert state['note_active'] == 60

    state = trigger(q, state, media, 11.0, 62)
    assert state['surface'] == 'second'
    assert state['note_active'] == 62


def test_same_note_retrigger_strobes_black_then_draws_media():
    pygame.init()
    try:
        screen = pygame.Surface((8, 8))
        red = pygame.Surface((8, 8))
        red.fill((255, 0, 0))
        q = queue.Queue()
        state = make_state()
        state = trigger(q, state, {60: {'type': 'image', 'surface': red}}, 10.0, 60)
        state = trigger(q, state, {60: {'type': 'image', 'surface': red}}, 11.0, 60)

        assert state['strobe_until'] == 11.0 + DEFAULT_STROBE_MS / 1000
        assert strobe_is_active(state, 11.01)
        draw_performance_frame(screen, state, (8, 8), 11.01)
        assert screen.get_at((0, 0))[:3] == (0, 0, 0)

        assert not strobe_is_active(state, 11.1)
        draw_performance_frame(screen, state, (8, 8), 11.1)
        assert screen.get_at((0, 0))[:3] == (255, 0, 0)
    finally:
        pygame.quit()


def test_zero_strobe_disables_the_gap():
    q = queue.Queue()
    state = make_state()
    state = trigger(q, state, {60: {'type': 'image', 'surface': 'image'}}, 10.0, 60)

    q.put(mido.Message('note_on', note=60, velocity=100))
    with patch('time.monotonic', return_value=11.0):
        state = process_midi_messages(
            q, 36, 99, {60: {'type': 'image', 'surface': 'image'}}, (8, 8), state,
            strobe_seconds=0,
        )
    assert state['strobe_until'] == 11.0
    assert not strobe_is_active(state, 11.0)


def test_latch_toggle_flips_mode():
    assert toggle_latch_mode(True) is False
    assert toggle_latch_mode(False) is True
