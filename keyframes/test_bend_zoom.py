"""Headless coverage for pitch-bend live zoom and mod-wheel pan (task 199)."""
import os
import queue

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import mido
import pygame
import pytest

import main
from main import (
    MAX_PITCH_BEND_ZOOM,
    effective_zoom_scale,
    mod_wheel_pan,
    pitch_bend_zoom_scale,
    process_midi_messages,
    render_still,
    zoom_surface_to_screen,
)


@pytest.fixture(scope='module', autouse=True)
def _pygame_init():
    pygame.init()
    pygame.display.set_mode((800, 600))
    yield
    pygame.quit()


def make_state(**overrides):
    state = {
        'surface': None,
        'surface_media': None,
        'video_player': None,
        'note_active': None,
        'note_on_time': None,
        'hold_until': None,
        'zoom_scale': 1.0,
        'bend_zoom': 1.0,
        'pan': 0.0,
        'inverted': False,
        'last_note': None,
    }
    state.update(overrides)
    return state


def feed(state, *messages, channel=None):
    q = queue.Queue()
    for msg in messages:
        q.put(msg)
    return process_midi_messages(q, 36, 99, {}, (8, 8), state, channel)


# --- mapping functions -------------------------------------------------------

def test_pitch_bend_center_and_below_is_no_zoom():
    assert pitch_bend_zoom_scale(0) == 1.0
    assert pitch_bend_zoom_scale(-1) == 1.0
    assert pitch_bend_zoom_scale(-8192) == 1.0


def test_pitch_bend_maps_continuously_to_max_zoom():
    assert pitch_bend_zoom_scale(8191) == pytest.approx(MAX_PITCH_BEND_ZOOM)
    half = pitch_bend_zoom_scale(4096)
    assert 1.0 < half < MAX_PITCH_BEND_ZOOM
    assert half == pytest.approx(1.0 + (4096 / 8191) * (MAX_PITCH_BEND_ZOOM - 1))
    # Monotonic, unquantized: every step up bends further in.
    assert pitch_bend_zoom_scale(100) < pitch_bend_zoom_scale(101)


def test_mod_wheel_pan_rest_is_centered_full_is_right_edge():
    assert mod_wheel_pan(0) == 0.0
    assert mod_wheel_pan(127) == 1.0
    assert 0.0 < mod_wheel_pan(64) < 1.0


# --- message handling --------------------------------------------------------

def test_pitchwheel_message_sets_bend_zoom():
    state = feed(make_state(), mido.Message('pitchwheel', pitch=8191))
    assert state['bend_zoom'] == pytest.approx(MAX_PITCH_BEND_ZOOM)
    state = feed(state, mido.Message('pitchwheel', pitch=0))
    assert state['bend_zoom'] == 1.0


def test_mod_wheel_message_sets_pan_other_ccs_ignored():
    state = feed(make_state(), mido.Message('control_change', control=1, value=127))
    assert state['pan'] == 1.0
    state = feed(state, mido.Message('control_change', control=7, value=0))
    assert state['pan'] == 1.0  # CC7 (volume) must not touch pan


def test_bend_and_pan_respect_channel_filter():
    state = make_state()
    state = feed(state,
                 mido.Message('pitchwheel', pitch=8191, channel=5),
                 mido.Message('control_change', control=1, value=127, channel=5),
                 channel=3)
    assert state['bend_zoom'] == 1.0
    assert state['pan'] == 0.0
    state = feed(state,
                 mido.Message('pitchwheel', pitch=8191, channel=3),
                 mido.Message('control_change', control=1, value=127, channel=3),
                 channel=3)
    assert state['bend_zoom'] == pytest.approx(MAX_PITCH_BEND_ZOOM)
    assert state['pan'] == 1.0


def test_bend_zoom_composes_with_zoom_ring():
    state = make_state(zoom_scale=1.5, bend_zoom=2.0)
    assert effective_zoom_scale(state) == pytest.approx(3.0)
    # And survives states built before this feature existed.
    del state['bend_zoom']
    assert effective_zoom_scale(state) == pytest.approx(1.5)


def test_bend_zoom_persists_across_note_off_clear():
    state = make_state(bend_zoom=2.0, pan=0.5, note_active=60,
                       surface='x', last_note=60)
    state = feed(state, mido.Message('note_off', note=60, velocity=0))
    # (latch defaults on, but even a clear must not reset the physical wheels)
    assert state['bend_zoom'] == 2.0
    assert state['pan'] == 0.5


# --- rendering ---------------------------------------------------------------

@pytest.mark.parametrize('display_mode', ['fill', 'fit'])
def test_pan_shifts_zoom_window_across_overflow(display_mode):
    surface = pygame.Surface((100, 100))
    target = (100, 100)
    # zoom 2.0 -> 200x200 zoomed, 100px horizontal overflow
    center = zoom_surface_to_screen(surface, target, 2.0, display_mode, 0.0)
    left = zoom_surface_to_screen(surface, target, 2.0, display_mode, -1.0)
    right = zoom_surface_to_screen(surface, target, 2.0, display_mode, 1.0)
    assert center.get_size() == left.get_size() == right.get_size() == target
    assert center.get_offset() == (50, 50)
    assert left.get_offset() == (0, 50)
    assert right.get_offset() == (100, 50)


@pytest.mark.parametrize('display_mode', ['fill', 'fit'])
def test_pan_is_noop_without_zoom(display_mode):
    surface = pygame.Surface((80, 60))
    plain = zoom_surface_to_screen(surface, (100, 100), 1.0, display_mode, 0.0)
    panned = zoom_surface_to_screen(surface, (100, 100), 1.0, display_mode, 1.0)
    assert plain.get_size() == panned.get_size() == (100, 100)
    # No overflow to pan across: identical pixels either way.
    assert (pygame.surfarray.array3d(plain)
            == pygame.surfarray.array3d(panned)).all()


def test_fit_mode_zoom_overflows_into_bars_with_bend():
    # A wide source in fit mode has letterbox bars; bend-zooming must grow the
    # letterboxed frame (same semantics as the zoom ring).
    surface = pygame.Surface((200, 100))
    surface.fill((250, 10, 10))
    zoomed = zoom_surface_to_screen(surface, (100, 100), 2.0, 'fit', 0.0)
    assert zoomed.get_size() == (100, 100)
    # Center row was media before and stays media after.
    assert zoomed.get_at((50, 50))[:3] == (250, 10, 10)


def test_render_still_caches_until_inputs_change():
    surface = pygame.Surface((64, 64))
    state = make_state()
    first = render_still(state, surface, (32, 32), 2.0, 'fill', 0.0)
    again = render_still(state, surface, (32, 32), 2.0, 'fill', 0.0)
    assert again is first  # unchanged inputs: no per-frame rescale
    moved = render_still(state, surface, (32, 32), 2.0, 'fill', 0.5)
    assert moved is not first
    zoomed = render_still(state, surface, (32, 32), 3.0, 'fill', 0.5)
    assert zoomed is not moved


def test_draw_performance_frame_applies_live_bend_to_latched_still():
    surface = pygame.Surface((100, 100))
    surface.fill((10, 200, 30))
    screen = pygame.Surface((50, 50))
    state = make_state(surface=surface)
    main.draw_performance_frame(screen, state, (50, 50))
    unbent = state['still_render'][0]
    state['bend_zoom'] = 2.0
    main.draw_performance_frame(screen, state, (50, 50))
    assert state['still_render'][0] != unbent  # re-rendered at the new scale
    assert screen.get_at((25, 25))[:3] == (10, 200, 30)
