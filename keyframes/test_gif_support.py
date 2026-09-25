"""Headless tests for animated GIF support (T127).

GIFs are classified as videos (VIDEO_EXTS) so they ride the existing
VideoPlayer / thumbnail / drop / interleave pipeline; unlike real videos they
carry a loop flag so a held note keeps the animation cycling instead of
freezing on the last frame.

Decoding tests need a real animated GIF; it is generated with the system
ffmpeg and skipped when ffmpeg is unavailable.

Run with SDL's dummy video driver:
    SDL_VIDEODRIVER=dummy python3 -m pytest test_gif_support.py
"""
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


@pytest.fixture(scope='module')
def gif_path(tmp_path_factory):
    """A small 5-frame animated GIF, generated with ffmpeg."""
    if shutil.which('ffmpeg') is None:
        pytest.skip('ffmpeg not available to generate a test GIF')
    path = str(tmp_path_factory.mktemp('gif') / 'anim.gif')
    subprocess.run(
        ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi',
         '-i', 'testsrc=duration=0.5:size=64x48:rate=10', path],
        check=True)
    return path


# --- classification ---------------------------------------------------------

def test_gif_is_a_video_extension():
    assert '.gif' in main.VIDEO_EXTS
    assert '.gif' not in main.IMAGE_EXTS
    assert '.gif' in main.LOOP_EXTS


def test_supported_media_file_accepts_gif_case_insensitively():
    assert main.supported_media_file('/anywhere/clip.gif')
    assert main.supported_media_file('/anywhere/CLIP.GIF')


def test_make_media_entry_marks_gif_as_looping_video():
    entry = main.make_media_entry('anim.gif')
    assert entry['type'] == 'video'
    assert entry['loop'] is True


def test_make_media_entry_marks_real_video_as_non_looping():
    entry = main.make_media_entry('clip.mp4')
    assert entry['type'] == 'video'
    assert entry['loop'] is False


def test_order_media_files_interleaves_gifs_as_videos():
    ordered = main.order_media_files(
        ['a.png', 'b.png', 'c.png', 'anim.gif', 'clip.mp4'])
    assert sorted(ordered) == ['a.png', 'anim.gif', 'b.png', 'c.png', 'clip.mp4']
    # Videos (gif included) are spread among the images, not clumped at the end.
    assert ordered[0] == 'a.png'
    assert ordered[-1] != 'clip.mp4' or ordered[-2] != 'anim.gif'


def test_list_media_files_includes_gifs(monkeypatch, tmp_path):
    for name in ('a.png', 'anim.gif', 'notes.txt'):
        (tmp_path / name).write_bytes(b'')
    monkeypatch.setattr(main, 'IMAGES_DIR', str(tmp_path))
    assert sorted(main.list_media_files()) == ['a.png', 'anim.gif']


# --- playback: loop vs freeze ------------------------------------------------

def _drain(player, limit=10000):
    """Advance until the player finishes or ``limit`` frames pass."""
    for i in range(limit):
        player.get_frame()
        if player.finished:
            return i
    return limit


def test_looping_player_never_finishes_and_keeps_decoding(gif_path):
    # Step clock: a frame is due on every call despite fps pacing.
    player = main.VideoPlayer(gif_path, (64, 48), loop=True,
                              clock=main.make_step_clock(1.0))
    try:
        # The GIF has 5 frames; read far past the end.
        frames = [player.get_frame() for _ in range(23)]
        assert player.finished is False
        assert all(f is not None for f in frames)
        # Post-rewind frames are freshly decoded, not the frozen last surface.
        assert frames[-1] is not frames[-2]
    finally:
        player.release()


def test_non_looping_player_still_freezes_on_last_frame(gif_path):
    player = main.VideoPlayer(gif_path, (64, 48), loop=False,
                              clock=main.make_step_clock(1.0))
    try:
        assert _drain(player) < 10000
        assert player.finished is True
        assert player.get_frame() is player.last_surface
    finally:
        player.release()


def test_loop_defaults_off(gif_path):
    player = main.VideoPlayer(gif_path, (64, 48))
    try:
        assert player.loop is False
    finally:
        player.release()


# --- integration: note-on and thumbnails -------------------------------------

def test_note_on_starts_a_looping_player_for_a_gif(gif_path):
    import queue
    import mido
    media = {'type': 'video', 'path': gif_path, 'name': 'anim.gif',
             'loop': True}
    state = {'surface': None, 'video_player': None, 'note_active': None,
             'note_on_time': None, 'hold_until': None, 'zoom_scale': 1.0,
             'inverted': False, 'surface_media': None, 'last_note': None}
    q = queue.Queue()
    q.put(mido.Message('note_on', note=60, velocity=100))
    state = main.process_midi_messages(q, 36, 99, {60: media}, (64, 48), state)
    try:
        assert state['video_player'] is not None
        assert state['video_player'].loop is True
        assert state['note_active'] == 60
    finally:
        state['video_player'].release()


def test_make_thumbnail_decodes_gif_first_frame(gif_path):
    media = {'type': 'video', 'path': gif_path, 'name': 'anim.gif',
             'loop': True}
    thumb = main.make_thumbnail(media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    assert thumb.get_size() == (main.GRID_THUMB_W, main.GRID_THUMB_H)
    # ffmpeg's testsrc pattern is non-black, so a decoded thumb has color.
    non_black = any(
        thumb.get_at((x, y))[:3] != (0, 0, 0)
        for x in range(0, main.GRID_THUMB_W, 7)
        for y in range(0, main.GRID_THUMB_H, 7)
    )
    assert non_black


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
