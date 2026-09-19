"""Headless tests for Linux drop-path normalization and drop-target plumbing.

Covers the headless-testable halves of the T29 fix (grid drag-drop did nothing
on Linux/X11): decoding file:// URI payloads, the pointer-position fallback,
and the whole-window red flash for a drop that misses every cell.  The real
XDND coordinate behaviour needs a display and is verified manually.

Run with SDL's dummy video driver so no window is needed:
    SDL_VIDEODRIVER=dummy python3 -m pytest test_drop_target.py
"""
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


# --- normalize_drop_paths ---------------------------------------------------

def test_plain_path_passes_through():
    assert main.normalize_drop_paths('/home/devin/pic.png') == ['/home/devin/pic.png']

def test_file_uri_is_decoded():
    assert main.normalize_drop_paths('file:///home/devin/pic.png') == ['/home/devin/pic.png']

def test_file_uri_percent_encoding_and_crlf():
    raw = 'file:///home/devin/My%20Pics/a%20b.jpg\r\n'
    assert main.normalize_drop_paths(raw) == ['/home/devin/My Pics/a b.jpg']

def test_file_uri_localhost_host_allowed():
    assert main.normalize_drop_paths('file://localhost/tmp/x.png') == ['/tmp/x.png']

def test_file_uri_remote_host_rejected():
    assert main.normalize_drop_paths('file://nas.local/tmp/x.png') == []

def test_multiline_uri_list():
    raw = 'file:///a.png\nfile:///b.mp4\n'
    assert main.normalize_drop_paths(raw) == ['/a.png', '/b.mp4']

def test_non_file_url_rejected():
    assert main.normalize_drop_paths('http://example.com/a.png') == []

def test_whitespace_only_payload():
    assert main.normalize_drop_paths('   \n') == []

def test_normalized_uri_is_supported_media():
    # The original bug path: a URI payload made supported_media_file() see no
    # extension. After normalization the extension check works again.
    [path] = main.normalize_drop_paths('file:///home/devin/clip.MP4')
    assert main.supported_media_file(path)


# --- drop_pointer_pos fallback ----------------------------------------------

def test_drop_pointer_pos_falls_back_to_pygame(monkeypatch):
    # Off-X11 (dummy driver) the X query must fail soft and yield get_pos().
    monkeypatch.setattr(main, 'x11_query_pointer', lambda: None)
    assert main.drop_pointer_pos() == pygame.mouse.get_pos()

def test_drop_pointer_pos_prefers_x11_answer(monkeypatch):
    monkeypatch.setattr(main, 'x11_query_pointer', lambda: (123, 456))
    assert main.drop_pointer_pos() == (123, 456)

def test_x11_query_pointer_headless_is_none_not_crash():
    # Dummy video driver has no X window; the query must return None, never raise.
    assert main.x11_query_pointer() is None


# --- missed-drop visibility -------------------------------------------------

def test_drop_flash_note_none_draws_window_border():
    screen = pygame.display.get_surface()
    screen.fill((0, 0, 0))
    flash = {'note': None, 'ok': False, 'until': 10.0}
    main.draw_drop_flash(screen, [], 0, flash, now=0.0)
    assert screen.get_at((0, 0))[:3] == (230, 60, 60)

def test_drop_flash_note_none_expires():
    screen = pygame.display.get_surface()
    screen.fill((0, 0, 0))
    flash = {'note': None, 'ok': False, 'until': 1.0}
    main.draw_drop_flash(screen, [], 0, flash, now=2.0)
    assert screen.get_at((0, 0))[:3] == (0, 0, 0)
