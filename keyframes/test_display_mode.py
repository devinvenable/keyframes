"""Headless regression tests for display resize and fullscreen transitions."""
import ctypes
import os

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


def test_set_window_always_on_top_routes_to_windows_topmost(monkeypatch):
    calls = []
    monkeypatch.setattr(main.pygame.display, 'get_wm_info', lambda: {'window': 42})
    monkeypatch.setattr(main.sys, 'platform', 'win32')
    monkeypatch.setattr(main, '_windows_set_always_on_top',
                        lambda hwnd, on_top: calls.append((hwnd, on_top)) or True)

    assert main.set_window_always_on_top(False) is True
    assert calls == [(42, False)]
