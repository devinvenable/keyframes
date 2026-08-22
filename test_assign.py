"""Headless tests for play-to-assign (MIDI-learn) note-range assignment.

Covers the pure assign-mode state machine (select -> enter -> capture ->
apply/cancel) and the mapping mutation (apply_assign), both without a window.

Run with SDL's dummy video driver so no display is needed:
    SDL_VIDEODRIVER=dummy python3 -m pytest test_assign.py
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


# --- assign-mode state machine (pure) ---------------------------------------

def test_new_state_is_empty():
    s = main.new_assign_state()
    assert s == {'selected': None, 'active': False, 'captured': []}


def test_select_sets_index_and_stays_inactive():
    s = main.assign_select(main.new_assign_state(), 3)
    assert s['selected'] == 3
    assert s['active'] is False
    assert s['captured'] == []


def test_enter_requires_a_selection():
    # Nothing selected -> enter is a no-op (never captures into thin air).
    s = main.assign_enter(main.new_assign_state())
    assert s['active'] is False


def test_enter_activates_capture_for_selected_cell():
    s = main.assign_enter(main.assign_select(main.new_assign_state(), 2))
    assert s['selected'] == 2
    assert s['active'] is True
    assert s['captured'] == []


def test_capture_ignored_when_not_active():
    # A note played while merely selected (not in assign mode) is NOT captured,
    # so normal grid play never reassigns.
    s = main.assign_select(main.new_assign_state(), 1)
    s2 = main.assign_capture(s, 60)
    assert s2['captured'] == []


def test_capture_records_notes_in_order_when_active():
    s = main.assign_enter(main.assign_select(main.new_assign_state(), 0))
    s = main.assign_capture(s, 62)
    s = main.assign_capture(s, 60)
    s = main.assign_capture(s, 64)
    assert s['captured'] == [62, 60, 64]


def test_capture_dedups_repeats():
    s = main.assign_enter(main.assign_select(main.new_assign_state(), 0))
    s = main.assign_capture(s, 60)
    s = main.assign_capture(s, 60)
    assert s['captured'] == [60]


def test_cancel_leaves_mode_but_keeps_selection():
    s = main.assign_enter(main.assign_select(main.new_assign_state(), 5))
    s = main.assign_capture(s, 60)
    s = main.assign_cancel(s)
    assert s['active'] is False
    assert s['captured'] == []
    assert s['selected'] == 5  # cell stays selected so the user can retry


def test_select_clears_pending_capture():
    s = main.assign_enter(main.assign_select(main.new_assign_state(), 0))
    s = main.assign_capture(s, 60)
    s = main.assign_select(s, 4)  # re-target mid-assign
    assert s['selected'] == 4
    assert s['active'] is False
    assert s['captured'] == []


def test_assign_target_index_finds_cell_by_name():
    cells = [{'media': _img('a.png'), 'notes': [36]},
             {'media': _img('b.png'), 'notes': [40]}]
    assert main.assign_target_index(cells, 'b.png') == 1
    assert main.assign_target_index(cells, 'gone.png') is None


# --- apply_assign: the mapping mutation -------------------------------------

def test_apply_assign_persists_and_updates_live(media_dir):
    images = media_dir / 'images'
    _make_png(images / 'a.png', color=(200, 0, 0))
    _make_png(images / 'b.png', color=(0, 0, 200))
    note_to_media = main.load_media(36, 99)
    cells = main.build_grid_cells(note_to_media,
                                  (main.GRID_THUMB_W, main.GRID_THUMB_H))
    # Pick cell b as the target; grab a note that currently belongs to cell a.
    cell_b = next(c for c in cells if c['media']['name'] == 'b.png')
    cell_a = next(c for c in cells if c['media']['name'] == 'a.png')
    stolen = cell_a['notes'][0]
    b_obj = cell_b['media']

    applied = main.apply_assign(cell_b, [stolen], note_to_media)
    assert applied == [stolen]

    # Persisted: the stolen note now points at b.png on disk.
    saved = main.load_mapping()
    assert saved[stolen] == 'b.png'
    # Live: the stolen note holds the SAME already-loaded b object (no re-decode,
    # so the grid's id()-dedup keeps one cell per file).
    assert note_to_media[stolen] is b_obj


def test_apply_assign_empty_is_noop(media_dir):
    images = media_dir / 'images'
    _make_png(images / 'a.png')
    _make_png(images / 'b.png')
    note_to_media = main.load_media(36, 99)
    cells = main.build_grid_cells(note_to_media,
                                  (main.GRID_THUMB_W, main.GRID_THUMB_H))
    before = dict(main.load_mapping())

    applied = main.apply_assign(cells[0], [], note_to_media)
    assert applied == []
    assert main.load_mapping() == before  # nothing written


def test_apply_assign_multiple_notes_from_several_cells(media_dir):
    images = media_dir / 'images'
    _make_png(images / 'a.png')
    _make_png(images / 'b.png')
    _make_png(images / 'c.png')
    note_to_media = main.load_media(36, 99)
    cells = main.build_grid_cells(note_to_media,
                                  (main.GRID_THUMB_W, main.GRID_THUMB_H))
    target = cells[0]
    target_name = target['media']['name']
    # Steal one note from each of the other two cells.
    stolen = [cells[1]['notes'][0], cells[2]['notes'][0]]

    main.apply_assign(target, stolen, note_to_media)
    main_cells = main.build_grid_cells(note_to_media,
                                       (main.GRID_THUMB_W, main.GRID_THUMB_H))

    saved = main.load_mapping()
    for n in stolen:
        assert saved[n] == target_name
    # Rebuilt grid: the target cell now covers its original notes plus the two
    # stolen ones, and there is still exactly one cell per file.
    target_cell = next(c for c in main_cells if c['media']['name'] == target_name)
    for n in stolen:
        assert n in target_cell['notes']
    names = [c['media']['name'] for c in main_cells]
    assert len(names) == len(set(names))


def test_apply_assign_can_leave_a_file_unreferenced(media_dir):
    # Assigning away every note a single-note cell held makes that file
    # unreferenced — documented as OK (reconcile re-surfaces present files).
    images = media_dir / 'images'
    _make_png(images / 'a.png')
    _make_png(images / 'b.png')
    note_to_media = main.load_media(36, 37)  # exactly two notes -> two cells
    cells = main.build_grid_cells(note_to_media,
                                  (main.GRID_THUMB_W, main.GRID_THUMB_H))
    target = cells[0]
    victim = cells[1]
    victim_name = victim['media']['name']
    victim_notes = list(victim['notes'])

    main.apply_assign(target, victim_notes, note_to_media)
    saved = main.load_mapping()
    # None of the persisted notes point at the victim anymore.
    assert victim_name not in saved.values()


# --- assign_projection: the pure preview (no mutation) ----------------------

def _cell(name, notes):
    return {'media': _img(name), 'type': 'image', 'notes': list(notes)}


def test_projection_empty_when_nothing_captured():
    cells = [_cell('a.png', [36, 37]), _cell('b.png', [40])]
    proj = main.assign_projection(cells, 0, [])
    assert proj == {'selected': None, 'donors': {}}


def test_projection_empty_when_nothing_selected():
    cells = [_cell('a.png', [36]), _cell('b.png', [40])]
    assert main.assign_projection(cells, None, [40]) == {'selected': None,
                                                         'donors': {}}


def test_projection_selected_grows_by_captured():
    cells = [_cell('a.png', [36, 37]), _cell('b.png', [40, 41])]
    proj = main.assign_projection(cells, 0, [40])
    assert proj['selected'] == {'index': 0,
                                'current': [36, 37],
                                'projected': [36, 37, 40]}


def test_projection_donor_loses_exactly_the_captured_notes_it_held():
    # b holds 40,41,42; capturing 41 for cell a: b loses ONLY 41, keeps 40,42.
    cells = [_cell('a.png', [36]), _cell('b.png', [40, 41, 42])]
    proj = main.assign_projection(cells, 0, [41])
    assert proj['donors'] == {1: {'losing': [41],
                                  'remaining': [40, 42],
                                  'emptied': False}}


def test_projection_flags_donor_emptied_when_all_notes_taken():
    cells = [_cell('a.png', [36]), _cell('b.png', [40, 41])]
    proj = main.assign_projection(cells, 0, [40, 41])
    assert proj['donors'][1]['emptied'] is True
    assert proj['donors'][1]['remaining'] == []
    assert proj['donors'][1]['losing'] == [40, 41]


def test_projection_spans_multiple_donors_and_ignores_unheld_notes():
    cells = [_cell('a.png', [36]),
             _cell('b.png', [40, 41]),
             _cell('c.png', [50])]
    # Capture one note from b, all of c, plus 99 which no cell holds.
    proj = main.assign_projection(cells, 0, [40, 50, 99])
    assert proj['selected']['projected'] == [36, 40, 50, 99]
    assert set(proj['donors']) == {1, 2}
    assert proj['donors'][1] == {'losing': [40], 'remaining': [41],
                                 'emptied': False}
    assert proj['donors'][2] == {'losing': [50], 'remaining': [],
                                 'emptied': True}


def test_projection_does_not_list_selected_cell_as_its_own_donor():
    # Capturing a note the selected cell already holds: no donor, no change.
    cells = [_cell('a.png', [36, 37]), _cell('b.png', [40])]
    proj = main.assign_projection(cells, 0, [36])
    assert proj['donors'] == {}
    assert proj['selected']['projected'] == [36, 37]


def test_projection_does_not_mutate_cells():
    cells = [_cell('a.png', [36]), _cell('b.png', [40, 41])]
    before = [list(c['notes']) for c in cells]
    main.assign_projection(cells, 0, [40])
    assert [c['notes'] for c in cells] == before


# --- end-to-end via the shared apply path -----------------------------------

def test_capture_then_apply_full_flow(media_dir):
    """Drive the whole flow with the pure pieces the loop uses: select a cell,
    enter, capture two notes, then apply them via apply_assign."""
    images = media_dir / 'images'
    _make_png(images / 'a.png')
    _make_png(images / 'b.png')
    note_to_media = main.load_media(36, 99)
    cells = main.build_grid_cells(note_to_media,
                                  (main.GRID_THUMB_W, main.GRID_THUMB_H))
    target_idx = 0
    target_name = cells[target_idx]['media']['name']
    other = next(c for c in cells if c['media']['name'] != target_name)
    notes = other['notes'][:2] if len(other['notes']) >= 2 else other['notes'][:1]

    s = main.new_assign_state()
    s = main.assign_select(s, target_idx)
    s = main.assign_enter(s)
    for n in notes:
        s = main.assign_capture(s, n)
    assert s['captured'] == list(notes)

    applied = main.apply_assign(cells[target_idx], s['captured'], note_to_media)
    assert applied == list(notes)
    saved = main.load_mapping()
    for n in notes:
        assert saved[n] == target_name
