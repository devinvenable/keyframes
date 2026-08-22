"""Headless coverage for the default latch mode and same-note invert flash."""
import os
import queue
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

import mido
import pygame

from main import (
    draw_performance_frame,
    inverted_surface,
    process_midi_messages,
    toggle_latch_mode,
)


def make_state():
    return {
        'surface': None,
        'surface_media': None,
        'video_player': None,
        'note_active': None,
        'note_on_time': None,
        'hold_until': None,
        'zoom_scale': 1.0,
        'inverted': False,
        'last_note': None,
    }


def trigger(queue_, state, note_to_media, now, note):
    with patch('time.monotonic', return_value=now):
        queue_.put(mido.Message('note_on', note=note, velocity=100))
        return process_midi_messages(queue_, 36, 99, note_to_media, (8, 8), state)


def test_invert_toggles_only_on_same_note_image_repeat():
    q = queue.Queue()
    state = make_state()
    media = {
        60: {'type': 'image', 'surface': 'a'},
        62: {'type': 'image', 'surface': 'b'},
    }
    # First hit of 60: not a repeat -> normal.
    state = trigger(q, state, media, 10.0, 60)
    assert state['inverted'] is False
    # Same note again -> flips to negative.
    state = trigger(q, state, media, 11.0, 60)
    assert state['inverted'] is True
    # And again -> flips back to normal (toggle).
    state = trigger(q, state, media, 12.0, 60)
    assert state['inverted'] is False
    # Switch to a different note -> always normal.
    state = trigger(q, state, media, 13.0, 62)
    assert state['inverted'] is False
    assert state['surface'] == 'b'


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


def test_same_note_repeat_draws_negative_then_back_to_normal():
    pygame.init()
    try:
        pygame.display.set_mode((8, 8))
        screen = pygame.Surface((8, 8))
        red = pygame.Surface((8, 8)).convert_alpha()
        red.fill((255, 0, 0, 255))
        media = {60: {'type': 'image', 'surface': red, 'name': 'r.png'}}

        q = queue.Queue()
        state = make_state()
        # First hit: normal red.
        state = trigger(q, state, media, 10.0, 60)
        draw_performance_frame(screen, state, (8, 8), 10.0)
        assert screen.get_at((0, 0))[:3] == (255, 0, 0)
        # Same-note repeat: negative of red -> cyan (0, 255, 255).
        state = trigger(q, state, media, 11.0, 60)
        draw_performance_frame(screen, state, (8, 8), 11.0)
        assert screen.get_at((0, 0))[:3] == (0, 255, 255)
        # Repeat again toggles back to normal red.
        state = trigger(q, state, media, 12.0, 60)
        draw_performance_frame(screen, state, (8, 8), 12.0)
        assert screen.get_at((0, 0))[:3] == (255, 0, 0)
    finally:
        pygame.quit()


def test_inverted_surface_is_cached_and_negative():
    pygame.init()
    try:
        pygame.display.set_mode((4, 4))
        src = pygame.Surface((4, 4)).convert_alpha()
        src.fill((10, 20, 30, 255))
        media = {'type': 'image', 'surface': src, 'name': 'x.png'}
        inv = inverted_surface(media)
        assert inv.get_at((0, 0))[:3] == (245, 235, 225)  # 255 - (10,20,30)
        assert inverted_surface(media) is inv  # cached, not recomputed
    finally:
        pygame.quit()


def test_latch_toggle_flips_mode():
    assert toggle_latch_mode(True) is False
    assert toggle_latch_mode(False) is True
