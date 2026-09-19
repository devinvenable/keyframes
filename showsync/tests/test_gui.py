from types import SimpleNamespace

from showsync.audio import AudioEngine
from showsync.gui import run, timestamp
from showsync.setlist import Setlist, Song
from showsync.tempomap import TempoEvent
from pathlib import Path


def test_dashboard_and_keyboard_transport(monkeypatch):
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    import pygame
    fixture = Path(__file__).parent / 'fixtures' / 'tone.wav'
    engine = AudioEngine(Setlist('stage test', (Song('Ambient', fixture, 120,
                                                  tempo=(TempoEvent(0, 140, .5),)),)))
    # A real pygame event loop, exercising pause, skip, and rendered ramp fields.
    original = pygame.event.get
    events = iter([[pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)],
                   [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_n)],
                   [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q)]])
    monkeypatch.setattr(pygame.event, 'get', lambda: next(events, []))
    run(engine, SimpleNamespace(error=None), max_frames=4)
    assert engine._requested == (True, 1, 1)
    assert timestamp(95.5) == '01:35'
