"""Headless tests for the grid press-and-hold video preview gesture (T31).

The gesture is shared with drag-to-rearrange: a mouse-down on a cell is PENDING;
past GRID_DRAG_THRESHOLD it becomes a rearrange DRAG (no preview); while it stays
put on a VIDEO cell it drives an in-place preview. These tests pin the pending /
drag / preview state machine and the preview draw, all without a real window.

Run with SDL's dummy video driver:
    SDL_VIDEODRIVER=dummy python3 -m pytest test_grid_preview.py
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


SCREEN = (800, 600)


def _cell(kind, note, path=None):
    """A minimal grid cell of the shape build_grid_cells() produces."""
    thumb = pygame.Surface((main.GRID_THUMB_W, main.GRID_THUMB_H))
    thumb.fill((30, 30, 30))
    media = {'type': kind, 'name': f'n{note}.{"mp4" if kind == "video" else "png"}'}
    if path is not None:
        media['path'] = path
    return {'type': kind, 'thumb': thumb, 'media': media, 'notes': [note]}


def _cells():
    # index 0 = video, index 1 = image
    return [_cell('video', 36), _cell('image', 37)]


def _center(cells, index, scroll_y=0):
    """Pixel position at the center of cell ``index``."""
    layout = main.grid_layout(len(cells), scroll_y, SCREEN)
    x, y = main.cell_rect(index, layout)
    return (x + main.GRID_THUMB_W // 2, y + main.GRID_THUMB_H // 2)


# --- begin_grid_gesture -----------------------------------------------------

def test_begin_on_video_cell_marks_video_and_pending():
    cells = _cells()
    g = main.begin_grid_gesture(cells, 0, SCREEN, _center(cells, 0))
    assert g is not None
    assert g['from_index'] == 0
    assert g['is_video'] is True
    assert g['moved'] is False


def test_begin_on_image_cell_is_not_video():
    cells = _cells()
    g = main.begin_grid_gesture(cells, 0, SCREEN, _center(cells, 1))
    assert g['from_index'] == 1
    assert g['is_video'] is False


def test_begin_off_any_cell_returns_none():
    cells = _cells()
    # y=0 is the header band, never a cell.
    assert main.begin_grid_gesture(cells, 0, SCREEN, (5, 0)) is None


# --- update_grid_gesture: pending -> drag latch -----------------------------

def test_small_move_stays_pending():
    cells = _cells()
    g = main.begin_grid_gesture(cells, 0, SCREEN, _center(cells, 0))
    sx, sy = g['start']
    main.update_grid_gesture(g, (sx + main.GRID_DRAG_THRESHOLD, sy))  # not past
    assert g['moved'] is False


def test_move_past_threshold_becomes_drag():
    cells = _cells()
    g = main.begin_grid_gesture(cells, 0, SCREEN, _center(cells, 0))
    sx, sy = g['start']
    main.update_grid_gesture(g, (sx + main.GRID_DRAG_THRESHOLD + 1, sy))
    assert g['moved'] is True


def test_drag_latches_and_never_reverts():
    cells = _cells()
    g = main.begin_grid_gesture(cells, 0, SCREEN, _center(cells, 0))
    sx, sy = g['start']
    main.update_grid_gesture(g, (sx + 50, sy + 50))  # clearly a drag
    assert g['moved'] is True
    main.update_grid_gesture(g, (sx, sy))  # back to origin
    assert g['moved'] is True  # stays a drag


# --- gesture_previews: the preview predicate --------------------------------

def test_previews_true_for_held_video_on_its_cell():
    cells = _cells()
    pos = _center(cells, 0)
    g = main.begin_grid_gesture(cells, 0, SCREEN, pos)
    assert main.gesture_previews(g, cells, 0, SCREEN, pos) is True


def test_no_preview_for_image_cell():
    cells = _cells()
    pos = _center(cells, 1)
    g = main.begin_grid_gesture(cells, 0, SCREEN, pos)
    assert main.gesture_previews(g, cells, 0, SCREEN, pos) is False


def test_no_preview_once_it_is_a_drag():
    cells = _cells()
    pos = _center(cells, 0)
    g = main.begin_grid_gesture(cells, 0, SCREEN, pos)
    g['moved'] = True
    assert main.gesture_previews(g, cells, 0, SCREEN, pos) is False


def test_no_preview_when_pointer_leaves_the_cell():
    cells = _cells()
    g = main.begin_grid_gesture(cells, 0, SCREEN, _center(cells, 0))
    # Pointer now over the OTHER cell (still within threshold is impossible
    # across cells, but the predicate must guard it regardless).
    assert main.gesture_previews(g, cells, 0, SCREEN, _center(cells, 1)) is False


def test_no_preview_without_a_gesture():
    cells = _cells()
    assert main.gesture_previews(None, cells, 0, SCREEN, _center(cells, 0)) is False


# --- draw_grid_preview + VideoPlayer end-to-end -----------------------------

def _video_path():
    # Prefer the committed starter clip: it is short (so the freeze test reaches
    # the end) and non-black (so the decode test sees pixels). Falling back to an
    # arbitrary user video in images/ makes these tests non-portable — a long or
    # fade-from-black clip fails assumptions that starter-pulse.mp4 guarantees.
    names = sorted(os.listdir(main.IMAGES_DIR))
    preferred = [n for n in names if n.lower() == 'starter-pulse.mp4']
    for name in preferred + [n for n in names if n.lower().endswith('.mp4')]:
        return os.path.join(main.IMAGES_DIR, name)
    return None


def test_draw_grid_preview_blits_a_decoded_frame_onto_the_cell():
    path = _video_path()
    if path is None:
        pytest.skip('no .mp4 in images/ to decode')
    cells = [_cell('video', 36, path=path), _cell('image', 37)]
    screen = pygame.display.get_surface()
    screen.fill((0, 0, 0))
    player = main.VideoPlayer(path, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    try:
        preview = {'index': 0, 'player': player}
        main.draw_grid_preview(screen, cells, 0, preview)
    finally:
        player.release()
    # Something was drawn onto cell 0's rect (frame is not all-black).
    layout = main.grid_layout(len(cells), 0, screen.get_size())
    x, y = main.cell_rect(0, layout)
    non_black = any(
        screen.get_at((x + dx, y + dy))[:3] != (0, 0, 0)
        for dx in range(0, main.GRID_THUMB_W, 7)
        for dy in range(0, main.GRID_THUMB_H, 7)
    )
    assert non_black


def test_draw_grid_preview_none_is_a_noop():
    screen = pygame.display.get_surface()
    main.draw_grid_preview(screen, _cells(), 0, None)  # must not raise


def test_video_player_freezes_on_last_frame():
    path = _video_path()
    if path is None:
        pytest.skip('no .mp4 in images/ to decode')
    player = main.VideoPlayer(path, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    try:
        last = None
        for _ in range(10000):
            frame = player.get_frame()
            if player.finished:
                last = frame
                break
        assert player.finished is True
        # A finished player keeps returning the frozen last frame, not None.
        assert player.get_frame() is last
    finally:
        player.release()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
