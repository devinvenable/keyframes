"""Headless tests for click-to-replace (pygame DROPFILE) media reassignment.

Run with SDL's dummy video driver so no window is needed:
    SDL_VIDEODRIVER=dummy python3 -m pytest test_click_replace.py
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


def _video(name):
    return {'type': 'video', 'path': os.path.join(main.IMAGES_DIR, name),
            'name': name}


# --- supported_media_file ---------------------------------------------------

def test_supported_media_file():
    assert main.supported_media_file('/x/a.png')
    assert main.supported_media_file('/x/a.MP4')      # case-insensitive
    assert main.supported_media_file('a.jpeg')
    assert not main.supported_media_file('/x/notes.txt')
    assert not main.supported_media_file('/x/no_ext')


# --- grid_cell_at: the drop hit-test ----------------------------------------

def test_grid_cell_at_hits_the_cell_under_the_cursor():
    cells = [{'notes': [n], 'type': 'image'} for n in range(36, 44)]
    screen = (800, 600)
    layout = main.grid_layout(len(cells), 0, screen)
    # Aim at the center of cell index 3.
    x, y = main.cell_rect(3, layout)
    pos = (x + main.GRID_THUMB_W // 2, y + main.GRID_THUMB_H // 2)
    assert main.grid_cell_at(cells, 0, screen, pos) == 3


def test_grid_cell_at_misses_gap_between_cells():
    cells = [{'notes': [n], 'type': 'image'} for n in range(36, 44)]
    screen = (800, 600)
    # A drop in the inter-cell padding (just right of cell 0's thumbnail) misses.
    layout = main.grid_layout(len(cells), 0, screen)
    x, y = main.cell_rect(0, layout)
    gap_x = x + main.GRID_THUMB_W + main.GRID_PAD // 2
    assert main.grid_cell_at(cells, 0, screen, (gap_x, y + 10)) is None


def test_grid_cell_at_ignores_cells_scrolled_under_the_header():
    # Enough cells to allow a real scroll offset.
    cells = [{'notes': [n], 'type': 'image'} for n in range(36, 66)]
    screen = (800, 600)
    # Scroll until a second-row cell's thumbnail slides partly under the header.
    scroll = 134
    layout = main.grid_layout(len(cells), scroll, screen)
    x, y = main.cell_rect(3, layout)  # first cell of row 1
    assert y < layout['top'], "test setup: cell must overlap the header band"
    # A point inside that cell's rect but within the header band must NOT hit it:
    # the header owns those pixels (Tab/scroll hints), a drop there is not a drop
    # on the note hiding beneath.
    hdr_y = layout['top'] - 2
    assert y <= hdr_y < y + main.GRID_THUMB_H, "test setup: point must be in cell rect"
    assert main.grid_cell_at(cells, scroll, screen,
                             (x + main.GRID_THUMB_W // 2, hdr_y)) is None
    # ...but the same cell IS hittable just below the header.
    assert main.grid_cell_at(cells, scroll, screen,
                             (x + main.GRID_THUMB_W // 2, layout['top'] + 2)) == 3


def test_grid_cell_at_empty_grid_returns_none():
    assert main.grid_cell_at([], 0, (800, 600), (400, 300)) is None


# --- import_dropped_file ----------------------------------------------------

def test_import_dropped_file_copies_external_file(media_dir, tmp_path):
    src = tmp_path / 'incoming.png'
    _make_png(src)
    name = main.import_dropped_file(str(src))
    assert name == 'incoming.png'
    assert os.path.exists(os.path.join(main.IMAGES_DIR, 'incoming.png'))


def test_import_dropped_file_leaves_existing_in_place(media_dir):
    # A file already in images/ is reused, not re-copied over itself.
    existing = os.path.join(main.IMAGES_DIR, 'already.png')
    _make_png(existing, color=(1, 2, 3))
    before = os.path.getmtime(existing)
    name = main.import_dropped_file(existing)
    assert name == 'already.png'
    assert os.path.getmtime(existing) == before  # untouched


# --- reassign_cell_media: shared-object dedup invariant ----------------------

def test_reassign_reuses_already_loaded_object():
    shared = _video('clip.mp4')
    other = _video('old.mp4')
    note_to_media = {36: shared, 37: shared, 40: other}
    main.reassign_cell_media(note_to_media, [40], 'clip.mp4')
    # note 40 must now be the SAME object already loaded for clip.mp4, not a
    # second copy — otherwise the grid shows two cells for one file.
    assert note_to_media[40] is shared


def test_reassign_creates_one_object_for_new_file():
    note_to_media = {36: _video('old.mp4'), 37: _video('old.mp4')}
    main.reassign_cell_media(note_to_media, [36, 37], 'fresh.mp4')
    assert note_to_media[36] is note_to_media[37]
    assert note_to_media[36]['name'] == 'fresh.mp4'


# --- apply_drop: end-to-end reassignment ------------------------------------

def test_apply_drop_persists_mapping_and_updates_media_live(media_dir, tmp_path):
    images = media_dir / 'images'
    _make_png(images / 'a.png')
    _make_png(images / 'b.png')
    note_to_media = main.load_media(36, 99)
    cells = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    target = cells[0]
    notes = list(target['notes'])

    src = tmp_path / 'dropped.png'
    _make_png(src, color=(200, 100, 50))
    ok = main.apply_drop(str(src), target, note_to_media)

    old_name = target['media']['name']
    assert ok is True
    # File landed in images/
    assert os.path.exists(images / 'dropped.png')
    # The replaced file is deleted so no orphan cell remains.
    assert old_name != 'dropped.png'
    assert not os.path.exists(images / old_name)
    # Mapping persisted for every note of the cell.
    saved = main.load_mapping()
    for n in notes:
        assert saved[n] == 'dropped.png'
    # Live media updated in place for those notes.
    for n in notes:
        assert note_to_media[n]['name'] == 'dropped.png'


def test_apply_drop_shares_object_with_notes_already_on_that_file(media_dir, tmp_path):
    images = media_dir / 'images'
    _make_png(images / 'a.png')
    _make_png(images / 'b.png')
    note_to_media = main.load_media(36, 99)
    cells = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))

    # Reassign cell 1 to the filename already backing cell 0.
    name0 = cells[0]['media']['name']
    obj0 = cells[0]['media']
    main.apply_drop(os.path.join(str(images), name0), cells[1], note_to_media)

    rebuilt = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    names = [c['media']['name'] for c in rebuilt]
    # The file appears in exactly one cell despite two cells now using it.
    assert names.count(name0) == 1
    # And it is the same shared object, not a second decode.
    for n, media in note_to_media.items():
        if media['name'] == name0:
            assert media is obj0


def test_apply_drop_rejects_unsupported_type(media_dir, tmp_path):
    images = media_dir / 'images'
    _make_png(images / 'a.png')
    note_to_media = main.load_media(36, 99)
    cells = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    before = dict(main.load_mapping())

    bad = tmp_path / 'notes.txt'
    bad.write_text('nope')
    ok = main.apply_drop(str(bad), cells[0], note_to_media)

    assert ok is False
    assert not os.path.exists(images / 'notes.txt')  # not copied
    assert os.path.exists(images / 'a.png')          # target left intact
    assert main.load_mapping() == before             # mapping untouched


# --- apply_drop: new replace-in-place behavior (T52) -------------------------

def test_apply_drop_on_mapped_cell_keeps_key_points_at_b_removes_a(media_dir, tmp_path):
    images = media_dir / 'images'
    _make_png(images / 'a.png')
    note_to_media = main.load_media(36, 99)
    cells = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    target = cells[0]
    key = target['notes'][0]  # the cell is mapped to a key
    assert target['media']['name'] == 'a.png'

    src = tmp_path / 'b.png'
    _make_png(src, color=(9, 9, 9))
    ok = main.apply_drop(str(src), target, note_to_media)

    assert ok is True
    # The key stays and now triggers B.
    assert main.load_mapping()[key] == 'b.png'
    assert note_to_media[key]['name'] == 'b.png'
    # A's file is gone; B is present.
    assert not os.path.exists(images / 'a.png')
    assert os.path.exists(images / 'b.png')
    # Rebuilt grid: exactly one cell, showing B on the key.
    rebuilt = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    assert [c['media']['name'] for c in rebuilt] == ['b.png']
    assert rebuilt[0]['notes'] == [key]


def test_apply_drop_on_unmapped_cell_swaps_file_no_key(media_dir, tmp_path):
    images = media_dir / 'images'
    _make_png(images / 'c.png')
    # An unmapped cell: no note_to_media entry, notes empty.
    note_to_media = {}
    cell = {'media': {'name': 'c.png', 'type': 'image'}, 'type': 'image',
            'notes': []}

    src = tmp_path / 'd.png'
    _make_png(src, color=(3, 4, 5))
    ok = main.apply_drop(str(src), cell, note_to_media)

    assert ok is True
    # No key was created.
    assert main.load_mapping() == {}
    assert all(m['name'] != 'd.png' for m in note_to_media.values())
    # File swapped: A deleted, B present.
    assert not os.path.exists(images / 'c.png')
    assert os.path.exists(images / 'd.png')
    # Rebuilt grid shows B as a single unmapped cell.
    rebuilt = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    assert [c['media']['name'] for c in rebuilt] == ['d.png']
    assert rebuilt[0]['notes'] == []


def test_apply_drop_same_file_onto_own_cell_is_noop_no_delete(media_dir):
    images = media_dir / 'images'
    _make_png(images / 'a.png')
    note_to_media = main.load_media(36, 99)
    cells = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    target = cells[0]
    key = target['notes'][0]

    # Drop a.png onto a.png's own cell — the file must survive.
    ok = main.apply_drop(os.path.join(str(images), 'a.png'), target, note_to_media)

    assert ok is True
    assert os.path.exists(images / 'a.png')       # NOT deleted
    assert main.load_mapping()[key] == 'a.png'    # key unchanged
    assert note_to_media[key]['name'] == 'a.png'


def test_remove_media_file_never_unlinks_outside_images_dir(media_dir, tmp_path):
    images = media_dir / 'images'
    # A file living outside images/, reachable only via a traversal basename.
    outside = tmp_path / 'secret.png'
    _make_png(outside)
    assert outside.exists()

    # A crafted "name" that would escape IMAGES_DIR must be refused.
    escaped = main.remove_media_file(os.path.join('..', 'secret.png'))
    assert escaped is False
    assert outside.exists()                       # untouched

    # An empty name and a name equal to `keep` are also no-ops.
    assert main.remove_media_file('') is False
    _make_png(images / 'keepme.png')
    assert main.remove_media_file('keepme.png', keep='keepme.png') is False
    assert os.path.exists(images / 'keepme.png')

    # A legitimate in-dir file IS removed.
    _make_png(images / 'gone.png')
    assert main.remove_media_file('gone.png') is True
    assert not os.path.exists(images / 'gone.png')
