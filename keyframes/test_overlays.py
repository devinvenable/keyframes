"""Headless coverage for periodic alpha overlays — transparent title
animations composited on top of the normal view or an active scene.

Covers the wall-clock scheduler (fires within configured bounds, never when
disabled), the N-loop playback lifecycle, round-robin/shuffle variant
rotation, on-top compositing over both base layers (pixel-level alpha
checks), centered fit-inside placement math, per-bank config override and
fallback, the hard decode-memory bound, and frame-hold under a starved
decoder pool."""
import json
import os
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame
import pytest

import main
from main import (
    DEFAULT_OVERLAYS_CONFIG,
    OVERLAY_DECODE_WORKERS,
    OVERLAY_MAX_CACHE_BYTES,
    OVERLAY_RING_MAX,
    OVERLAY_RING_MIN,
    OverlayDecoder,
    OverlayPlayback,
    OverlayScheduler,
    compute_overlay_placement,
    discover_overlays,
    draw_performance_frame,
    load_overlays_config,
    overlay_ring_frames,
)

GREEN = (0, 255, 0, 255)
BLUE = (0, 0, 255, 255)
RED = (255, 0, 0, 255)


@pytest.fixture(autouse=True)
def display():
    pygame.init()
    screen = pygame.display.set_mode((8, 8))
    yield screen
    pygame.quit()


def save_rgba(path, left, right, size=(4, 4)):
    """A tiny RGBA PNG: left half ``left``, right half ``right`` (RGBA)."""
    surface = pygame.Surface(size, pygame.SRCALPHA)
    half = size[0] // 2
    surface.fill(left, pygame.Rect(0, 0, half, size[1]))
    surface.fill(right, pygame.Rect(half, 0, size[0] - half, size[1]))
    pygame.image.save(surface, str(path))


def make_variant(root, name, frame_colors):
    """A variant dir of solid 4x4 frames; returns its discover_overlays dict."""
    folder = root / name
    folder.mkdir(parents=True)
    for i, color in enumerate(frame_colors):
        save_rgba(folder / f'frame_{i:04d}.png', color, color)
    return {'name': name,
            'frames': sorted(str(p) for p in folder.iterdir())}


def make_state(surface=None):
    return {'surface': surface, 'surface_media': None, 'video_player': None,
            'inverted': False, 'zoom_scale': 1.0, 'bend_zoom': 1.0,
            'pan': 0.0, 'active_scene': None, 'overlay': None}


def base_still(color=RED, size=(8, 8)):
    surface = pygame.Surface(size).convert_alpha()
    surface.fill(color)
    return surface


def drain(decoder, timeout=5.0):
    """Collect every emitted frame from a live decoder (real threads)."""
    frames = []
    deadline = time.time() + timeout
    while not decoder.finished():
        assert time.time() < deadline, 'decoder stalled'
        data = decoder.get_nowait()
        if data is None:
            time.sleep(0.002)
        else:
            frames.append(data)
    return frames


def render_until(condition, pb, screen, target_size, now, timeout=5.0):
    """Repeat render at a frozen ``now`` until the decoder catches up."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pb.render(screen, target_size, now)
        if condition():
            return
        time.sleep(0.002)
    raise AssertionError('condition never reached')


class FakeRng:
    """Deterministic stand-in for random.Random."""

    def __init__(self, r=0.0, randint_high=True, reverse_shuffle=False):
        self.r = r
        self.randint_high = randint_high
        self.reverse_shuffle = reverse_shuffle

    def random(self):
        return self.r

    def randint(self, low, high):
        return high if self.randint_high else low

    def shuffle(self, seq):
        if self.reverse_shuffle:
            seq.reverse()


class FakePlayback:
    """Records scheduler interactions; completion is set by the test."""

    created = []

    def __init__(self, name, frames, loops, target_size, now, fps=None,
                 clock=None):
        self.name, self.loops, self.started_at = name, loops, now
        self.finished = False
        self.released = False
        self.rendered = []
        FakePlayback.created.append(self)

    def done(self, now=None):
        return self.finished

    def render(self, screen, target_size, now):
        self.rendered.append(now)

    def release(self):
        self.released = True


@pytest.fixture(autouse=True)
def reset_fakes():
    FakePlayback.created = []


def make_scheduler(config=None, variants=('a', 'b', 'c'), now=0.0, rng=None):
    cfg = dict(DEFAULT_OVERLAYS_CONFIG)
    cfg.update({'enabled': True, 'interval_min_s': 10.0,
                'interval_max_s': 20.0})
    cfg.update(config or {})
    vlist = [{'name': n, 'frames': [f'{n}.png']} for n in variants]
    return OverlayScheduler(cfg, vlist, now, rng=rng or FakeRng(),
                            playback_factory=FakePlayback)


# ---------------------------------------------------------------- config ---

def test_config_defaults_on_missing_or_malformed(tmp_path):
    assert load_overlays_config(str(tmp_path / 'nope.json')) == \
        DEFAULT_OVERLAYS_CONFIG
    bad = tmp_path / 'overlays.json'
    bad.write_text('{not json')
    assert load_overlays_config(str(bad)) == DEFAULT_OVERLAYS_CONFIG
    bad.write_text('[1, 2]')
    assert load_overlays_config(str(bad)) == DEFAULT_OVERLAYS_CONFIG
    assert DEFAULT_OVERLAYS_CONFIG['enabled'] is False  # ships disabled


def test_config_values_validation_and_clamps(tmp_path):
    path = tmp_path / 'overlays.json'
    path.write_text(json.dumps({
        'enabled': True, 'dir': 'titles', 'fps': 24,
        'interval_min_s': 5, 'interval_max_s': 9.5,
        'loops_min': 1, 'loops_max': 4, 'shuffle': True}))
    config = load_overlays_config(str(path))
    assert config == {'enabled': True, 'dir': 'titles', 'fps': 24.0,
                      'interval_min_s': 5.0, 'interval_max_s': 9.5,
                      'loops_min': 1, 'loops_max': 4, 'shuffle': True}
    # Wrong types / out-of-range fall back per key; inverted ranges clamp.
    path.write_text(json.dumps({
        'enabled': 'yes', 'dir': '', 'fps': -30,
        'interval_min_s': 50, 'interval_max_s': 20,
        'loops_min': 5, 'loops_max': 2, 'shuffle': 1}))
    config = load_overlays_config(str(path))
    assert config['enabled'] is False and config['shuffle'] is False
    assert config['dir'] == 'overlays' and config['fps'] == 30.0
    assert (config['interval_min_s'], config['interval_max_s']) == (50.0, 50.0)
    assert (config['loops_min'], config['loops_max']) == (5, 5)


def test_per_bank_override_and_fallback(tmp_path, monkeypatch):
    images = tmp_path / 'images'
    bank = tmp_path / 'banks' / 'other'
    images.mkdir()
    bank.mkdir(parents=True)
    for folder in (images, bank):
        save_rgba(folder / 'shared.png', RED, RED)
    (tmp_path / 'mapping.json').write_text('{"48": "shared.png"}\n')
    (bank / 'mapping.json').write_text('{"48": "shared.png"}\n')
    (tmp_path / 'overlays.json').write_text(
        '{"enabled": true, "interval_min_s": 30, "interval_max_s": 30}')
    monkeypatch.setattr(main, 'IMAGES_DIR', str(images))
    monkeypatch.setattr(main, 'MAPPING_PATH', str(tmp_path / 'mapping.json'))
    monkeypatch.setattr(main, 'SCENES_CONFIG_PATH',
                        str(tmp_path / 'scenes.json'))
    monkeypatch.setattr(main, 'OVERLAYS_CONFIG_PATH',
                        str(tmp_path / 'overlays.json'))
    monkeypatch.setattr(main, 'BANKS_DIR', tmp_path / 'banks')
    banks = main.MediaBanks(36, 99)

    # No bank file -> global settings apply to the bank.
    banks.load('other')
    assert banks.overlays_config['interval_min_s'] == 30.0
    assert main.OVERLAYS_CONFIG_PATH == str(tmp_path / 'overlays.json')

    # A bank-local overlays.json overrides; switching back restores global.
    (bank / 'overlays.json').write_text(
        '{"enabled": false, "interval_min_s": 7, "interval_max_s": 8}')
    banks.load('other')
    assert banks.overlays_config['enabled'] is False
    assert banks.overlays_config['interval_min_s'] == 7.0
    assert main.OVERLAYS_CONFIG_PATH == str(bank / 'overlays.json')
    banks.load('default')
    assert banks.overlays_config['enabled'] is True
    assert banks.overlays_config['interval_min_s'] == 30.0


# ------------------------------------------------- discovery & placement ---

def test_discover_overlays_sorted_and_tolerant(tmp_path):
    assert discover_overlays(str(tmp_path / 'missing')) == []
    make_variant(tmp_path, 'bbb', [GREEN])
    make_variant(tmp_path, 'aaa', [GREEN, BLUE])
    (tmp_path / 'empty').mkdir()          # no frames: skipped
    (tmp_path / 'loose.png').touch()      # not a variant dir: skipped
    (tmp_path / 'aaa' / 'notes.txt').touch()  # non-png ignored
    variants = discover_overlays(str(tmp_path))
    assert [v['name'] for v in variants] == ['aaa', 'bbb']
    assert len(variants[0]['frames']) == 2
    assert variants[0]['frames'] == sorted(variants[0]['frames'])


def test_centered_fit_placement_math():
    # Square overlay on a 16:9 screen: native size, centered horizontally.
    assert compute_overlay_placement((1080, 1080), (1920, 1080)) == \
        ((1080, 1080), (420, 0))
    # Wide overlay on its native screen: full frame.
    assert compute_overlay_placement((1920, 1080), (1920, 1080)) == \
        ((1920, 1080), (0, 0))
    # Downscale into a small window, aspect kept, centered.
    assert compute_overlay_placement((1920, 1080), (1280, 720)) == \
        ((1280, 720), (0, 0))
    assert compute_overlay_placement((1080, 1080), (1280, 720)) == \
        ((720, 720), (280, 0))
    # Upscale to a larger screen (fit-inside allows growth), never cropped.
    assert compute_overlay_placement((1920, 1080), (3840, 2160)) == \
        ((3840, 2160), (0, 0))
    assert compute_overlay_placement((0, 0), (1920, 1080)) == ((0, 0), (0, 0))


# -------------------------------------------------- decoder memory bound ---

def test_ring_sizing_respects_hard_memory_cap():
    for width, height in ((1920, 1080), (1080, 1080), (3840, 2160),
                          (1280, 720), (4, 4)):
        frame_bytes = width * height * 4
        ring = overlay_ring_frames(frame_bytes)
        assert OVERLAY_RING_MIN <= ring <= OVERLAY_RING_MAX
        resident = (ring + OVERLAY_DECODE_WORKERS) * frame_bytes
        assert resident <= OVERLAY_MAX_CACHE_BYTES, (width, height)


def test_decoder_never_claims_past_ring(tmp_path):
    variant = make_variant(tmp_path, 'v', [GREEN] * 12)
    decoder = OverlayDecoder(variant['frames'], 1, (4, 4), ring_frames=3)
    deadline = time.time() + 2.0
    while len(decoder._ready) < 3 and time.time() < deadline:
        time.sleep(0.002)
    time.sleep(0.05)  # workers must now be parked on the backpressure gate
    with decoder._cond:
        assert decoder._next_claim - decoder._next_emit <= 3
        assert len(decoder._ready) <= 3
    decoder.release()


def test_decoder_in_order_loops_and_skips_unreadable(tmp_path):
    variant = make_variant(tmp_path, 'v', [GREEN, BLUE])
    decoder = OverlayDecoder(variant['frames'], 2, (2, 2))
    frames = drain(decoder)
    green, blue = bytes(GREEN) * 4, bytes(BLUE) * 4
    assert frames == [green, blue, green, blue]
    # An unreadable frame is skipped, the rest still deliver in order.
    decoder = OverlayDecoder([variant['frames'][0], str(tmp_path / 'no.png'),
                              variant['frames'][1]], 1, (2, 2))
    assert drain(decoder) == [green, blue]


# ------------------------------------------------------ playback pacing ---

def test_playback_n_loop_lifecycle_and_pacing(tmp_path, display):
    variant = make_variant(tmp_path, 'v', [GREEN, BLUE])
    pb = OverlayPlayback('v', variant['frames'], 2, (8, 8), now=100.0,
                         fps=10.0)
    assert not pb.done()
    shown = []
    now = 100.0
    for _ in range(4):  # 2 frames x 2 loops, one due every 0.1s
        render_until(lambda: pb.surface not in shown and pb.surface,
                     pb, display, (8, 8), now)
        shown.append(pb.surface)
        now += 0.1
    assert [s.get_at((2, 2)) for s in shown] == [GREEN, BLUE, GREEN, BLUE]
    # Final frame holds for its full interval, then the overlay disappears.
    assert not pb.done(now)
    render_until(lambda: pb.done(now), pb, display, (8, 8), now)
    display.fill((0, 0, 0))
    pb.render(display, (8, 8), now + 1)
    assert display.get_at((2, 2)) == (0, 0, 0, 255)
    pb.release()


def test_playback_between_frames_holds_without_advancing(tmp_path, display):
    variant = make_variant(tmp_path, 'v', [GREEN, BLUE])
    pb = OverlayPlayback('v', variant['frames'], 1, (8, 8), now=0.0, fps=10.0)
    render_until(lambda: pb.surface, pb, display, (8, 8), 0.0)
    first = pb.surface
    for now in (0.02, 0.05, 0.09):  # not due yet: same surface object
        pb.render(display, (8, 8), now)
        assert pb.surface is first
    pb.release()


class StarvedDecoder:
    """A decode pool that has fallen behind: nothing ready, not finished."""

    def __init__(self, *args, **kwargs):
        self.data = []
        self.ended = False
        self.released = False

    def get_nowait(self):
        return self.data.pop(0) if self.data else None

    def finished(self):
        return self.ended and not self.data

    def release(self):
        self.released = True


def test_playback_holds_frame_under_starved_decoder(tmp_path, display):
    variant = make_variant(tmp_path, 'v', [GREEN])
    stub = StarvedDecoder()
    pb = OverlayPlayback('v', variant['frames'], 1, (8, 8), now=0.0, fps=10.0,
                         decoder_factory=lambda *a, **k: stub)
    display.fill((40, 40, 40))
    pb.render(display, (8, 8), 0.0)  # nothing decoded yet: base untouched
    assert display.get_at((2, 2)) == (40, 40, 40, 255)
    assert not pb.done()
    stub.data.append(bytes(GREEN) * 64)  # one 8x8 frame arrives
    pb.render(display, (8, 8), 0.0)
    held = pb.surface
    assert held is not None
    # Decoder starves for many frame intervals: the shown frame holds, the
    # playback neither crashes, advances, nor ends.
    for now in (0.1, 0.5, 2.0, 9.0):
        display.fill((40, 40, 40))
        pb.render(display, (8, 8), now)
        assert pb.surface is held
        assert display.get_at((2, 2)) == GREEN
        assert not pb.done(now)
    # The pool finally reports the end: overlay finishes and disappears.
    stub.ended = True
    pb.render(display, (8, 8), 10.0)
    assert pb.done(10.0)
    pb.release()


# ----------------------------------------------------------- scheduler ---

def test_scheduler_never_fires_when_disabled(display):
    sched = make_scheduler({'enabled': False}, now=0.0)
    for now in (0.0, 100.0, 1e6):
        sched.render(display, (8, 8), now)
    assert FakePlayback.created == [] and sched.active is None


def test_scheduler_fires_within_configured_bounds(display):
    # rng.random()=0 -> earliest bound (10s); never a moment before.
    sched = make_scheduler(now=1000.0, rng=FakeRng(r=0.0))
    sched.render(display, (8, 8), 1009.99)
    assert sched.active is None
    sched.render(display, (8, 8), 1010.0)
    assert sched.active is not None and sched.active.started_at == 1010.0
    # rng.random()=1 -> latest bound (20s after the first showing ends).
    sched.rng = FakeRng(r=1.0)
    sched.active.finished = True
    sched.render(display, (8, 8), 1016.0)  # ends here; next due 1036.0
    assert sched.active is None
    sched.render(display, (8, 8), 1035.9)
    assert sched.active is None
    sched.render(display, (8, 8), 1036.0)
    assert sched.active is not None


def test_scheduler_loop_count_from_config_and_lifecycle(display):
    sched = make_scheduler({'interval_min_s': 1.0, 'interval_max_s': 1.0,
                            'loops_min': 2, 'loops_max': 3},
                           rng=FakeRng(randint_high=True), now=0.0)
    sched.render(display, (8, 8), 1.0)
    playback = sched.active
    assert playback.loops == 3
    # While active it renders every tick; when done it is released, cleared,
    # and the next interval is scheduled from the end time.
    sched.render(display, (8, 8), 2.0)
    assert playback.rendered == [1.0, 2.0]
    playback.finished = True
    sched.render(display, (8, 8), 5.0)
    assert playback.released and sched.active is None
    assert sched._next_at == 6.0


def finish_and_advance(sched, display, now):
    """Complete the active showing and run to the next activation."""
    sched.active.finished = True
    sched.render(display, (8, 8), now)          # releases, schedules +10s
    sched.render(display, (8, 8), now + 10.0)   # activates next variant
    return sched.active


def test_scheduler_round_robin_and_shuffle(display):
    sched = make_scheduler({'interval_min_s': 10.0, 'interval_max_s': 10.0},
                           now=0.0)
    sched.render(display, (8, 8), 10.0)
    names = [sched.active.name]
    for step in range(1, 7):
        names.append(finish_and_advance(sched, display, 10.0 + 20.0 * step)
                     .name)
    assert names == ['a', 'b', 'c', 'a', 'b', 'c', 'a']  # wraps in order

    shuffled = make_scheduler({'interval_min_s': 10.0,
                               'interval_max_s': 10.0, 'shuffle': True},
                              rng=FakeRng(reverse_shuffle=True), now=0.0)
    shuffled.render(display, (8, 8), 10.0)
    order = [shuffled.active.name]
    for step in range(1, 3):
        order.append(finish_and_advance(shuffled, display, 10.0 + 20.0 * step)
                     .name)
    assert order == ['c', 'b', 'a']  # the injected shuffle, not name order


def test_scheduler_reconfigure_bank_switch_rules(display):
    sched = make_scheduler(now=0.0, rng=FakeRng(r=0.0))
    sched.render(display, (8, 8), 10.0)
    active = sched.active
    # Disabling via a bank switch never cancels the active showing...
    sched.reconfigure(dict(sched.config, enabled=False), sched.variants, 11.0)
    sched.render(display, (8, 8), 12.0)
    assert sched.active is active
    # ...but once it ends, nothing new is scheduled.
    active.finished = True
    sched.render(display, (8, 8), 13.0)
    for now in (14.0, 1000.0):
        sched.render(display, (8, 8), now)
    assert sched.active is None and len(FakePlayback.created) == 1
    # Re-enabling schedules an activation again.
    sched.reconfigure(dict(sched.config, enabled=True), sched.variants, 20.0)
    sched.render(display, (8, 8), 30.0)
    assert sched.active is not None


# ------------------------------------------------- compositing (on top) ---

def overlay_state_with_scheduler(tmp_path, display):
    """A real scheduler + playback over a red base still: min=max=5s."""
    root = tmp_path / 'ov'
    (root / 'title').mkdir(parents=True)
    save_rgba(root / 'title' / 'frame_0001.png', GREEN, (0, 0, 0, 0))
    cfg = dict(DEFAULT_OVERLAYS_CONFIG)
    cfg.update({'enabled': True, 'interval_min_s': 5.0, 'interval_max_s': 5.0,
                'loops_min': 1, 'loops_max': 1})
    sched = OverlayScheduler(cfg, discover_overlays(str(root)), 0.0,
                             rng=FakeRng())
    state = make_state(base_still())
    state['overlay'] = sched
    return state, sched


def wait_overlay_pixels(state, display, now, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        draw_performance_frame(display, state, (8, 8), now)
        if display.get_at((1, 4)) == GREEN:
            return
        time.sleep(0.002)
    raise AssertionError('overlay never composited')


def test_overlay_renders_on_top_of_normal_view(tmp_path, display):
    state, sched = overlay_state_with_scheduler(tmp_path, display)
    draw_performance_frame(display, state, (8, 8), 1.0)
    assert sched.active is None          # before the interval: base only
    assert display.get_at((1, 4)) == RED
    wait_overlay_pixels(state, display, 5.0)  # fires exactly at min=max=5s
    # Opaque overlay half covers the base; transparent half shows it.
    assert display.get_at((1, 4)) == GREEN
    assert display.get_at((6, 4)) == RED
    sched.release()


def test_overlay_renders_on_top_of_active_scene(tmp_path, display):
    state, sched = overlay_state_with_scheduler(tmp_path, display)

    class FakeScene:
        def render(self, screen, target_size, now):
            screen.fill(BLUE)

    state['active_scene'] = FakeScene()
    wait_overlay_pixels(state, display, 5.0)
    assert display.get_at((1, 4)) == GREEN   # overlay above the scene
    assert display.get_at((6, 4)) == BLUE    # scene intact underneath
    sched.release()


def test_overlay_disappears_after_loops_and_reschedules(tmp_path, display):
    state, sched = overlay_state_with_scheduler(tmp_path, display)
    wait_overlay_pixels(state, display, 5.0)
    # One 1-frame loop at 30fps: done one interval after the frame showed.
    deadline = time.time() + 5.0
    now = 5.0
    while sched.active is not None:
        assert time.time() < deadline, 'overlay never ended'
        now += 1 / 30.0
        draw_performance_frame(display, state, (8, 8), now)
    assert display.get_at((1, 4)) == RED  # gone — base view restored
    assert sched._next_at == pytest.approx(now + 5.0)  # next interval armed
    sched.release()


# ------------------------------------------- decoder worker crash (task 266) --
def test_decode_exception_cannot_wedge_the_showing(tmp_path, monkeypatch, capsys):
    """A frame whose DECODE RAISES (not merely imread->None: a truncated or
    malformed PNG can throw from resize/cvtColor) must be skipped like an
    unreadable one. Before task 266 the exception silently killed the worker
    with its frame index claimed: get_nowait() waited on that index forever,
    finished() never flipped, ring backpressure wedged the other workers, and
    the overlay held its last frame on top of the show indefinitely — read as
    a Keyframes lockup on stage (overlays were enabled during the 2026-10-10
    live freezes)."""
    variant = make_variant(tmp_path, 'wedge', [GREEN, BLUE, RED])
    poison = variant['frames'][1]
    real_imread = main.cv2.imread

    def exploding_imread(path, flags=None):
        if path == poison:
            raise RuntimeError('corrupt frame')
        return real_imread(path, flags)

    monkeypatch.setattr(main.cv2, 'imread', exploding_imread)
    decoder = OverlayDecoder(variant['frames'], 1, (2, 2))
    frames = drain(decoder)  # asserts 'decoder stalled' on regression
    decoder.release()
    assert len(frames) == 2  # poisoned frame skipped, the rest emitted
    assert 'overlay frame decode failed' in capsys.readouterr().out
