"""Regression guard for enable_all_events().

A previous change called pygame.event.set_blocked(None) intending to *unblock*
drop events, but that call blocks EVERY event type — it silently killed all
keyboard, mouse, and drop input. enable_all_events() must leave the core input
events (KEYDOWN, KEYUP, mouse, and the DROP family) unblocked.
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import main


def test_enable_all_events_unblocks_input():
    pygame.init()
    pygame.display.set_mode((1, 1))
    try:
        # Simulate the buggy state first, then repair with the helper.
        pygame.event.set_blocked(None)
        main.enable_all_events()
        for ev in (pygame.KEYDOWN, pygame.KEYUP,
                   pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                   pygame.MOUSEMOTION, pygame.DROPFILE):
            assert pygame.event.get_blocked(ev) is False, (
                f"{pygame.event.event_name(ev)} must not be blocked"
            )
    finally:
        pygame.quit()
