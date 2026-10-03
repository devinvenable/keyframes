"""Headless coverage for animated media INSIDE scenes (task 222).

Scenes used to freeze videos/GIFs to one still; now every scene layer is a
pollable frame source riding the existing VideoPlayer pipeline. Covered
here: media advances between render ticks (and holds between due frames),
static images keep their zero-rebuild cached fast path, all sweep bars show
one synchronized frame from one decode per tick, the rings background
animates, a scene adopts the live normal-view player as its background
(playback position continuity — no restart), and decoders are released on
every non-adoption path.

Run with SDL's dummy video driver:
    SDL_VIDEODRIVER=dummy python3 -m pytest test_scene_animation.py
"""
import os
import queue
import shutil
import subprocess
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import mido
import pygame
import pytest

import main
from main import (
    AnimatedSceneSource,
    ConcentricRingsScene,
    FourBarSweepScene,
    SceneMediaSource,
    TimedConcentricRingsScene,
    VideoPlayer,
    make_step_clock,
    scene_media_source,
    update_scene_on_trigger,
)

SIZE = (40, 40)
# See test_scenes.py: ring 0 (foreground) and ring 1 (background) pixels at
# the default ring geometry on a 40x40 target, sampled at t == activation.
FG_PIXEL = (19, 19)
BG_PIXEL = (19, 25)


@pytest.fixture(scope='module', autouse=True)
def _pygame_init():
    pygame.init()
    pygame.display.set_mode(SIZE)
    yield
    pygame.quit()


@pytest.fixture(scope='module')
def gif_path(tmp_path_factory):
    """A small animated GIF whose frames differ, generated with ffmpeg."""
    if shutil.which('ffmpeg') is None:
        pytest.skip('ffmpeg not available to generate a test GIF')
    path = str(tmp_path_factory.mktemp('gif') / 'anim.gif')
    subprocess.run(
        ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi',
         '-i', 'testsrc=duration=1:size=64x48:rate=10', path],
        check=True)
    return path


def gif_media(gif_path):
    return {'type': 'video', 'path': gif_path, 'name': 'anim.gif',
            'loop': True}


def make_image(color=(255, 0, 0), size=SIZE):
    surface = pygame.Surface(size).convert_alpha()
    surface.fill(color + (255,))
    return surface


def frame_of(color, size=SIZE):
    surface = pygame.Surface(size)
    surface.fill(color)
    return surface


class SteppingSource(SceneMediaSource):
    """Fake animated layer: each current_frame() call steps to the next
    prepared frame (then holds the last), and counts its calls — so a test
    can assert exactly how many decodes one render tick costs."""

    animated = True

    def __init__(self, frames):
        self.frames = list(frames)
        self.calls = 0
        self.released = False
        super().__init__(None)

    def current_frame(self):
        self.calls += 1
        if self.frames:
            self._frame = self.frames.pop(0)
        return self._frame

    def release(self):
        self.released = True


class StubPlayer:
    """Minimal VideoPlayer stand-in yielding a scripted frame sequence
    (None = no new frame ready)."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.last_surface = None
        self.released = False

    def get_frame(self):
        return self.frames.pop(0) if self.frames else None

    def release(self):
        self.released = True


def render_bytes(scene, now, size=SIZE):
    screen = pygame.Surface(size)
    scene.render(screen, size, now)
    return pygame.image.tobytes(screen, 'RGB')


# --- media advances between render ticks -------------------------------------

def test_animated_media_advances_between_render_ticks(gif_path):
    """Two render ticks straddling a media frame boundary show different
    pixels; a tick before the boundary holds the previous frame."""
    # 10 fps GIF (0.1s frame interval), 0.05s step clock: construction costs
    # two polls (prime + base-class init), then render polls alternate
    # decode / hold / decode.
    source = scene_media_source(gif_media(gif_path), SIZE,
                                clock=make_step_clock(0.05))
    scene = FourBarSweepScene(source, 10.0)
    first = scene.image
    advanced = render_bytes(scene, 10.0)
    assert scene.image is not first  # tick past a frame boundary: new frame
    second = scene.image
    held = render_bytes(scene, 10.05)
    assert scene.image is second  # tick inside the frame interval: held
    assert held == advanced  # identical pixels while held
    assert render_bytes(scene, 10.10) != held  # next boundary: new pixels
    assert scene.image is not second
    scene.release()


def test_static_image_scene_pixels_and_cache_identity_are_stable():
    """The all-images path must keep the exact cached fast path: identical
    pixels across ticks AND the same cached bar surface object."""
    scene = FourBarSweepScene(make_image((255, 0, 0)), 10.0)
    first = render_bytes(scene, 10.0)
    bar = scene.bar_surface((10, 40), 0)
    assert render_bytes(scene, 10.4) == first
    assert scene.bar_surface((10, 40), 0) is bar  # cache never invalidated


# --- sweep bars: one decode per tick, all bars synchronized -------------------

def test_sweep_bars_share_one_frame_from_one_poll_per_tick():
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
              (0, 255, 255), (255, 0, 255)]
    source = SteppingSource([frame_of(c) for c in colors])
    scene = FourBarSweepScene(source, 10.0)
    assert source.calls == 1  # construction primed exactly one frame
    for _ in range(3):
        # Place bars 2-4; one shared timestamp == render time keeps every
        # fade at strength 0 so the bar pixels are the raw frame.
        scene.advance(None, 13.0)

    screen = pygame.Surface(SIZE)
    scene.render(screen, SIZE, 13.0)
    assert source.calls == 2  # ONE decode for the whole 4-bar tick
    # Every bar shows the SAME frame — sampled below the fade overlays at
    # strength 0 (render time == last advance time).
    bar_pixels = {screen.get_at((x, 20))[:3] for x in (1, 11, 21, 31)}
    assert len(bar_pixels) == 1
    # Next tick: the next frame, again decoded once, again on every bar.
    scene.render(screen, SIZE, 13.0)
    assert source.calls == 3
    assert {screen.get_at((x, 20))[:3] for x in (1, 11, 21, 31)} != bar_pixels


# --- rings: background animates too, motion independent of media rate --------

def test_rings_background_animates():
    bg = SteppingSource([frame_of((0, 0, 255)), frame_of((0, 255, 0))])
    scene = ConcentricRingsScene(make_image((255, 0, 0)), 10.0, background=bg)
    screen = pygame.Surface(SIZE)
    scene.render(screen, SIZE, 10.0)
    assert screen.get_at(BG_PIXEL)[:3] == (0, 255, 0)  # bg frame advanced
    assert screen.get_at(FG_PIXEL)[:3] == (255, 0, 0)  # static fg untouched
    scene.release()
    assert bg.released


def test_rings_keep_expanding_while_media_frame_holds():
    """Ring motion is wall-clock driven: a starved decoder (frames held)
    must not stall the expansion."""
    player = StubPlayer([frame_of((0, 0, 255))])  # one frame, then None forever
    scene = ConcentricRingsScene(make_image((255, 0, 0)), 10.0,
                                 background=AnimatedSceneSource(player))
    screen = pygame.Surface(SIZE)
    scene.render(screen, SIZE, 10.0)
    assert screen.get_at(BG_PIXEL)[:3] == (0, 0, 255)
    # 0.2s later the boundary moved past BG_PIXEL (see test_scenes.py) even
    # though the background never produced another frame — held, not black.
    scene.render(screen, SIZE, 10.2)
    assert screen.get_at(BG_PIXEL)[:3] == (255, 0, 0)
    assert screen.get_at(FG_PIXEL)[:3] == (0, 0, 255)


def test_animated_source_holds_previous_frame_when_none_ready():
    blue = frame_of((0, 0, 255))
    source = AnimatedSceneSource(StubPlayer([blue]))
    assert source.current_frame() is blue
    assert source.current_frame() is blue  # player returned None: held


# --- playback position continuity ---------------------------------------------

def scene_state():
    return {'surface': None, 'surface_media': None, 'video_player': None,
            'note_active': None, 'note_on_time': None, 'hold_until': None,
            'zoom_scale': 1.0, 'inverted': False, 'last_note': None,
            'active_scene': None}


def trigger(q, state, note_to_media, now, note, config):
    with patch('time.monotonic', return_value=now):
        q.put(mido.Message('note_on', note=note, velocity=100))
        return main.process_midi_messages(q, 36, 99, note_to_media, SIZE,
                                          state, scenes_config=config)


def test_scene_adopts_live_player_as_background_without_restart(gif_path):
    """A rings scene activated while a video plays keeps THAT player as its
    background — same object, position intact, never re-opened."""
    q = queue.Queue()
    state = scene_state()
    media = {60: gif_media(gif_path),
             62: {'type': 'image', 'surface': make_image(), 'name': 'a.png'}}
    quiet = {'enabled': True, 'probability': 0.05}

    with patch('main.random.random', return_value=0.9):
        state = trigger(q, state, media, 10.0, 60, quiet)
    player = state['video_player']
    assert player is not None

    with patch('main.random.random', return_value=0.0), \
            patch('main.random.choice', return_value='concentric-rings'):
        state = trigger(q, state, media, 11.0, 62, quiet)
    scene = state['active_scene']
    assert isinstance(scene, ConcentricRingsScene)
    assert isinstance(scene.background_source, AnimatedSceneSource)
    assert scene.background_source.player is player  # adopted, not restarted
    assert player.cap is not None  # still open and playing
    assert state['video_player'] is None  # detached from the normal state
    scene.release()
    assert player.cap is None


def test_unadopted_player_is_released_when_no_scene_activates(gif_path):
    q = queue.Queue()
    state = scene_state()
    media = {60: gif_media(gif_path),
             62: {'type': 'image', 'surface': make_image(), 'name': 'a.png'}}
    quiet = {'enabled': True, 'probability': 0.05}

    with patch('main.random.random', return_value=0.9):
        state = trigger(q, state, media, 10.0, 60, quiet)
        player = state['video_player']
        state = trigger(q, state, media, 11.0, 62, quiet)
    assert state['active_scene'] is None
    assert player.cap is None  # wrapped for capture, then released


def test_sweep_releases_an_animated_background_immediately():
    stub = StubPlayer([frame_of((0, 0, 255))])
    scene = FourBarSweepScene(make_image(), 10.0,
                              background=AnimatedSceneSource(stub))
    assert stub.released
    assert scene.background_source is None


def test_ended_scene_releases_its_decoders(gif_path):
    q = queue.Queue()
    state = scene_state()
    media = {60: gif_media(gif_path),
             62: {'type': 'image', 'surface': make_image(), 'name': 'a.png'}}
    config = {'enabled': True, 'probability': 1.0}

    with patch('main.random.random', return_value=0.0), \
            patch('main.random.choice', return_value='four-bar-sweep'):
        state = trigger(q, state, media, 10.0, 60, config)
    scene = state['active_scene']
    fg_player = scene.image_source.player
    assert fg_player.cap is not None
    for now in (11.0, 12.0, 13.0, 14.0):  # bars 2-4, then the final fade
        state = trigger(q, state, media, now, 62, config)
    with patch('main.random.random', return_value=0.9):
        # Past the fade: this trigger ends the scene; the quiet probability
        # keeps the follow-up roll from starting a successor.
        state = trigger(q, state, media, 20.0, 62,
                        {'enabled': True, 'probability': 0.05})
    assert state['active_scene'] is None
    assert fg_player.cap is None  # ended scene's decoder freed


# --- timed rings rotation / native decode -------------------------------------

def test_timed_rings_rotation_installs_a_live_source(gif_path):
    scene = TimedConcentricRingsScene(make_image((255, 0, 0)), 10.0)
    old_image = scene.image
    scene.advance(gif_media(gif_path), 10.1)
    assert isinstance(scene.image_source, AnimatedSceneSource)
    assert scene.background is old_image  # old foreground rotated back
    scene.release()


def test_video_player_native_size_when_target_is_none(gif_path):
    player = VideoPlayer(gif_path, None, loop=True,
                         clock=make_step_clock(1.0))
    try:
        assert player.get_frame().get_size() == (64, 48)
    finally:
        player.release()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
