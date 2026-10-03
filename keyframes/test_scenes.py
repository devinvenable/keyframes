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
    ConcentricRingsScene,
    FourBarSweepBlackScene,
    FourBarSweepScene,
    FourBarSweepTintedScene,
    SCENE_REGISTRY,
    TimedConcentricRingsScene,
    draw_performance_frame,
    load_scenes_config,
    process_midi_messages,
    scene_bar_rect,
    update_scene_on_trigger,
)


def pick_scene(name):
    """Pin the random registry pick so a test exercises one known scene."""
    return patch('main.random.choice', return_value=name)


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

    with pick_scene('four-bar-sweep'):
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

    with patch('main.random.random', return_value=0.01), \
            pick_scene('four-bar-sweep'):
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

    with patch('main.random.random', return_value=0.0), \
            pick_scene('four-bar-sweep'):
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

    with patch('main.random.random', return_value=0.0), \
            pick_scene('four-bar-sweep'):
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

    # Past the final fade, the render path does NOT drop the scene — it holds
    # the fully-faded final frame (solid white) instead of letting the at-rest
    # full-screen view (blue, a different key than the scene's red) flash
    # through before the next trigger arrives.
    draw_performance_frame(screen, state, (8, 8), 15.1)
    assert state['active_scene'] is scene
    assert screen.get_at((4, 4))[:3] == (255, 255, 255)

    # The NEXT trigger clears the finished scene (its roll stays above the
    # probability here), and only then does the normal view resume — showing
    # that very trigger's media (red, note 60: a non-repeat after 62, so no
    # same-note invert in the way).
    with patch('main.random.random', return_value=0.9):
        state = trigger(q, state, media, 16.0, 60,
                        {'enabled': True, 'probability': 0.05})
    assert state['active_scene'] is None
    draw_performance_frame(screen, state, (8, 8), 16.1)
    assert screen.get_at((4, 4))[:3] == (255, 0, 0)


def test_no_at_rest_frame_renders_across_a_scene_handoff():
    """Render-level guard for Devin's reported flash: with probability 1.0,
    NO frame between a scene's activation and the next scene's first frame
    may be the plain full-screen view — including the dead zone between the
    final fade completing on wall-clock and the next trigger arriving."""
    screen = pygame.Surface((8, 8))
    q = queue.Queue()
    state = make_state()
    red, blue = make_image((255, 0, 0)), make_image((0, 0, 255))
    media = {60: {'type': 'image', 'surface': red, 'name': 'r.png'},
             62: {'type': 'image', 'surface': blue, 'name': 'b.png'}}
    config = {'enabled': True, 'probability': 1.0}

    def plain_frame(now):
        """What the at-rest (sceneless) view would show right now."""
        ref = pygame.Surface((8, 8))
        sceneless = dict(state, active_scene=None)
        draw_performance_frame(ref, sceneless, (8, 8), now)
        return ref

    def assert_scene_owns_frame(now):
        draw_performance_frame(screen, state, (8, 8), now)
        assert state['active_scene'] is not None
        ref = plain_frame(now)
        # Byte-identical frames mean the composed frame IS the plain
        # full-screen view — the reported flash.
        assert (pygame.image.tobytes(screen, 'RGB')
                != pygame.image.tobytes(ref, 'RGB'))

    with patch('main.random.random', return_value=0.0), \
            pick_scene('four-bar-sweep'):
        state = trigger(q, state, media, 10.0, 60, config)
        first = state['active_scene']

        # Bars 2-4, final fade starts at 14.0; sample frames between beats,
        # through the fade, and PAST its completion (15.0) into the dead zone
        # where no trigger has arrived yet — the frames that used to flash.
        for now, note in ((11.0, 62), (12.0, 60), (13.0, 60), (14.0, 62)):
            state = trigger(q, state, media, now, note, config)
            assert_scene_owns_frame(now + 0.5)
        for now in (14.9, 15.1, 16.0, 25.0):
            assert_scene_owns_frame(now)

        # The next trigger hands off to the successor scene in the same call.
        state = trigger(q, state, media, 26.0, 60, config)
    assert state['active_scene'] is not None
    assert state['active_scene'] is not first
    assert_scene_owns_frame(26.0)


def test_no_new_scene_can_stack_on_an_active_one():
    media = {'type': 'image', 'surface': make_image(), 'name': 'a.png'}
    config = {'enabled': True, 'probability': 1.0}
    state = make_state()
    with pick_scene('four-bar-sweep'):
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


def test_all_scenes_are_registered():
    assert SCENE_REGISTRY['four-bar-sweep'] is FourBarSweepScene
    assert SCENE_REGISTRY['four-bar-sweep-black'] is FourBarSweepBlackScene
    assert SCENE_REGISTRY['four-bar-sweep-tinted'] is FourBarSweepTintedScene
    assert SCENE_REGISTRY['concentric-rings'] is ConcentricRingsScene
    assert SCENE_REGISTRY['concentric-rings-timed'] is TimedConcentricRingsScene
    assert len(SCENE_REGISTRY) == 5


# --- fade-to-black variant ----------------------------------------------------

def test_black_variant_fades_previous_bar_to_black():
    screen = pygame.Surface((8, 8))
    scene = FourBarSweepBlackScene(make_image((255, 0, 0), (8, 8)), 10.0)
    scene.advance(None, 11.0)  # bar 2 placed, bar 1 fading from 11.0

    # Mid-fade: bar 1 is red blended halfway to black, bar 2 still pure red.
    scene.render(screen, (8, 8), 11.5)
    r, g, b = screen.get_at((0, 0))[:3]
    assert 100 < r < 155 and g == 0 and b == 0
    assert screen.get_at((2, 0))[:3] == (255, 0, 0)

    # Fade complete: bar 1 is solid black.
    scene.render(screen, (8, 8), 12.5)
    assert screen.get_at((0, 0))[:3] == (0, 0, 0)


# --- per-bar tints ------------------------------------------------------------

def test_tinted_variant_tints_each_bar_with_bar_four_untinted():
    # White source: multiply shows each bar's tint directly, and the untinted
    # bar 4 stays white. All advances share one timestamp and the render
    # happens at that same instant, so every fade strength is still 0.
    screen = pygame.Surface((8, 8))
    scene = FourBarSweepTintedScene(make_image((255, 255, 255), (8, 8)), 10.0)
    for _ in range(3):
        scene.advance(None, 10.0)
    assert scene.bars_placed == 4
    scene.render(screen, (8, 8), 10.0)

    red = screen.get_at((0, 0))[:3]
    assert red[0] >= 250 and red[1] == 0 and red[2] == 0
    green = screen.get_at((2, 0))[:3]
    assert green[0] == 0 and green[1] >= 250 and green[2] == 0
    blue = screen.get_at((4, 0))[:3]
    assert blue[0] == 0 and blue[1] == 0 and blue[2] >= 250
    # Bar 4 untinted: the natural image, give or take fade-start timing...
    bar4 = screen.get_at((6, 0))[:3]
    assert all(c >= 250 for c in bar4)


def test_tint_applies_to_color_sources_too():
    """Devin's decision: tint ALWAYS applies — no grayscale gating. A yellow
    source through the red tint keeps only its red channel (multiply)."""
    scene = FourBarSweepTintedScene(make_image((255, 255, 0), (8, 8)), 10.0)
    bar = scene.bar_surface((2, 8), 0)  # bar 1 = red tint
    r, g, b = bar.get_at((1, 4))[:3]
    assert r >= 250 and g == 0 and b == 0

    # ...while the untinted bar shows the source unchanged.
    plain = scene.bar_surface((2, 8), 3)
    assert plain.get_at((1, 4))[:3] == (255, 255, 0)


def test_tinted_bar_cache_is_keyed_by_tint():
    scene = FourBarSweepTintedScene(make_image((255, 255, 255), (8, 8)), 10.0)
    assert scene.bar_surface((2, 8), 0) is not scene.bar_surface((2, 8), 1)
    assert scene.bar_surface((2, 8), 0) is scene.bar_surface((2, 8), 0)


def test_base_sweep_keeps_white_fade_and_no_tint():
    # The parameterization must not change the original scene's behavior.
    assert FourBarSweepScene.FADE_COLOR == (255, 255, 255)
    assert FourBarSweepScene.BAR_TINTS is None
    scene = FourBarSweepScene(make_image((255, 255, 0), (8, 8)), 10.0)
    assert scene.bar_surface((2, 8), 0).get_at((1, 4))[:3] == (255, 255, 0)


# --- concentric rings ---------------------------------------------------------
# 40x40 screen, default params: ring thickness = 4px, expansion = 10px/s,
# center at (19.5, 19.5). Pixel (19, 19) sits at dist ~0.7 (ring 0, even);
# pixel (19, 25) at dist ~5.5 (ring 1, odd).

RINGS_SIZE = (40, 40)
FG_PIXEL = (19, 19)
BG_PIXEL = (19, 25)


def make_rings(background='blue'):
    fg = make_image((255, 0, 0), RINGS_SIZE)
    bg = make_image((0, 0, 255), RINGS_SIZE) if background == 'blue' else None
    return ConcentricRingsScene(fg, 10.0, background=bg)


def rendered(scene, now):
    screen = pygame.Surface(RINGS_SIZE)
    scene.render(screen, RINGS_SIZE, now)
    return screen


def test_even_rings_show_foreground_odd_show_background():
    screen = rendered(make_rings(), 10.0)
    assert screen.get_at(FG_PIXEL)[:3] == (255, 0, 0)  # ring 0: foreground
    assert screen.get_at(BG_PIXEL)[:3] == (0, 0, 255)  # ring 1: background


def test_rings_expand_outward_with_wall_clock_time():
    scene = make_rings()
    # At activation the dist-5.5 pixel is in odd ring 1 (background). 0.2s
    # later the offset has grown by 2px, the ring boundary moved outward past
    # it, and the same pixel now shows foreground — without any beat.
    assert rendered(scene, 10.0).get_at(BG_PIXEL)[:3] == (0, 0, 255)
    assert rendered(scene, 10.2).get_at(BG_PIXEL)[:3] == (255, 0, 0)
    # New rings are born at center: once the offset exceeds the center
    # distance, the center pixel flips to the newborn (odd) ring.
    assert rendered(scene, 10.0).get_at(FG_PIXEL)[:3] == (255, 0, 0)
    assert rendered(scene, 10.2).get_at(FG_PIXEL)[:3] == (0, 0, 255)


def test_beat_swaps_foreground_and_background():
    scene = make_rings()
    assert rendered(scene, 10.0).get_at(FG_PIXEL)[:3] == (255, 0, 0)
    scene.advance(None, 10.0)
    screen = rendered(scene, 10.0)
    assert screen.get_at(FG_PIXEL)[:3] == (0, 0, 255)  # same pixel, other image
    assert screen.get_at(BG_PIXEL)[:3] == (255, 0, 0)
    scene.advance(None, 10.0)
    assert rendered(scene, 10.0).get_at(FG_PIXEL)[:3] == (255, 0, 0)


def test_missing_background_falls_back_to_black():
    screen = rendered(make_rings(background=None), 10.0)
    assert screen.get_at(FG_PIXEL)[:3] == (255, 0, 0)
    assert screen.get_at(BG_PIXEL)[:3] == (0, 0, 0)


def test_rings_tuning_defaults_slower_and_longer():
    """Devin's live tuning (task 218): halve the expansion speed and double
    the lifetime so the ring motion reads continuous for longer."""
    assert ConcentricRingsScene.EXPANSION_SPEED_FRACTION == 0.25
    assert ConcentricRingsScene.BEATS_TO_LIVE == 16


def test_rings_scene_ends_on_sixteenth_beat():
    scene = make_rings()
    for i in range(scene.BEATS_TO_LIVE - 1):
        scene.advance(None, 10.0 + i)
        assert not scene.done(10.0 + i)
    scene.advance(None, 26.0)
    assert scene.done(26.0)


def test_new_scene_can_start_on_the_trigger_that_ended_the_old():
    """A trigger that finishes the active scene falls through to the
    activation roll in the same call — no one-frame full-screen flash
    between back-to-back scenes."""
    media = {'type': 'image', 'surface': make_image(), 'name': 'a.png'}
    config = {'enabled': True, 'probability': 1.0}
    state = make_state()
    with pick_scene('concentric-rings'):
        update_scene_on_trigger(state, media, 10.0, config, rng=lambda: 0.0)
        old = state['active_scene']
        assert isinstance(old, ConcentricRingsScene)
        # Beats 1-16; the 16th ends `old` and must activate its successor
        # within the SAME call.
        for i in range(ConcentricRingsScene.BEATS_TO_LIVE):
            update_scene_on_trigger(state, media, 11.0 + i, config,
                                    rng=lambda: 0.0)
    assert old.done(27.0)
    assert state['active_scene'] is not None
    assert state['active_scene'] is not old


def test_back_to_back_rings_continue_the_expansion():
    """Rings following rings on the ending trigger carry the predecessor's
    expansion origin: ring placement never restarts from center, only the
    foreground image swaps (Devin: 'keep the ring motion continuous')."""
    media = {'type': 'image', 'surface': make_image(), 'name': 'a.png'}
    config = {'enabled': True, 'probability': 1.0}
    state = make_state()
    with pick_scene('concentric-rings'):
        update_scene_on_trigger(state, media, 10.0, config, rng=lambda: 0.0)
        old = state['active_scene']
        for i in range(ConcentricRingsScene.BEATS_TO_LIVE):
            update_scene_on_trigger(state, media, 11.0 + i, config,
                                    rng=lambda: 0.0)
    new = state['active_scene']
    assert isinstance(new, ConcentricRingsScene) and new is not old
    # Same expansion origin -> the render offset is continuous across the
    # handoff instead of resetting to zero at the new activation time.
    assert new.activated_at == old.activated_at


def test_rings_after_a_sweep_start_fresh():
    """continue_from only carries state between two rings scenes — rings
    activated on the trigger that ended a SWEEP expand from center."""
    media = {'type': 'image', 'surface': make_image(), 'name': 'a.png'}
    config = {'enabled': True, 'probability': 1.0}
    state = make_state()
    with pick_scene('four-bar-sweep'):
        update_scene_on_trigger(state, media, 10.0, config, rng=lambda: 0.0)
    sweep = state['active_scene']
    for i in range(4):
        update_scene_on_trigger(state, media, 11.0 + i, config,
                                rng=lambda: 0.0)
    assert sweep.finishing
    with pick_scene('concentric-rings'):
        # 20.0 is past the final fade, so this trigger ends the sweep and
        # activates rings in the same call.
        update_scene_on_trigger(state, media, 20.0, config, rng=lambda: 0.0)
    rings = state['active_scene']
    assert isinstance(rings, ConcentricRingsScene)
    assert rings.activated_at == 20.0


def test_activation_captures_previous_image_as_background():
    """The background is what was ON SCREEN before the activating trigger —
    captured before the trigger overwrites state — so the new image tunnels
    in through the old."""
    q = queue.Queue()
    state = make_state()
    red, blue = make_image((255, 0, 0)), make_image((0, 0, 255))
    media = {60: {'type': 'image', 'surface': red, 'name': 'r.png'},
             62: {'type': 'image', 'surface': blue, 'name': 'b.png'}}
    config = {'enabled': True, 'probability': 1.0}

    quiet = {'enabled': True, 'probability': 0.05}
    with patch('main.random.random', return_value=0.9):
        state = trigger(q, state, media, 10.0, 60, quiet)  # red on screen
    assert state['active_scene'] is None

    with patch('main.random.random', return_value=0.0), \
            pick_scene('concentric-rings'):
        state = trigger(q, state, media, 11.0, 62, config)
    scene = state['active_scene']
    assert isinstance(scene, ConcentricRingsScene)
    assert scene.image is blue
    assert scene.background is red


def test_rings_complete_after_sixteen_beats_and_normal_view_resumes():
    screen = pygame.Surface((8, 8))
    q = queue.Queue()
    state = make_state()
    red, blue = make_image((255, 0, 0)), make_image((0, 0, 255))
    media = {60: {'type': 'image', 'surface': red, 'name': 'r.png'},
             62: {'type': 'image', 'surface': blue, 'name': 'b.png'}}
    config = {'enabled': True, 'probability': 1.0}

    with patch('main.random.random', return_value=0.0), \
            pick_scene('concentric-rings'):
        state = trigger(q, state, media, 10.0, 60, config)
    scene = state['active_scene']
    assert isinstance(scene, ConcentricRingsScene)

    # Beats 1-15 (notes alternate, so no same-note invert interferes): the
    # scene stays active and owns the frame.
    for beat in range(1, scene.BEATS_TO_LIVE):
        note = 60 if beat % 2 else 62
        state = trigger(q, state, media, 10.0 + beat, note, config)
    draw_performance_frame(screen, state, (8, 8), 24.5)
    assert state['active_scene'] is scene

    # Beat 16 ends the scene ON the beat — a hard cut back to the normal view
    # showing that very trigger's media (blue, note 62). The roll that the
    # ending trigger falls through to stays above the probability here, so
    # no back-to-back scene starts.
    with patch('main.random.random', return_value=0.9):
        state = trigger(q, state, media, 26.0, 62,
                        {'enabled': True, 'probability': 0.05})
    assert state['active_scene'] is None
    draw_performance_frame(screen, state, (8, 8), 26.1)
    assert screen.get_at((4, 4))[:3] == (0, 0, 255)


# --- timed rings variant ------------------------------------------------------

def image_media(surface, name='m.png'):
    return {'type': 'image', 'surface': surface, 'name': name}


def make_timed_rings(fg=(255, 0, 0), background=(0, 0, 255)):
    bg = make_image(background, RINGS_SIZE) if background else None
    return TimedConcentricRingsScene(make_image(fg, RINGS_SIZE), 10.0,
                                     background=bg)


def test_timed_rings_defaults():
    assert SCENE_REGISTRY['concentric-rings-timed'] is TimedConcentricRingsScene
    assert TimedConcentricRingsScene.DURATION_SECONDS == 6.0


def test_timed_rings_done_is_duration_based_not_beat_based():
    scene = make_timed_rings()
    media = image_media(make_image((0, 255, 0), RINGS_SIZE))
    # 20 triggers inside the first second: still alive.
    for i in range(20):
        scene.advance(media, 10.0 + i * 0.05)
    assert not scene.done(11.0)
    # Zero further triggers: done exactly at activation + 6s.
    assert not scene.done(15.99)
    assert scene.done(16.0)


def test_timed_rings_triggers_do_not_alter_ring_motion():
    """Render bytes at a fixed t are identical with and without interleaved
    advances (modulo image change — same image on every trigger here): no
    parity swap, no offset change."""
    quiet = make_timed_rings(fg=(255, 0, 0), background=(255, 0, 0))
    busy = make_timed_rings(fg=(255, 0, 0), background=(255, 0, 0))
    media = image_media(make_image((255, 0, 0), RINGS_SIZE))
    rendered(busy, 10.5)  # populate the render cache before any rotation
    for i in range(7):
        busy.advance(media, 10.1 + i * 0.3)
    a = pygame.surfarray.array3d(rendered(quiet, 12.3))
    b = pygame.surfarray.array3d(rendered(busy, 12.3))
    assert (a == b).all()


def test_timed_rings_trigger_rotates_images():
    """On each note-on the current foreground becomes the background and the
    trigger's still becomes the foreground — newest image tunnels in."""
    scene = make_timed_rings(fg=(255, 0, 0), background=(0, 0, 255))
    rendered(scene, 10.0)  # cached layers must be rebuilt by the rotation
    scene.advance(image_media(make_image((0, 255, 0), RINGS_SIZE)), 10.1)
    screen = rendered(scene, 10.0)
    assert screen.get_at(FG_PIXEL)[:3] == (0, 255, 0)  # new still: foreground
    assert screen.get_at(BG_PIXEL)[:3] == (255, 0, 0)  # old fg: background
    scene.advance(image_media(make_image((255, 255, 0), RINGS_SIZE)), 10.2)
    screen = rendered(scene, 10.0)
    assert screen.get_at(FG_PIXEL)[:3] == (255, 255, 0)
    assert screen.get_at(BG_PIXEL)[:3] == (0, 255, 0)


def test_timed_rings_handoff_carries_expansion_but_not_lifetime():
    """A timed scene activated on the trigger that ended a rings scene keeps
    the ring motion continuous (carries expansion_origin) but lives its FULL
    6 seconds from its OWN activation, not the predecessor's."""
    media = {'type': 'image', 'surface': make_image(), 'name': 'a.png'}
    config = {'enabled': True, 'probability': 1.0}
    state = make_state()
    with pick_scene('concentric-rings'):
        update_scene_on_trigger(state, media, 10.0, config, rng=lambda: 0.0)
        old = state['active_scene']
        for i in range(ConcentricRingsScene.BEATS_TO_LIVE - 1):
            update_scene_on_trigger(state, media, 11.0 + i, config,
                                    rng=lambda: 0.0)
    with pick_scene('concentric-rings-timed'):
        update_scene_on_trigger(state, media, 26.0, config, rng=lambda: 0.0)
    new = state['active_scene']
    assert isinstance(new, TimedConcentricRingsScene) and new is not old
    assert new.expansion_origin == old.expansion_origin == 10.0
    assert new.activated_at == 26.0
    assert not new.done(31.99)
    assert new.done(32.0)


def test_timed_rings_ends_on_first_trigger_past_duration():
    """The render path holds a done scene's final frame; the next trigger
    past the 6s mark is what actually ends it (and may roll a successor)."""
    media = {'type': 'image', 'surface': make_image(), 'name': 'a.png'}
    config = {'enabled': True, 'probability': 1.0}
    state = make_state()
    with pick_scene('concentric-rings-timed'):
        update_scene_on_trigger(state, media, 10.0, config, rng=lambda: 0.0)
    scene = state['active_scene']
    assert isinstance(scene, TimedConcentricRingsScene)
    update_scene_on_trigger(state, media, 12.0, config, rng=lambda: 1.0)
    assert state['active_scene'] is scene  # mid-flight trigger: still alive
    update_scene_on_trigger(state, media, 17.0, config, rng=lambda: 1.0)
    assert state['active_scene'] is None  # past 6s: this trigger ended it
