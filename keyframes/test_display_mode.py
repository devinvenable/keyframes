"""Headless regression tests for display resize and fullscreen transitions."""
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
