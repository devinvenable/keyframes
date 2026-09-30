"""Headless regression tests for display resize, fullscreen transitions,
and the fill/fit media scaling modes."""
import ctypes
import os
import shutil
import subprocess

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame
import pytest

import main


@pytest.fixture(scope='module', autouse=True)
def _pygame_init():
    pygame.init()
    pygame.display.set_mode((800, 600))
    yield
    pygame.quit()


def _keydown(key, mod=0):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod)


def test_fullscreen_toggle_keys_do_not_collide_with_piano_or_help():
    f11 = _keydown(pygame.K_F11)
    alt_enter = _keydown(pygame.K_RETURN, pygame.KMOD_ALT)
    plain_enter = _keydown(pygame.K_RETURN)

    assert main.is_fullscreen_toggle_key(f11)
    assert main.is_fullscreen_toggle_key(alt_enter)
    assert not main.is_fullscreen_toggle_key(plain_enter)
    for event in (f11, alt_enter):
        assert event.key not in main.KEY_TO_NOTE
        assert not main.is_help_reshow_key(event)


def test_resize_updates_active_video_target_size():
    player = type('Player', (), {'target_size': (1, 1)})()
    state = {'video_player': player}

    target_size = main.update_display_target_size(state, 1536, 864)

    assert target_size == (1536, 864)
    assert player.target_size == (1536, 864)


def test_resize_updates_target_without_active_video():
    assert main.update_display_target_size({'video_player': None}, 900, 700) == (900, 700)


def test_set_display_mode_changes_dimensions_and_retargets_video(monkeypatch):
    calls = []
    player = type('Player', (), {'target_size': (1, 1)})()
    state = {'video_player': player}

    def set_mode(size, flags=0, **kwargs):
        calls.append((size, flags, kwargs))
        return pygame.Surface(size)

    monkeypatch.setattr(main.pygame.display, 'set_mode', set_mode)
    monkeypatch.setattr(main.pygame.mouse, 'set_visible', lambda visible: None)
    monkeypatch.setattr(main, 'choose_landscape_display', lambda: (0, 1920, 1080))

    screen, width, height, target_size = main.set_display_mode(True, (1280, 720), state)

    assert screen.get_size() == (1920, 1080)
    assert (width, height, target_size, player.target_size) == (
        1920, 1080, (1920, 1080), (1920, 1080))
    assert calls[-1] == ((1920, 1080),
                         pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF,
                         {'display': 0})

    screen, width, height, target_size = main.set_display_mode(False, (1280, 720), state)

    assert screen.get_size() == (1280, 720)
    assert (width, height, target_size, player.target_size) == (
        1280, 720, (1280, 720), (1280, 720))
    assert calls[-1] == ((1280, 720), pygame.RESIZABLE, {})


def test_set_display_mode_pins_fullscreen_above_and_unpins_windowed(monkeypatch):
    pins = []
    monkeypatch.setattr(main.pygame.display, 'set_mode',
                        lambda size, flags=0, **kwargs: pygame.Surface(size))
    monkeypatch.setattr(main.pygame.mouse, 'set_visible', lambda visible: None)
    monkeypatch.setattr(main, 'choose_landscape_display', lambda: (0, 1920, 1080))
    monkeypatch.setattr(main, 'set_window_always_on_top',
                        lambda on_top: pins.append(on_top) or True)

    main.set_display_mode(True, (1280, 720), {'video_player': None})
    main.set_display_mode(False, (1280, 720), {'video_player': None})

    assert pins == [True, False]


def test_build_wm_state_event_encodes_ewmh_above_message():
    event = main.build_wm_state_event(0x1234, 55, 66, main._NET_WM_STATE_ADD)

    assert (event.type, event.window, event.message_type, event.format) == (
        main._X_CLIENT_MESSAGE, 0x1234, 55, 32)
    assert list(event.data) == [main._NET_WM_STATE_ADD, 66, 0, 0, 0]
    # libX11 copies the whole XEvent union (long pad[24]) — the struct must be
    # at least that big or XSendEvent reads past the allocation.
    assert ctypes.sizeof(event) >= 24 * ctypes.sizeof(ctypes.c_long)


def test_set_window_always_on_top_headless_is_false_not_crash(monkeypatch):
    monkeypatch.setattr(main.pygame.display, 'get_wm_info', lambda: {})
    assert main.set_window_always_on_top(True) is False


def test_set_window_always_on_top_survives_wm_info_failure(monkeypatch):
    def boom():
        raise pygame.error('video system not initialized')
    monkeypatch.setattr(main.pygame.display, 'get_wm_info', boom)
    assert main.set_window_always_on_top(True) is False


# --- fill / fit media scaling ------------------------------------------------

def _white_square(size=100):
    surface = pygame.Surface((size, size))
    surface.fill((255, 255, 255))
    return surface


def _is_white(color):
    return all(v > 200 for v in color[:3])


def _is_black(color):
    return all(v < 50 for v in color[:3])


def test_fit_to_screen_pillarboxes_square_media_in_wide_target():
    result = main.fit_to_screen(_white_square(), (160, 90))

    assert result.get_size() == (160, 90)
    # Full height visible, media centered: 90x90 white with black side bars
    assert _is_white(result.get_at((80, 45)))
    assert _is_white(result.get_at((80, 0)))
    assert _is_white(result.get_at((80, 89)))
    assert _is_black(result.get_at((0, 45)))
    assert _is_black(result.get_at((159, 45)))


def test_fit_to_screen_letterboxes_wide_media_in_tall_target():
    wide = pygame.Surface((200, 100))
    wide.fill((255, 255, 255))

    result = main.fit_to_screen(wide, (100, 100))

    assert result.get_size() == (100, 100)
    # Full width visible: 100x50 white band with black bars above and below
    assert _is_white(result.get_at((50, 50)))
    assert _is_white(result.get_at((0, 50)))
    assert _is_black(result.get_at((50, 0)))
    assert _is_black(result.get_at((50, 99)))


def test_zoom_surface_to_screen_default_fill_has_no_bars():
    result = main.zoom_surface_to_screen(_white_square(), (160, 90), 1.0)

    assert result.get_size() == (160, 90)
    assert _is_white(result.get_at((0, 45)))
    assert _is_white(result.get_at((159, 45)))


def test_zoom_surface_to_screen_fit_mode_keeps_bars():
    result = main.zoom_surface_to_screen(
        _white_square(), (160, 90), 1.0, display_mode='fit')

    assert result.get_size() == (160, 90)
    assert _is_white(result.get_at((80, 45)))
    assert _is_black(result.get_at((0, 45)))
    assert _is_black(result.get_at((159, 45)))


def test_zoom_ring_in_fit_mode_overflows_into_bars():
    # 2x zoom on a 90px-wide fitted square spans 180px > 160px target width,
    # so the media covers the pillarbox bars while staying target-sized.
    result = main.zoom_surface_to_screen(
        _white_square(), (160, 90), 2.0, display_mode='fit')

    assert result.get_size() == (160, 90)
    assert _is_white(result.get_at((0, 45)))
    assert _is_white(result.get_at((159, 45)))


@pytest.fixture(scope='module')
def white_video_path(tmp_path_factory):
    """A short 64x64 all-white video, generated with ffmpeg."""
    if shutil.which('ffmpeg') is None:
        pytest.skip('ffmpeg not available to generate a test video')
    path = str(tmp_path_factory.mktemp('video') / 'white.mp4')
    subprocess.run(
        ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi',
         '-i', 'color=c=white:duration=0.3:size=64x64:rate=10', path],
        check=True)
    return path


def test_video_player_fit_mode_pillarboxes_square_frames(white_video_path):
    player = main.VideoPlayer(white_video_path, (128, 72), display_mode='fit')
    try:
        frame = player.get_frame()
    finally:
        player.release()

    assert frame.get_size() == (128, 72)
    # 64x64 frame fit into 128x72 → 72x72 media centered with black side bars
    assert _is_white(frame.get_at((64, 36)))
    assert _is_white(frame.get_at((64, 0)))
    assert _is_black(frame.get_at((0, 36)))
    assert _is_black(frame.get_at((127, 36)))


def test_video_player_default_fill_crops_square_frames(white_video_path):
    player = main.VideoPlayer(white_video_path, (128, 72))
    try:
        frame = player.get_frame()
    finally:
        player.release()

    assert frame.get_size() == (128, 72)
    assert _is_white(frame.get_at((0, 36)))
    assert _is_white(frame.get_at((127, 36)))


def test_video_player_started_by_note_on_inherits_display_mode(white_video_path):
    state = {'surface': None, 'video_player': None, 'note_active': None,
             'note_on_time': None, 'hold_until': None, 'zoom_scale': 1.0,
             'inverted': False, 'surface_media': None, 'last_note': None}
    note_to_media = {60: {'type': 'video', 'path': white_video_path}}
    messages = [type('Msg', (), {'type': 'note_on', 'note': 60,
                                 'velocity': 100, 'channel': 0})()]
    source = type('Source', (), {'iter_pending': lambda self: iter(messages)})()

    state = main.process_midi_messages(
        source, 0, 127, note_to_media, (128, 72), state,
        display_mode='fit')
    try:
        assert state['video_player'] is not None
        assert state['video_player'].display_mode == 'fit'
    finally:
        if state['video_player']:
            state['video_player'].release()


def test_set_window_always_on_top_routes_to_windows_topmost(monkeypatch):
    calls = []
    monkeypatch.setattr(main.pygame.display, 'get_wm_info', lambda: {'window': 42})
    monkeypatch.setattr(main.sys, 'platform', 'win32')
    monkeypatch.setattr(main, '_windows_set_always_on_top',
                        lambda hwnd, on_top: calls.append((hwnd, on_top)) or True)

    assert main.set_window_always_on_top(False) is True
    assert calls == [(42, False)]
