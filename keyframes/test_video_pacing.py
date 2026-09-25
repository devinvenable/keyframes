"""Headless tests for fps-paced video decoding (T162).

VideoPlayer.get_frame() must decode at the media's frame rate, not at the
caller's render-loop rate: a 30fps file under a 60Hz loop was decoded ~2x
over AND played back visually fast, and the decode burst competed with the
audio graph (canon midi:I39). The clock is injectable, so these tests drive
playback with fake clocks and count actual decoder work via a wrapped
VideoCapture.

Run with SDL's dummy video driver:
    SDL_VIDEODRIVER=dummy python3 -m pytest test_video_pacing.py
"""
import os
import shutil
import subprocess

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import numpy as np
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
    """A 10fps, 5-frame animated GIF, generated with ffmpeg."""
    if shutil.which('ffmpeg') is None:
        pytest.skip('ffmpeg not available to generate a test GIF')
    path = str(tmp_path_factory.mktemp('gif') / 'anim.gif')
    subprocess.run(
        ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi',
         '-i', 'testsrc=duration=0.5:size=64x48:rate=10', path],
        check=True)
    return path


class CountingCap:
    """Wraps a cv2.VideoCapture and counts frames actually consumed.

    Only successful read()/grab() calls count: a failed grab at end of a
    looping stream (followed by rewind + retry) consumes nothing."""

    def __init__(self, cap):
        self._cap = cap
        self.reads = 0
        self.grabs = 0

    @property
    def consumed(self):
        return self.reads + self.grabs

    def read(self):
        ret, frame = self._cap.read()
        if ret:
            self.reads += 1
        return ret, frame

    def grab(self):
        ok = self._cap.grab()
        if ok:
            self.grabs += 1
        return ok

    def __getattr__(self, name):
        return getattr(self._cap, name)


class ManualClock:
    """A clock the test moves by hand."""

    def __init__(self, start=100.0):
        self.t = start

    def __call__(self):
        return self.t


def _counting_player(path, clock, loop=True):
    player = main.VideoPlayer(path, (64, 48), loop=loop, clock=clock)
    player.cap = CountingCap(player.cap)
    return player


# --- pacing: media slower than the render loop -------------------------------

def test_media_fps_reported_for_generated_gif(gif_path):
    player = main.VideoPlayer(gif_path, (64, 48), loop=True)
    try:
        assert player.fps == 10
    finally:
        player.release()


def test_60hz_render_loop_decodes_at_media_fps_not_loop_rate(gif_path):
    # One simulated second of a 60Hz render loop over 10fps media:
    # ~10 frames decoded, not 60.
    player = _counting_player(gif_path, main.make_step_clock(1 / 60))
    try:
        for _ in range(60):
            assert player.get_frame() is not None
        assert 9 <= player.cap.consumed <= 12
    finally:
        player.release()


def test_no_frame_due_returns_same_surface_without_decoding(gif_path):
    clock = ManualClock()
    player = _counting_player(gif_path, clock)
    try:
        first = player.get_frame()
        reads_after_first = player.cap.reads
        clock.t += 0.01  # 10ms later: next 10fps frame not due for 90ms
        assert player.get_frame() is first
        assert player.cap.reads == reads_after_first
        clock.t += 0.1  # past the frame interval: a fresh decode
        assert player.get_frame() is not first
        assert player.cap.reads == reads_after_first + 1
    finally:
        player.release()


# --- pacing: media faster than the render loop --------------------------------

def test_fast_media_skips_frames_to_stay_real_time(gif_path):
    # Pretend the media is 120fps while the render loop runs at 30Hz: the
    # player must consume ~4 frames per call (grab-skipping the unshown
    # ones) so playback stays real-time instead of slowing to 30fps.
    player = _counting_player(gif_path, main.make_step_clock(1 / 30))
    player.fps = 120
    try:
        calls = 30  # one simulated second
        for _ in range(calls):
            assert player.get_frame() is not None
        assert player.cap.reads == calls  # exactly one rendered frame per call
        assert 100 <= player.cap.consumed <= 140  # ~120 frames of timeline
    finally:
        player.release()


# --- pacing: stalls ----------------------------------------------------------

def test_long_stall_resyncs_instead_of_decode_burst(gif_path):
    clock = ManualClock()
    player = _counting_player(gif_path, clock)
    try:
        player.get_frame()
        consumed_before = player.cap.consumed
        clock.t += 10.0  # a 10s stall is 100 overdue frames at 10fps
        player.get_frame()
        burst = player.cap.consumed - consumed_before
        assert burst <= main.MAX_DECODE_CATCHUP + 1
        # Resynced: the very next call a frame later decodes exactly one.
        clock.t += 0.1
        consumed_before = player.cap.consumed
        player.get_frame()
        assert player.cap.consumed - consumed_before == 1
    finally:
        player.release()


# --- unknown fps falls back to decode-per-call --------------------------------

class FakeUnknownFpsCap:
    """A capture that reports no frame rate and yields synthetic frames."""

    def __init__(self, *_args):
        self.reads = 0

    def isOpened(self):  # noqa: N802 (cv2 API name)
        return True

    def get(self, _prop):
        return 0.0

    def read(self):
        self.reads += 1
        frame = np.full((48, 64, 3), self.reads % 255, dtype=np.uint8)
        return True, frame

    def grab(self):
        raise AssertionError('unpaced playback must never grab-skip')

    def release(self):
        pass


def test_unknown_fps_decodes_once_per_call(monkeypatch):
    monkeypatch.setattr(main.cv2, 'VideoCapture', FakeUnknownFpsCap)
    player = main.VideoPlayer('fake.mp4', (64, 48))
    assert player.fps == 0
    surfaces = [player.get_frame() for _ in range(5)]
    assert player.cap.reads == 5
    assert all(s is not None for s in surfaces)
    assert surfaces[-1] is not surfaces[-2]


# --- decode-thread capping ----------------------------------------------------

def test_open_video_capture_caps_ffmpeg_threads():
    # Needs an H.264 file: single-threaded codecs (GIF) clamp to 1 thread
    # whether capped or not, so only a threadable codec discriminates.
    if not hasattr(main.cv2, 'CAP_PROP_N_THREADS'):
        pytest.skip('this OpenCV build has no CAP_PROP_N_THREADS')
    mp4s = sorted(
        n for n in os.listdir(main.IMAGES_DIR) if n.lower().endswith('.mp4'))
    if not mp4s:
        pytest.skip('no .mp4 in images/ to open')
    cap = main.open_video_capture(os.path.join(main.IMAGES_DIR, mp4s[0]))
    try:
        assert cap.get(main.cv2.CAP_PROP_N_THREADS) == main.VIDEO_DECODE_THREADS
        assert cap.read()[0]  # the capped capture actually decodes
    finally:
        cap.release()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
