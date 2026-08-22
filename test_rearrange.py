"""Headless tests for drag-to-rearrange (in-grid note<->note swap).

Run with SDL's dummy video driver so no window is needed:
    SDL_VIDEODRIVER=dummy python3 -m pytest test_rearrange.py
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


@pytest.fixture
def media_dir(tmp_path, monkeypatch):
    """Point main at an isolated images/ dir and mapping.json under tmp_path."""
    images = tmp_path / 'images'
    images.mkdir()
    monkeypatch.setattr(main, 'IMAGES_DIR', str(images))
    monkeypatch.setattr(main, 'MAPPING_PATH', str(tmp_path / 'mapping.json'))
    return tmp_path


def _make_png(path, color=(10, 20, 30)):
    surf = pygame.Surface((8, 8))
    surf.fill(color)
    pygame.image.save(surf, str(path))


def _img(name):
    return {'type': 'image', 'surface': pygame.Surface((4, 4)), 'name': name}


# --- swap_cell_mapping: the pure manifest edit ------------------------------

def test_swap_cell_mapping_swaps_single_notes():
    mapping = {36: 'a.png', 40: 'b.png'}
    main.swap_cell_mapping(mapping, [36], 'a.png', [40], 'b.png')
    assert mapping[36] == 'b.png'
    assert mapping[40] == 'a.png'


def test_swap_cell_mapping_swaps_all_notes_of_multi_note_cells():
    # Cell A backs three notes, cell B backs two — every note moves.
    mapping = {36: 'a.png', 37: 'a.png', 38: 'a.png', 50: 'b.png', 51: 'b.png'}
    main.swap_cell_mapping(mapping, [36, 37, 38], 'a.png', [50, 51], 'b.png')
    assert mapping[36] == mapping[37] == mapping[38] == 'b.png'
    assert mapping[50] == mapping[51] == 'a.png'


def test_swap_cell_mapping_leaves_untouched_notes_alone():
    mapping = {36: 'a.png', 40: 'b.png', 44: 'c.png'}
    main.swap_cell_mapping(mapping, [36], 'a.png', [40], 'b.png')
    assert mapping[44] == 'c.png'  # a third file's note is not disturbed


# --- swap_cells_media: live object identity ---------------------------------

def test_swap_cells_media_moves_objects_preserving_identity():
    obj_a = _img('a.png')
    obj_b = _img('b.png')
    note_to_media = {36: obj_a, 37: obj_a, 40: obj_b}
    main.swap_cells_media(note_to_media, [36, 37], obj_a, [40], obj_b)
    # A's notes now hold the SAME B object (no re-decode); B's note holds A.
    assert note_to_media[36] is obj_b
    assert note_to_media[37] is obj_b
    assert note_to_media[40] is obj_a


# --- apply_swap: end-to-end rearrange ---------------------------------------

def test_apply_swap_persists_and_updates_live(media_dir):
    images = media_dir / 'images'
    _make_png(images / 'a.png', color=(200, 0, 0))
    _make_png(images / 'b.png', color=(0, 0, 200))
    note_to_media = main.load_media(36, 99)
    cells = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    cell_a, cell_b = cells[0], cells[1]
    name_a, name_b = cell_a['media']['name'], cell_b['media']['name']
    notes_a, notes_b = list(cell_a['notes']), list(cell_b['notes'])
    obj_a, obj_b = cell_a['media'], cell_b['media']

    ok = main.apply_swap(cell_a, cell_b, note_to_media)
    assert ok is True

    # Manifest persisted with the two sides swapped.
    saved = main.load_mapping()
    for n in notes_a:
        assert saved[n] == name_b
    for n in notes_b:
        assert saved[n] == name_a
    # Live media swapped, reusing the already-loaded objects (no re-decode).
    for n in notes_a:
        assert note_to_media[n] is obj_b
    for n in notes_b:
        assert note_to_media[n] is obj_a


def test_apply_swap_keeps_one_cell_per_file(media_dir):
    images = media_dir / 'images'
    _make_png(images / 'a.png')
    _make_png(images / 'b.png')
    _make_png(images / 'c.png')
    note_to_media = main.load_media(36, 99)
    cells = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    before = len(cells)
    main.apply_swap(cells[0], cells[2], note_to_media)
    rebuilt = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    # Rearranging is not adding/removing media: same number of cells.
    assert len(rebuilt) == before
    names = [c['media']['name'] for c in rebuilt]
    assert len(names) == len(set(names))  # still exactly one cell per file


def test_apply_swap_onto_self_is_a_noop(media_dir):
    images = media_dir / 'images'
    _make_png(images / 'a.png')
    _make_png(images / 'b.png')
    note_to_media = main.load_media(36, 99)
    cells = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    before = dict(main.load_mapping())
    ok = main.apply_swap(cells[0], cells[0], note_to_media)
    assert ok is False
    assert main.load_mapping() == before  # nothing swapped, nothing saved-over


def test_apply_swap_is_its_own_inverse(media_dir):
    # Swapping A<->B, then B<->A (same objects) restores the original mapping.
    images = media_dir / 'images'
    _make_png(images / 'a.png')
    _make_png(images / 'b.png')
    note_to_media = main.load_media(36, 99)
    original = dict(main.load_mapping())
    cells = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    main.apply_swap(cells[0], cells[1], note_to_media)
    cells2 = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    main.apply_swap(cells2[0], cells2[1], note_to_media)
    assert main.load_mapping() == original


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
