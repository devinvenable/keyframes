"""Headless tests for the grid / media-manager view.

Run with SDL's dummy video driver so no window is needed:
    SDL_VIDEODRIVER=dummy python3 -m pytest test_grid_view.py
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


def _img(color=(100, 150, 200), size=(320, 180)):
    surf = pygame.Surface(size)
    surf.fill(color)
    return {'type': 'image', 'surface': surf}


def test_build_grid_cells_dedupes_shared_media():
    # Two media objects, each shared across a contiguous run of notes.
    a, b = _img((10, 20, 30)), _img((40, 50, 60))
    note_to_media = {36: a, 37: a, 38: a, 39: b, 40: b}
    cells = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))

    assert len(cells) == 2, "shared media object should collapse to one cell"
    assert cells[0]['notes'] == [36, 37, 38]
    assert cells[1]['notes'] == [39, 40]
    # Cells ordered by their first note
    assert cells[0]['notes'][0] < cells[1]['notes'][0]
    # Thumbnails are the requested size
    assert cells[0]['thumb'].get_size() == (main.GRID_THUMB_W, main.GRID_THUMB_H)


def test_format_notes():
    assert main.format_notes([36]) == '36'
    assert main.format_notes([36, 37, 38]) == '36-38'
    # Non-contiguous notes show each run so gaps are honest, not a bare min-max.
    assert main.format_notes([46, 47, 51, 52, 53]) == '46-47, 51-53'
    assert main.format_notes([36, 40]) == '36, 40'
    assert main.format_notes([]) == ''


def test_cell_highlight_active_faded_and_expired():
    cell = {'notes': [40, 41], 'type': 'image'}
    now = 1000.0

    # Held note -> full strength
    assert main.cell_highlight(cell, active_note=41, flash_times={}, now=now) == 1.0

    # Recently flashed (half the fade window) -> ~0.5, strictly between 0 and 1
    flash = {40: now - main.GRID_FLASH_FADE / 2}
    mid = main.cell_highlight(cell, active_note=None, flash_times=flash, now=now)
    assert 0.0 < mid < 1.0

    # Flashed long ago -> fully expired
    old = {40: now - main.GRID_FLASH_FADE * 2}
    assert main.cell_highlight(cell, active_note=None, flash_times=old, now=now) == 0.0

    # A note that belongs to no cell never highlights it
    assert main.cell_highlight(cell, active_note=99, flash_times={}, now=now) == 0.0


def test_render_grid_clamps_scroll_and_runs():
    screen = pygame.display.get_surface()
    a, b = _img((10, 20, 30)), _img((40, 50, 60))
    note_to_media = {n: (a if n < 50 else b) for n in range(36, 60)}
    cells = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))

    # Over-scrolling is clamped to a finite, non-negative offset
    clamped = main.render_grid(screen, cells, 10 ** 9, {
        'note': pygame.font.SysFont(None, 40),
        'small': pygame.font.SysFont(None, 26),
        'header': pygame.font.SysFont(None, 30),
    }, active_note=36, flash_times={}, now=0.0)
    assert clamped >= 0
    assert clamped < 10 ** 9

    # Under-scrolling is clamped to 0
    zero = main.render_grid(screen, cells, -500, {
        'note': pygame.font.SysFont(None, 40),
        'small': pygame.font.SysFont(None, 26),
        'header': pygame.font.SysFont(None, 30),
    }, active_note=None, flash_times={}, now=0.0)
    assert zero == 0
