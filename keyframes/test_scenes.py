"""Headless coverage for Scenes — reusable templated playback sequences.

Covers the random activation gate, trigger-driven bar advancement, the
fade-to-white timing, completion/return-to-normal, and the center-crop math
of the four-bar sweep prototype."""
import os
import queue
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

import mido
import pygame

from main import (
    DEFAULT_SCENE_PROBABILITY,
    FourBarSweepScene,
    SCENE_REGISTRY,
    draw_performance_frame,
    load_scenes_config,
    process_midi_messages,
    scene_bar_rect,
    update_scene_on_trigger,
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
        'active_scene': None,
    }


def make_image(color=(255, 0, 0), size=(8, 8)):
    surface = pygame.Surface(size).convert_alpha()
    surface.fill(color + (255,))
    return surface


def trigger(queue_, state, note_to_media, now, note, scenes_config=None):
    with patch('time.monotonic', return_value=now):
        queue_.put(mido.Message('note_on', note=note, velocity=100))
        return process_midi_messages(queue_, 36, 99, note_to_media, (8, 8),
                                     state, scenes_config=scenes_config)


def setup_module(module):
    pygame.init()
    pygame.display.set_mode((8, 8))


def teardown_module(module):
    pygame.quit()


# --- activation gate ---------------------------------------------------------

def test_activation_requires_roll_under_probability():
    config = {'enabled': True, 'probability': 0.05}
    media = {'type': 'image', 'surface': make_image(), 'name': 'a.png'}

    state = make_state()
    update_scene_on_trigger(state, media, 10.0, config, rng=lambda: 0.9)
    assert state['active_scene'] is None

    update_scene_on_trigger(state, media, 10.0, config, rng=lambda: 0.01)
    assert isinstance(state['active_scene'], FourBarSweepScene)


def test_no_activation_when_disabled_or_unconfigured():
    media = {'type': 'image', 'surface': make_image(), 'name': 'a.png'}
    always = lambda: 0.0

    state = make_state()
    update_scene_on_trigger(state, media, 10.0,
                            {'enabled': False, 'probability': 1.0}, rng=always)
    assert state['active_scene'] is None

    update_scene_on_trigger(state, media, 10.0, None, rng=always)
    assert state['active_scene'] is None


def test_activation_rolls_through_process_midi_messages():
    q = queue.Queue()
    state = make_state()
    media = {60: {'type': 'image', 'surface': make_image(), 'name': 'a.png'}}
    config = {'enabled': True, 'probability': 0.05}

    with patch('main.random.random', return_value=0.9):
        state = trigger(q, state, media, 10.0, 60, config)
    assert state['active_scene'] is None

    with patch('main.random.random', return_value=0.01):
        state = trigger(q, state, media, 11.0, 60, config)
    assert isinstance(state['active_scene'], FourBarSweepScene)


def test_scenes_config_defaults_and_validation(tmp_path):
    missing = load_scenes_config(str(tmp_path / 'nope.json'))
    assert missing == {'enabled': True,
                       'probability': DEFAULT_SCENE_PROBABILITY}

    good = tmp_path / 'scenes.json'
    good.write_text('{"enabled": false, "probability": 0.25}')
    assert load_scenes_config(str(good)) == {'enabled': False,
                                             'probability': 0.25}

    bad = tmp_path / 'bad.json'
    bad.write_text('{"enabled": "yes", "probability": 7}')
    assert load_scenes_config(str(bad)) == {'enabled': True,
                                            'probability': DEFAULT_SCENE_PROBABILITY}

    broken = tmp_path / 'broken.json'
    broken.write_text('{not json')
    assert load_scenes_config(str(broken)) == {'enabled': True,
                                               'probability': DEFAULT_SCENE_PROBABILITY}


# --- bar advancement ---------------------------------------------------------

def test_triggers_advance_bars_and_start_predecessor_fades():
    scene = FourBarSweepScene(make_image(), 10.0)
    assert scene.bars_placed == 1
    assert scene.fade_starts == {}

    scene.advance(None, 11.0)
    assert scene.bars_placed == 2
    assert scene.fade_starts == {0: 11.0}

    scene.advance(None, 12.0)
    scene.advance(None, 13.0)
    assert scene.bars_placed == 4
    assert scene.fade_starts == {0: 11.0, 1: 12.0, 2: 13.0}
    assert not scene.finishing

    # Trigger after bar 4: the final fade starts, nothing else moves.
    scene.advance(None, 14.0)
    assert scene.finishing
    assert scene.bars_placed == 4
    assert scene.fade_starts[3] == 14.0

    # Extra triggers during the final fade change nothing.
    scene.advance(None, 14.5)
    assert scene.fade_starts[3] == 14.0


def test_same_image_steps_across_bars_while_other_notes_trigger():
    """Devin's decision: the ACTIVATING image steps bar to bar; later triggers
    (even of different notes) only advance the beat, never swap the image."""
    q = queue.Queue()
    state = make_state()
    red, blue = make_image((255, 0, 0)), make_image((0, 0, 255))
    media = {60: {'type': 'image', 'surface': red, 'name': 'r.png'},
             62: {'type': 'image', 'surface': blue, 'name': 'b.png'}}
    config = {'enabled': True, 'probability': 1.0}

    with patch('main.random.random', return_value=0.0):
        state = trigger(q, state, media, 10.0, 60, config)
    scene = state['active_scene']
    assert scene.image is red

    state = trigger(q, state, media, 11.0, 62, config)
    assert state['active_scene'] is scene  # still the same scene
    assert scene.bars_placed == 2
    assert scene.image is red  # image did not swap to blue
    # Normal state keeps updating underneath for the return-to-normal cut.
    assert state['surface'] is blue


# --- fade-to-white timing ----------------------------------------------------

def test_fade_strength_timing():
    scene = FourBarSweepScene(make_image(), 10.0)
    scene.advance(None, 11.0)  # bar 1's fade starts at 11.0
    assert scene.fade_strength(0, 11.0) == 0.0
    assert abs(scene.fade_strength(0, 11.5) - 0.5) < 1e-9
    assert scene.fade_strength(0, 12.0) == 1.0
    assert scene.fade_strength(0, 99.0) == 1.0  # clamped, keeps white
    assert scene.fade_strength(1, 11.5) == 0.0  # unfaded successor


def test_render_fades_previous_bar_to_white():
    screen = pygame.Surface((8, 8))
    scene = FourBarSweepScene(make_image((255, 0, 0), (8, 8)), 10.0)
    scene.advance(None, 11.0)  # bar 2 placed, bar 1 fading from 11.0

    # Mid-fade: bar 1 is red blended halfway to white, bar 2 still pure red.
    scene.render(screen, (8, 8), 11.5)
    r, g, b = screen.get_at((0, 0))[:3]
    assert r == 255 and 100 < g < 155 and 100 < b < 155
    assert screen.get_at((2, 0))[:3] == (255, 0, 0)
    # Unplaced bar 3 is still background black.
    assert screen.get_at((4, 0))[:3] == (0, 0, 0)

    # Fade complete: bar 1 is solid white.
    scene.render(screen, (8, 8), 12.5)
    assert screen.get_at((0, 0))[:3] == (255, 255, 255)


# --- completion / return to normal -------------------------------------------

def test_scene_completes_after_final_fade_and_normal_view_resumes():
    screen = pygame.Surface((8, 8))
    q = queue.Queue()
    state = make_state()
    red, blue = make_image((255, 0, 0)), make_image((0, 0, 255))
    media = {60: {'type': 'image', 'surface': red, 'name': 'r.png'},
             62: {'type': 'image', 'surface': blue, 'name': 'b.png'}}
    config = {'enabled': True, 'probability': 1.0}

    with patch('main.random.random', return_value=0.0):
        state = trigger(q, state, media, 10.0, 60, config)
    scene = state['active_scene']

    # Four more triggers: bars 2-4 placed, then the final fade starts at 14.0.
    # The last trigger is a non-repeat (62 after 60), so the resumed view
    # must show plain blue — no same-note invert flash in the way.
    for now, note in ((11.0, 62), (12.0, 60), (13.0, 60), (14.0, 62)):
        state = trigger(q, state, media, now, note, config)
    assert scene.finishing
    assert not scene.done(14.5)
    assert scene.done(15.0)

    # While not done, the scene owns the frame (all four bars visible).
    draw_performance_frame(screen, state, (8, 8), 14.5)
    assert state['active_scene'] is scene
    assert screen.get_at((7, 7))[:3] != (0, 0, 255)

    # Once the final fade elapses the hook is dropped and the latest
    # triggered media (blue, note 62) draws full-screen again.
    draw_performance_frame(screen, state, (8, 8), 15.1)
    assert state['active_scene'] is None
    assert screen.get_at((4, 4))[:3] == (0, 0, 255)


def test_no_new_scene_can_stack_on_an_active_one():
    media = {'type': 'image', 'surface': make_image(), 'name': 'a.png'}
    config = {'enabled': True, 'probability': 1.0}
    state = make_state()
    update_scene_on_trigger(state, media, 10.0, config, rng=lambda: 0.0)
    scene = state['active_scene']
    update_scene_on_trigger(state, media, 11.0, config, rng=lambda: 0.0)
    assert state['active_scene'] is scene
    assert scene.bars_placed == 2


# --- center-crop math --------------------------------------------------------

def test_bar_rects_tile_the_screen_with_remainder_on_last_bar():
    rects = [scene_bar_rect(i, (1026, 768)) for i in range(4)]
    assert rects[0] == (0, 0, 256, 768)
    assert rects[1] == (256, 0, 256, 768)
    assert rects[2] == (512, 0, 256, 768)
    assert rects[3] == (768, 0, 258, 768)  # absorbs the remainder
    assert sum(r[2] for r in rects) == 1026


def test_bar_surface_is_center_crop_at_bar_aspect():
    # 40x10 source: outer quarters red, middle half white. A 10x10 bar must
    # center-crop (columns 15..25, all white) — a squeeze would show red.
    src = pygame.Surface((40, 10)).convert_alpha()
    src.fill((255, 0, 0, 255))
    src.fill((255, 255, 255, 255), (10, 0, 20, 10))
    scene = FourBarSweepScene(src, 0.0)

    bar = scene.bar_surface((10, 10))
    assert bar.get_size() == (10, 10)
    for x in (0, 5, 9):
        assert bar.get_at((x, 5))[:3] == (255, 255, 255)

    # Cached: the same size returns the same surface object.
    assert scene.bar_surface((10, 10)) is bar


def test_four_bar_sweep_is_registered():
    assert SCENE_REGISTRY['four-bar-sweep'] is FourBarSweepScene
