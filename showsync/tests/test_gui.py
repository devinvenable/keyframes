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
    events = iter([[pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)],
                   [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_n)],
                   [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q)]])
    monkeypatch.setattr(pygame.event, 'get', lambda: next(events, []))
    run(engine, SimpleNamespace(error=None), max_frames=4)
    assert engine._requested == (True, 1, 1)
    assert timestamp(95.5) == '01:35'


def test_setlist_panel_reorder_persists_and_restart_needs_confirm(monkeypatch):
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    import pygame
    fixture = Path(__file__).parent / 'fixtures' / 'tone.wav'
    songs = tuple(Song(name, fixture, bpm) for name, bpm in (('A', 120), ('B', 100), ('C', 90)))
    engine = AudioEngine(Setlist('stage test', songs))
    saved = []
    key = lambda k, mod=0: [pygame.event.Event(pygame.KEYDOWN, key=k, mod=mod)]
    events = iter([
        key(pygame.K_TAB),                            # open the setlist panel (selects song 2)
        key(pygame.K_DOWN),                           # select song 3
        key(pygame.K_UP, pygame.KMOD_SHIFT),          # move C before B
        key(pygame.K_UP, pygame.KMOD_SHIFT),          # refused: would land on the current song
        key(pygame.K_TAB),                            # close the panel
        key(pygame.K_r),                              # arms the confirm window only
        key(pygame.K_r),                              # confirmed restart
        key(pygame.K_q),
    ])
    monkeypatch.setattr(pygame.event, 'get', lambda: next(events, []))
    run(engine, SimpleNamespace(error=None),
        persist=lambda order: saved.append(tuple(order)), max_frames=10)
    assert engine.order == (0, 2, 1)
    assert saved == [(0, 2, 1)]
    assert [s.name for s in engine.setlist.songs] == ['A', 'C', 'B']
    assert engine._requested == (True, 1, 0)  # exactly one restart, queued to song 1
