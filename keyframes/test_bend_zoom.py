"""Headless coverage for pitch-bend live zoom and mod-wheel pan (tasks 199/201)."""
import os
import queue
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import mido
import pygame
import pytest

import main
from main import (
    MAX_PITCH_BEND_ZOOM,
    PAN_AUTO_RECENTER,
    PAN_RECENTER_DELAY,
    PAN_RECENTER_SECONDS,
    effective_zoom_scale,
    mod_wheel_pan,
    pitch_bend_zoom_scale,
    process_midi_messages,
    render_still,
    update_pan_recenter,
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


def test_mod_wheel_pan_is_bipolar_around_64():
    assert mod_wheel_pan(64) == 0.0
    assert mod_wheel_pan(0) == -1.0
    assert mod_wheel_pan(127) == 1.0
    assert -1.0 < mod_wheel_pan(32) < 0.0
    assert 0.0 < mod_wheel_pan(96) < 1.0
    # Monotonic across the whole strip, out-of-range values clamped.
    assert mod_wheel_pan(63) < mod_wheel_pan(64) < mod_wheel_pan(65)
    assert mod_wheel_pan(-5) == -1.0
    assert mod_wheel_pan(200) == 1.0


# --- message handling --------------------------------------------------------

def test_pitchwheel_message_sets_bend_zoom():
    state = feed(make_state(), mido.Message('pitchwheel', pitch=8191))
    assert state['bend_zoom'] == pytest.approx(MAX_PITCH_BEND_ZOOM)
    state = feed(state, mido.Message('pitchwheel', pitch=0))
    assert state['bend_zoom'] == 1.0


def test_mod_wheel_message_sets_pan_other_ccs_ignored():
    state = feed(make_state(), mido.Message('control_change', control=1, value=127))
    assert state['pan'] == 1.0
    state = feed(state, mido.Message('control_change', control=7, value=64))
    assert state['pan'] == 1.0  # CC7 (volume) must not touch pan
    state = feed(state, mido.Message('control_change', control=1, value=0))
    assert state['pan'] == -1.0
    state = feed(state, mido.Message('control_change', control=1, value=64))
    assert state['pan'] == 0.0


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


# --- auto-recenter -----------------------------------------------------------

def test_auto_recenter_enabled_with_one_second_idle_window():
    # Task 256: Devin bumps the mod strip accidentally and the frame stays
    # off-center, so the recenter is ON with a 1s idle window. (It was
    # feel-test disabled in task 203; this pins the reversal.)
    assert PAN_AUTO_RECENTER is True
    assert PAN_RECENTER_DELAY == 1.0


def test_recenter_drift_is_multi_frame_monotonic_at_60fps():
    # The glide home must span several frames — quick, but never a one-frame
    # snap. Walk the ease at a real 60fps cadence and require every rendered
    # frame to move strictly toward 0 without ever reaching it in one step.
    state = make_state(pan=1.0, pan_cc_time=0.0)
    frame = 1.0 / 60.0
    t = PAN_RECENTER_DELAY + 0.001
    update_pan_recenter(state, t)  # ease arms on this frame, pan still held
    samples = []
    while state['pan'] != 0.0:
        t += frame
        update_pan_recenter(state, t)
        samples.append(state['pan'])
    # Multiple intermediate frames strictly decreasing — no snap.
    intermediates = [p for p in samples if 0.0 < p < 1.0]
    assert len(intermediates) >= 5
    assert all(a > b for a, b in zip(intermediates, intermediates[1:]))
    assert samples[0] < 1.0  # first drifting frame has left the start...
    assert samples[0] > 0.5  # ...but nowhere near a jump home
    assert samples[-1] == 0.0


def test_recenter_waits_out_the_silence_delay_then_eases():
    state = make_state(pan=1.0, pan_cc_time=100.0)
    # Within the silence window: hold position, no ease.
    update_pan_recenter(state, 100.0 + PAN_RECENTER_DELAY * 0.5)
    assert state['pan'] == 1.0
    assert state.get('pan_ease') is None
    # Past the window: ease starts from the held pan.
    t0 = 100.0 + PAN_RECENTER_DELAY + 0.1
    update_pan_recenter(state, t0)
    assert state['pan_ease'] is not None
    assert state['pan'] == 1.0
    # Gradual: strictly between endpoints mid-ease, still decreasing later.
    update_pan_recenter(state, t0 + PAN_RECENTER_SECONDS * 0.5)
    mid = state['pan']
    assert 0.0 < mid < 1.0
    update_pan_recenter(state, t0 + PAN_RECENTER_SECONDS * 0.8)
    assert 0.0 < state['pan'] < mid
    # Done: snapped exactly home, ease cleared.
    update_pan_recenter(state, t0 + PAN_RECENTER_SECONDS + 0.01)
    assert state['pan'] == 0.0
    assert state['pan_ease'] is None


def test_recenter_works_from_the_left_too():
    state = make_state(pan=-1.0, pan_cc_time=0.0)
    update_pan_recenter(state, PAN_RECENTER_DELAY + 1.0)
    update_pan_recenter(state, PAN_RECENTER_DELAY + 1.0 + PAN_RECENTER_SECONDS * 0.5)
    assert -1.0 < state['pan'] < 0.0
    update_pan_recenter(state, PAN_RECENTER_DELAY + 1.0 + PAN_RECENTER_SECONDS + 0.01)
    assert state['pan'] == 0.0


def test_centered_pan_never_starts_an_ease():
    state = make_state(pan=0.0, pan_cc_time=None)
    update_pan_recenter(state, 1000.0)
    assert state['pan'] == 0.0
    assert state.get('pan_ease') is None


def test_new_cc_cancels_recenter_ease_and_restarts_the_clock():
    state = make_state(pan=1.0, pan_cc_time=0.0)
    update_pan_recenter(state, PAN_RECENTER_DELAY + 1.0)
    update_pan_recenter(state, PAN_RECENTER_DELAY + 1.0 + PAN_RECENTER_SECONDS * 0.5)
    assert state['pan_ease'] is not None
    # A live CC1 mid-glide takes over immediately...
    state = feed(state, mido.Message('control_change', control=1, value=0))
    assert state['pan'] == -1.0
    assert state['pan_ease'] is None
    # ...and resets the silence clock, so the very next frame holds position.
    update_pan_recenter(state, time.monotonic())
    assert state['pan'] == -1.0
    assert state['pan_ease'] is None


# --- rendering ---------------------------------------------------------------

RED = (255, 0, 0)
BLUE = (0, 0, 255)


def half_red_half_blue():
    surface = pygame.Surface((100, 100))
    surface.fill(RED, (0, 0, 50, 100))
    surface.fill(BLUE, (50, 0, 50, 100))
    return surface


@pytest.mark.parametrize('display_mode', ['fill', 'fit'])
def test_pan_slides_frame_at_zoom_one(display_mode):
    # At zoom 1.0 the frame itself slides — MAX_PAN_FRACTION (40%) of the
    # viewport at full deflection — revealing black at the vacated edge.
    surface = half_red_half_blue()
    target = (100, 100)
    center = zoom_surface_to_screen(surface, target, 1.0, display_mode, 0.0)
    right = zoom_surface_to_screen(surface, target, 1.0, display_mode, 1.0)
    left = zoom_surface_to_screen(surface, target, 1.0, display_mode, -1.0)
    assert center.get_size() == right.get_size() == left.get_size() == target
    assert center.get_at((10, 50))[:3] == RED
    assert center.get_at((90, 50))[:3] == BLUE
    # Frame slid right 40px: black gap, then red starting at x=40.
    assert right.get_at((20, 50))[:3] == (0, 0, 0)
    assert right.get_at((60, 50))[:3] == RED
    assert right.get_at((96, 50))[:3] == BLUE
    # Frame slid left 40px: content starts at src x=40, black after x=60.
    assert left.get_at((5, 50))[:3] == RED
    assert left.get_at((30, 50))[:3] == BLUE
    assert left.get_at((80, 50))[:3] == (0, 0, 0)


def test_pan_clamps_beyond_full_deflection():
    surface = half_red_half_blue()
    target = (100, 100)
    full = zoom_surface_to_screen(surface, target, 1.0, 'fill', 1.0)
    over = zoom_surface_to_screen(surface, target, 1.0, 'fill', 5.0)
    assert (pygame.surfarray.array3d(full)
            == pygame.surfarray.array3d(over)).all()
    full = zoom_surface_to_screen(surface, target, 1.0, 'fill', -1.0)
    over = zoom_surface_to_screen(surface, target, 1.0, 'fill', -5.0)
    assert (pygame.surfarray.array3d(full)
            == pygame.surfarray.array3d(over)).all()


@pytest.mark.parametrize('display_mode', ['fill', 'fit'])
def test_pan_composes_with_zoom(display_mode):
    # At zoom 2.0 the slide is still 40% of the VIEWPORT, so the source
    # window (half the frame wide) shifts by 20 source px. Sliding the frame
    # right reveals content to its left (red side) and vice versa.
    surface = half_red_half_blue()
    target = (100, 100)
    center = zoom_surface_to_screen(surface, target, 2.0, display_mode, 0.0)
    right = zoom_surface_to_screen(surface, target, 2.0, display_mode, 1.0)
    left = zoom_surface_to_screen(surface, target, 2.0, display_mode, -1.0)
    assert center.get_at((10, 50))[:3] == RED
    assert center.get_at((90, 50))[:3] == BLUE
    # window src 5..55: red until out x=90
    assert right.get_at((10, 50))[:3] == RED
    assert right.get_at((80, 50))[:3] == RED
    assert right.get_at((96, 50))[:3] == BLUE
    # window src 45..95: red only until out x=10
    assert left.get_at((4, 50))[:3] == RED
    assert left.get_at((50, 50))[:3] == BLUE
    assert left.get_at((95, 50))[:3] == BLUE


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
