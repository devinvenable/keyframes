"""Fault injection checks content progress, not merely a live render loop."""
import json
import os
from types import SimpleNamespace

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import numpy as np
import pygame
import pytest
import main


class Capture:
    def __init__(self, seek=False, broken=False):
        self.index = 0
        self.seek = seek
        self.broken = broken
        self.released = False

    def get(self, prop):
        return 10.0

    def read(self):
        if self.broken or self.index == 3:
            return False, None
        self.index += 1
        return True, np.full((4, 4, 3), self.index * 60, np.uint8)

    def grab(self):
        return self.read()[0]

    def set(self, *args):
        return self.seek  # even a successful seek can leave the decoder at EOF

    def release(self):
        self.released = True


@pytest.mark.parametrize('seek', [False, True])
def test_failed_loop_rewind_recovers_content(monkeypatch, seek):
    captures = []
    def open_cap(path):
        cap = Capture(seek=seek)
        captures.append(cap)
        return cap
    monkeypatch.setattr(main, 'open_video_capture', open_cap)
    now = [0.0]
    player = main.VideoPlayer('broken-seek.gif', (4, 4), loop=True, clock=lambda: now[0])
    pixels = []
    try:
        for i in range(40):
            now[0] = i * 0.11
            pixels.append(player.get_frame().get_at((0, 0))[0])
        assert len(set(pixels[-10:])) > 1
        assert not player.finished
        assert len(captures) > 1
        assert all(cap.released for cap in captures[:-1])
    finally:
        player.release()


def test_decode_exception_recovers_without_escaping_render(monkeypatch):
    monkeypatch.setattr(main, 'open_video_capture', lambda path: Capture())
    original = main.cv2.cvtColor
    count = [0]
    def poison(frame, code):
        count[0] += 1
        if count[0] == 2:
            raise RuntimeError('poisoned frame')
        return original(frame, code)
    monkeypatch.setattr(main.cv2, 'cvtColor', poison)
    now = [0.0]
    player = main.VideoPlayer('poison.gif', (4, 4), loop=True, clock=lambda: now[0])
    first = player.get_frame()
    now[0] = 0.11
    error = None
    try:
        held = player.get_frame()
    except Exception as exc:
        error = exc
        held = None
    assert error is None, f'decode exception escaped into render: {error}'
    assert held is first
    now[0] = 1.2
    player.get_frame()
    now[0] = 1.31
    assert player.get_frame().get_at((0, 0)) != first.get_at((0, 0))
    player.release()


def test_permanent_decode_failure_is_rate_limited(monkeypatch):
    calls = []
    def open_cap(path):
        calls.append(path)
        return Capture(broken=True)
    monkeypatch.setattr(main, 'open_video_capture', open_cap)
    now = [0.0]
    player = main.VideoPlayer('bad.gif', (4, 4), loop=True, clock=lambda: now[0])
    for i in range(300):
        now[0] = i / 60
        player.get_frame()
    assert 4 <= len(calls) <= 12
    assert not player.finished
    player.release()


def test_stagnation_reports_once_then_rearms_on_content_change(tmp_path):
    path = tmp_path / 'stall.log'
    sidecar = tmp_path / 'midi.jsonl'
    logger = main.MidiEventLogger(str(sidecar))
    watch = main.DisplayStagnationWatchdog(str(path), logger)
    player = SimpleNamespace(path='loop.gif', finished=False, loop=True)
    state = {'video_player': player, 'note_active': 55}
    screen = pygame.Surface((64, 36))
    for t in range(12):
        # New surface objects with identical pixels must still be detected.
        watch.observe(screen.copy(), state, t)
    assert path.exists(), 'stagnant displayed pixels were not reported'
    records = [json.loads(s) for s in path.read_text().splitlines()]
    assert len(records) == 1 and records[0]['stagnant_seconds'] > 5
    assert records[0]['path'] == 'loop.gif' and records[0]['note'] == 55
    screen.fill('red')
    for t in range(12, 20):
        watch.observe(screen, state, t)
    assert len(path.read_text().splitlines()) == 2
    logger.close()
    assert sum(json.loads(s).get('event') == 'display_stagnation'
               for s in sidecar.read_text().splitlines()) == 2


def test_stagnation_ignores_intentional_holds_and_resets_on_source_change(tmp_path):
    path = tmp_path / 'stall.log'
    watch = main.DisplayStagnationWatchdog(str(path))
    screen = pygame.Surface((64, 36))
    for state in ({}, {'video_player': SimpleNamespace(path='ended.mp4', finished=True, loop=False)},
                  {'active_scene': object()}):
        for t in range(10):
            watch.observe(screen, state, t)
    for t in range(10, 30):
        player = SimpleNamespace(path='new.gif', finished=False, loop=True)
        watch.observe(screen, {'video_player': player}, t)
    assert not path.exists()
