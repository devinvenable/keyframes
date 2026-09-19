"""Headless tests for select-to-arm assignment (no A/Enter arm step).

Selecting a grid cell *is* the arm: the next played note — computer-piano key
or incoming MIDI — remaps the selected cell and consumes the selection.

Run with SDL's dummy video driver so no window is needed:
    SDL_VIDEODRIVER=dummy python3 -m pytest test_select_assign.py
"""
import os

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import queue

import mido
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
def media(tmp_path, monkeypatch):
    """Isolated images/ + mapping.json with a.png mapped to 36, b.png unmapped.

    Returns (cells, note_to_media); cells are sorted by filename, so index 0 is
    a.png and index 1 is b.png."""
    images = tmp_path / 'images'
    images.mkdir()
    monkeypatch.setattr(main, 'IMAGES_DIR', str(images))
    monkeypatch.setattr(main, 'MAPPING_PATH', str(tmp_path / 'mapping.json'))
    for name, color in (('a.png', (10, 20, 30)), ('b.png', (40, 50, 60))):
        surf = pygame.Surface((8, 8))
        surf.fill(color)
        pygame.image.save(surf, str(images / name))
    main.save_mapping({36: 'a.png'})
    note_to_media = {36: main.make_media_entry('a.png')}
    cells = main.build_grid_cells(note_to_media,
                                  (main.GRID_THUMB_W, main.GRID_THUMB_H))
    return cells, note_to_media


def _blank_state():
    return {'surface': None, 'video_player': None, 'note_active': None,
            'note_on_time': None, 'hold_until': None, 'zoom_scale': 1.0}


# --- grid_assign_note: selection is the arm ---------------------------------

def test_selected_cell_takes_next_note_and_deselects(media):
    cells, note_to_media = media
    new_cells, selected = main.grid_assign_note(cells, 1, 40, note_to_media)
    assert selected is None  # one selection = one remap
    assert main.load_mapping() == {36: 'a.png', 40: 'b.png'}
    assert note_to_media[40]['name'] == 'b.png'
    assert new_cells[1]['notes'] == [40]


def test_assignment_steals_note_from_prior_cell(media):
    cells, note_to_media = media
    new_cells, selected = main.grid_assign_note(cells, 1, 36, note_to_media)
    assert selected is None
    assert main.load_mapping() == {36: 'b.png'}  # a.png lost its key
    # Cells are key-ordered, so check by content rather than position.
    a_cell = next(c for c in new_cells if c['media']['name'] == 'a.png')
    b_cell = next(c for c in new_cells if c['media']['name'] == 'b.png')
    assert a_cell['notes'] == []      # a.png lost its key
    assert b_cell['notes'] == [36]    # b.png now holds it


def test_no_selection_means_no_remap(media):
    cells, note_to_media = media
    same_cells, selected = main.grid_assign_note(cells, None, 40, note_to_media)
    assert same_cells is cells and selected is None
    assert main.load_mapping() == {36: 'a.png'}


# --- protected / non-piano keys can never reach the assign path -------------

def test_protected_keys_are_not_piano_keys():
    # Assignment only fires for KEY_TO_NOTE presses (they enqueue a note that
    # the assign callback consumes). Every protected binding must therefore
    # stay outside KEY_TO_NOTE, or pressing it while a cell is selected would
    # remap instead of doing its job.
    protected = (pygame.K_TAB, pygame.K_DELETE, pygame.K_BACKSPACE,
                 pygame.K_ESCAPE, pygame.K_F1, pygame.K_QUESTION,
                 pygame.K_F11, pygame.K_RETURN,
                 pygame.K_UP, pygame.K_DOWN, pygame.K_PAGEUP,
                 pygame.K_PAGEDOWN, pygame.K_HOME, pygame.K_END)
    for key in protected:
        assert key not in main.KEY_TO_NOTE


def test_non_piano_keys_have_no_note_to_assign():
    # 'A' used to arm assignment; now it is just a non-piano key = ignored.
    assert pygame.K_a not in main.KEY_TO_NOTE
    assert pygame.K_l not in main.KEY_TO_NOTE


# --- MIDI path: note_on while selected assigns, is consumed, then previews --

def test_midi_note_assigns_selected_cell_and_is_consumed(media):
    cells, note_to_media = media
    sel = {'cells': cells, 'index': 1}

    def assign_if_selected(note):
        if sel['index'] is None:
            return False
        sel['cells'], sel['index'] = main.grid_assign_note(
            sel['cells'], sel['index'], note, note_to_media)
        return True

    q = queue.Queue()
    q.put(mido.Message('note_on', note=40, velocity=100))
    state = main.process_midi_messages(q, 36, 99, note_to_media, (200, 112),
                                       _blank_state(),
                                       assign_callback=assign_if_selected)
    assert sel['index'] is None
    assert main.load_mapping() == {36: 'a.png', 40: 'b.png'}
    # Consumed by the assignment: the note must not also play/display.
    assert state['note_active'] is None and state['surface'] is None

    # With the selection consumed, the next note previews normally.
    q.put(mido.Message('note_on', note=40, velocity=100))
    state = main.process_midi_messages(q, 36, 99, note_to_media, (200, 112),
                                       state, assign_callback=assign_if_selected)
    assert state['note_active'] == 40
    assert main.load_mapping() == {36: 'a.png', 40: 'b.png'}  # unchanged


# --- Delete/Backspace unmap still works -------------------------------------

def test_unmap_cell_clears_key_but_keeps_file(media):
    cells, note_to_media = media
    main.unmap_cell(cells[0], note_to_media)
    assert main.load_mapping() == {}
    assert 36 not in note_to_media
    assert os.path.exists(os.path.join(main.IMAGES_DIR, 'a.png'))
