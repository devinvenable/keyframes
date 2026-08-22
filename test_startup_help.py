"""Headless tests for the startup help overlay state machine.

Run with SDL's dummy video driver so no window is needed:
    SDL_VIDEODRIVER=dummy python3 -m pytest test_startup_help.py
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


def _keydown(key, mod=0):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod)


# --- reshow-key detection --------------------------------------------------

def test_f1_is_reshow_key():
    assert main.is_help_reshow_key(_keydown(pygame.K_F1))


def test_question_is_reshow_key():
    assert main.is_help_reshow_key(_keydown(pygame.K_QUESTION))


def test_shift_slash_is_reshow_key():
    # `?` on most layouts is Shift + `/`.
    assert main.is_help_reshow_key(_keydown(pygame.K_SLASH, mod=pygame.KMOD_LSHIFT))


def test_plain_slash_is_not_reshow_key():
    assert not main.is_help_reshow_key(_keydown(pygame.K_SLASH))


def test_reshow_keys_are_not_piano_keys():
    # The whole point of intercepting F1/? ahead of KEY_TO_NOTE is that they
    # are not themselves playable notes.
    assert pygame.K_F1 not in main.KEY_TO_NOTE
    assert pygame.K_QUESTION not in main.KEY_TO_NOTE
    assert pygame.K_SLASH not in main.KEY_TO_NOTE


def test_piano_key_is_not_reshow_key():
    for key in main.KEY_TO_NOTE:
        assert not main.is_help_reshow_key(_keydown(key))


# --- show / dismiss / reshow transitions -----------------------------------

def test_dismiss_on_first_note():
    # Overlay is up at launch; the first note played hides it.
    show_help = True
    show_help = main.update_help_visibility(show_help, note_started=True)
    assert show_help is False


def test_no_input_keeps_overlay():
    # A frame with no input signal at all -> overlay stays up.
    show_help = True
    show_help = main.update_help_visibility(show_help, note_started=False)
    assert show_help is True


def test_any_key_dismisses():
    # Any key press hides the overlay, even a non-note key (space, a letter,
    # Tab). This is the fix for "pressing a key didn't dismiss it".
    show_help = True
    show_help = main.update_help_visibility(show_help, key_pressed=True)
    assert show_help is False


def test_reshow_wins_over_simultaneous_key():
    # F1/? is excepted from the any-key dismissal (it reshows instead).
    show_help = False
    show_help = main.update_help_visibility(show_help, reshow_key=True, key_pressed=True)
    assert show_help is True


def test_reshow_then_dismiss_again():
    # After dismissal, F1/? brings it back, and the next note dismisses again.
    show_help = False
    show_help = main.update_help_visibility(show_help, reshow_key=True)
    assert show_help is True
    show_help = main.update_help_visibility(show_help, note_started=True)
    assert show_help is False


def test_reshow_wins_over_simultaneous_note():
    # Reshow takes precedence: a reshow key never counts as a note.
    show_help = False
    show_help = main.update_help_visibility(show_help, reshow_key=True, note_started=True)
    assert show_help is True


def test_full_sequence_launch_dismiss_reshow():
    # End-to-end walk of the intended lifecycle.
    show_help = True                                              # launched showing
    assert show_help is True
    show_help = main.update_help_visibility(show_help, note_started=True)   # play a note
    assert show_help is False
    # further notes keep it hidden
    show_help = main.update_help_visibility(show_help, note_started=True)
    assert show_help is False
    # F1 reshows
    show_help = main.update_help_visibility(show_help, reshow_key=True)
    assert show_help is True
    # next note hides it once more
    show_help = main.update_help_visibility(show_help, note_started=True)
    assert show_help is False


# --- rendering smoke test --------------------------------------------------

def test_draw_startup_help_runs_headless():
    screen = pygame.display.get_surface()
    screen.fill((123, 45, 67))  # a distinctive "media" frame beneath the help
    # Should draw without raising and dim the frame (semi-transparent overlay
    # over the existing pixels, not a solid fill).
    main.draw_startup_help(screen, *screen.get_size())
    center = screen.get_at((screen.get_width() // 2, screen.get_height() // 2))
    # Dimmed toward black but text/panel present -> not the untouched frame.
    assert center != pygame.Color(123, 45, 67, 255)
