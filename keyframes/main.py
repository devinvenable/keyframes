import argparse
import ctypes
import json
import os
import queue
import random
import shutil
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import cv2
import numpy as np
import pygame
import mido

# Default note range for a 64-key keyboard
DEFAULT_START_NOTE = 36  # C2
DEFAULT_NUM_KEYS = 64

def get_application_dir():
    """Return the directory containing editable user files.

    PyInstaller extracts bundled files into ``sys._MEIPASS``, but Keyframes'
    media is intentionally *not* bundled.  A frozen app must therefore use the
    executable's directory, while a source checkout uses this file's directory.
    ``APP_DIR`` is also the location for future user-editable configuration.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = get_application_dir()
BUNDLE_DIR = Path(getattr(sys, '_MEIPASS', APP_DIR))
IMAGES_DIR = str(APP_DIR / 'images')
# Persistent note -> filename manifest, kept beside the exe and editable images/
# folder so it survives restarts and can be hand-edited.  Absent until the first
# launch (or the Media Manager) seeds it.
MAPPING_PATH = str(APP_DIR / 'mapping.json')
# Scene settings live in their OWN file, not mapping.json: save_mapping()
# rewrites mapping.json from the note->filename dict alone, so any config
# block stored there would be silently dropped on the first reconcile.
SCENES_CONFIG_PATH = str(APP_DIR / 'scenes.json')

IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.bmp')
# .gif is a video here: cv2's ffmpeg backend decodes GIFs frame-by-frame, so
# animated GIFs ride the whole VideoPlayer/thumbnail/interleave pipeline for
# free (transparency is flattened by cv2 — acceptable). A single-frame GIF
# takes the same path and simply displays its one frame. Unlike real videos,
# which freeze on their last frame while a note is held, LOOP_EXTS media
# rewinds and keeps playing for as long as the note is down.
VIDEO_EXTS = ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.gif')
LOOP_EXTS = ('.gif',)

# Computer keyboard -> MIDI note mapping (piano layout)
# Lower octave: Z-M = C3-B3, Upper octave: Q-P = C4-E5
# Sharps on S,D,G,H,J (lower) and 2,3,5,6,7,9,0 (upper)
KEY_TO_NOTE = {
    pygame.K_z: 48, pygame.K_s: 49, pygame.K_x: 50, pygame.K_d: 51,
    pygame.K_c: 52, pygame.K_v: 53, pygame.K_g: 54, pygame.K_b: 55,
    pygame.K_h: 56, pygame.K_n: 57, pygame.K_j: 58, pygame.K_m: 59,
    pygame.K_q: 60, pygame.K_2: 61, pygame.K_w: 62, pygame.K_3: 63,
    pygame.K_e: 64, pygame.K_r: 65, pygame.K_5: 66, pygame.K_t: 67,
    pygame.K_6: 68, pygame.K_y: 69, pygame.K_7: 70, pygame.K_u: 71,
    pygame.K_i: 72, pygame.K_9: 73, pygame.K_o: 74, pygame.K_0: 75,
    pygame.K_p: 76,
}

# Musical note lengths as fractions of a whole note
NOTE_LENGTHS = {
    'whole': 4.0, '1': 4.0,
    'half': 2.0, '1/2': 2.0,
    'quarter': 1.0, '1/4': 1.0,
    'eighth': 0.5, '1/8': 0.5,
    'sixteenth': 0.25, '1/16': 0.25,
    'thirtysecond': 0.125, '1/32': 0.125,
}

DEFAULT_BPM = 120
ZOOM_RING_SIZE = 16
ZOOM_RING_STEP = 0.03
LATCH_NOTICE_SECONDS = 1.5
# Pitch bend fully up (pitch 8191) zooms the displayed media to this scale;
# center and below is 1.0 (no zoom). Composes multiplicatively with the ring.
MAX_PITCH_BEND_ZOOM = 4.0
MOD_WHEEL_CC = 1
# Mod-wheel pan: full wheel deflection slides the displayed frame sideways by
# this fraction of the viewport width, at any zoom, revealing background at
# the vacated edge.
MAX_PAN_FRACTION = 0.40
# The KeyStep's mod strip sends nothing when the finger lifts, so pan cannot
# spring back on its own. After this much CC1 silence an off-center pan eases
# home over PAN_RECENTER_SECONDS; any new CC1 cancels the ease and takes over.
# Devin feel-tested and prefers the pan to STAY where he put it, so the
# auto-recenter is off; flip PAN_AUTO_RECENTER to re-enable the ease.
PAN_AUTO_RECENTER = False
PAN_RECENTER_DELAY = 0.4
PAN_RECENTER_SECONDS = 0.25

SIZE_PRESETS = {
    'hd': (1920, 1080),
    '4k': (3840, 2160),
    'tiktok': (1080, 1920),
    'tiktok-sm': (720, 1280),
    'square': (1080, 1080),
    'ig-story': (1080, 1920),
    'reel': (1080, 1350),
}


class MidiClockTracker:
    """Tracks MIDI clock messages (24 PPQ) to derive BPM in real time."""

    def __init__(self, fallback_bpm=DEFAULT_BPM):
        self.fallback_bpm = fallback_bpm
        self._clock_times = []
        self._bpm = None
        self._max_samples = 48  # 2 beats worth of clocks

    def tick(self):
        """Call on each MIDI clock message."""
        now = time.monotonic()
        self._clock_times.append(now)
        if len(self._clock_times) > self._max_samples:
            self._clock_times = self._clock_times[-self._max_samples:]
        if len(self._clock_times) >= 6:
            # Average interval over recent clocks
            intervals = [self._clock_times[i] - self._clock_times[i - 1]
                         for i in range(1, len(self._clock_times))]
            avg_interval = sum(intervals) / len(intervals)
            if avg_interval > 0:
                # 24 clocks per quarter note
                self._bpm = 60.0 / (avg_interval * 24)

    @property
    def bpm(self):
        return self._bpm if self._bpm else self.fallback_bpm

    def quarter_note_duration(self):
        """Duration of one quarter note in seconds."""
        return 60.0 / self.bpm

    def note_duration(self, note_length_beats):
        """Duration in seconds for a given note length (in quarter-note beats)."""
        return self.quarter_note_duration() * note_length_beats


def _blit_overlay_lines(screen, width, height, lines):
    """Blit a vertically-centered stack of ``(text, font, color)`` lines.

    Shared by the empty-folder screen and the startup/help overlay so both use
    the same centering and line-spacing."""
    y = height // 2 - len(lines) * 20
    for text, f, color in lines:
        if text:
            rendered = f.render(text, True, color)
            screen.blit(rendered, (width // 2 - rendered.get_width() // 2, y))
        y += f.get_height() + 8


def show_instructions(screen, width, height):
    """Display setup instructions when no media files are found."""
    screen.fill((20, 20, 20))
    font_large = pygame.font.SysFont(None, 48)
    font = pygame.font.SysFont(None, 32)

    lines = [
        ("Keyframes", font_large, (255, 255, 255)),
        ("", font, (180, 180, 180)),
        ("No media files found in the images/ folder.", font, (255, 180, 80)),
        ("", font, (180, 180, 180)),
        ("To get started:", font, (200, 200, 200)),
        ("  1. Drop images or videos into the images/ folder", font, (180, 180, 180)),
        ("     Supported: .png .jpg .jpeg .bmp .gif .mp4 .avi .mov .mkv .webm", font, (140, 140, 140)),
        ("  2. Restart this program", font, (180, 180, 180)),
        ("", font, (180, 180, 180)),
        ("Press ESC to quit.", font, (140, 140, 140)),
    ]

    _blit_overlay_lines(screen, width, height, lines)
    pygame.display.flip()

    # Wait for ESC or quit
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return


def draw_startup_help(screen, width, height):
    """Draw the semi-transparent startup/help overlay over the current frame.

    Lists the core controls plus how to bring this help back later. Unlike
    :func:`show_instructions` this does not fill the screen or flip — it dims
    the existing frame with a translucent layer so media stays faintly visible
    behind it (the main loop flips afterward). The caller shows it at launch and
    on F1/?, and hides it on the first note played."""
    font_large = pygame.font.SysFont(None, 48)
    font = pygame.font.SysFont(None, 32)
    font_small = pygame.font.SysFont(None, 26)

    dim = pygame.Surface((width, height), pygame.SRCALPHA)
    dim.fill((0, 0, 0, 205))
    screen.blit(dim, (0, 0))

    lines = [
        ("Keyframes", font_large, (255, 255, 255)),
        ("", font_small, (180, 180, 180)),
        ("Your computer keyboard is a piano:", font, (210, 210, 210)),
        ("  Z-M = lower octave    Q-P = upper octave", font_small, (180, 180, 180)),
        ("  Any mapped key triggers its image or video", font_small, (140, 140, 140)),
        ("", font_small, (180, 180, 180)),
        ("Tab    Grid manager: assign keys and replace media", font_small, (180, 180, 180)),
        ("L    Toggle latch mode (last hit stays on screen)", font_small, (180, 180, 180)),
        ("F11 or Alt+Enter   Toggle fullscreen / windowed", font_small, (180, 180, 180)),
        ("Esc    Quit", font_small, (180, 180, 180)),
        ("", font_small, (180, 180, 180)),
        ("Press any key to start playing.", font, (255, 220, 120)),
        ("Press F1 or ? anytime to show this help again.", font_small, (140, 185, 225)),
        ("Run with --help for more options (window size, MIDI channel, zoom ring, MIDI file)",
         font_small, (140, 185, 225)),
    ]
    _blit_overlay_lines(screen, width, height, lines)


def enable_all_events():
    """Allow every event type onto the queue.

    SDL ships with DROPTEXT/DROPBEGIN/DROPCOMPLETE disabled by default (only
    DROPFILE is on), so we need those text/uri-list drops and begin/complete
    diagnostics to arrive. The correct call is ``set_allowed(None)`` — note that
    ``set_blocked(None)`` does the OPPOSITE and blocks EVERY event (including
    KEYDOWN and DROPFILE), which silently kills all keyboard, mouse, and drop
    input. Kept as a named, tested helper so that trap can't be reintroduced."""
    pygame.event.set_allowed(None)


def is_help_reshow_key(event):
    """True if ``event`` (a KEYDOWN) is the reshow-help binding: F1 or ?.

    ``?`` arrives either as K_QUESTION or as Shift+K_SLASH depending on the
    platform/layout. None of these are piano keys (KEY_TO_NOTE), so the caller
    intercepts them ahead of note handling without stealing a playable key."""
    if event.key in (pygame.K_F1, pygame.K_QUESTION):
        return True
    if event.key == pygame.K_SLASH and (event.mod & pygame.KMOD_SHIFT):
        return True
    return False


def is_fullscreen_toggle_key(event):
    """True for the F11 and Alt+Enter fullscreen/windowed bindings."""
    return (event.key == pygame.K_F11
            or (event.key == pygame.K_RETURN and event.mod & pygame.KMOD_ALT))


def update_help_visibility(show_help, *, reshow_key=False, note_started=False,
                           key_pressed=False):
    """Return the help-overlay visibility after one input.

    Reshow (F1/?) wins and shows the overlay; otherwise ANY key press
    (``key_pressed``) or the first note played (a KEY_TO_NOTE press or an
    incoming MIDI note, ``note_started``) hides it. Called from the main loop
    for the keyboard, any-key, and live-MIDI paths. Dismissing on any key —
    not just playable notes — matches "press any key to continue" and avoids
    depending on the note being mapped or the note plumbing being reached."""
    if reshow_key:
        return True
    if note_started or key_pressed:
        return False
    return show_help


def toggle_latch_mode(latch_enabled):
    """Return the opposite of the current note-release mode."""
    return not latch_enabled


def inverted_surface(media):
    """Return a cached colour-inverted (XOR/negative) copy of an image media.

    Inversion is a white BLEND_RGB_SUB (255 - rgb), leaving alpha intact. Cached
    on the media dict so repeated same-note hits just swap surfaces — no
    per-frame cost. Used to flash a still to its negative on a same-note repeat
    instead of the old black strobe (video is left alone; it restarts on retrigger)."""
    inv = media.get('surface_inverted')
    if inv is None:
        src = media['surface']
        inv = pygame.Surface(src.get_size(), pygame.SRCALPHA)
        inv.fill((255, 255, 255, 255))
        # white - src (per RGB channel) = 255 - rgb, i.e. the colour negative.
        inv.blit(src, (0, 0), special_flags=pygame.BLEND_RGB_SUB)
        media['surface_inverted'] = inv
    return inv


def list_media_files():
    """Return the media filenames currently present in ``images/`` (unordered)."""
    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR)
    return [f for f in os.listdir(IMAGES_DIR)
            if f.lower().endswith(IMAGE_EXTS + VIDEO_EXTS)]


def order_media_files(all_files):
    """Sort images, then interleave videos evenly among them.

    This is the historical spread that keeps videos from clumping at one end of
    the note range; the seed distribution below relies on it."""
    images = sorted(f for f in all_files if f.lower().endswith(IMAGE_EXTS))
    videos = sorted(f for f in all_files if f.lower().endswith(VIDEO_EXTS))

    media_files = list(images)
    if videos:
        interval = max(1, len(media_files) // (len(videos) + 1))
        for vi, v in enumerate(videos):
            insert_pos = min(interval * (vi + 1) + vi, len(media_files))
            media_files.insert(insert_pos, v)
    return media_files


def seed_distribution(ordered_files, start_note, end_note):
    """Seed each file onto one distinct note, in media order."""
    return {note: name for note, name in zip(range(start_note, end_note + 1),
                                             ordered_files)}


def load_mapping(path=None):
    """Read the persistent note -> filename manifest.

    Returns a ``{int note: str filename}`` dict, or ``{}`` if the file is
    missing or unreadable.  Malformed entries are skipped rather than fatal so a
    hand-edit typo never bricks startup.  This is the single loader the
    replace/rearrange features share."""
    if path is None:
        path = MAPPING_PATH
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            raw = json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    mapping = {}
    for note, filename in raw.items():
        try:
            note_int = int(note)
        except (TypeError, ValueError):
            continue
        if isinstance(filename, str):
            mapping[note_int] = filename
    return mapping


def save_mapping(mapping, path=None):
    """Write the note -> filename manifest as human-readable JSON.

    Keys are stored as strings (JSON has no int keys) and sorted numerically so
    the file diffs cleanly and hand-edits stay legible.  Written atomically via a
    temp file so an interrupted write can't corrupt the manifest.  This is the
    single writer the replace/rearrange features share."""
    if path is None:
        path = MAPPING_PATH
    ordered = {str(note): mapping[note] for note in sorted(mapping)}
    tmp = f"{path}.tmp"
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(ordered, fh, indent=2)
        fh.write('\n')
    os.replace(tmp, path)


def reconcile_mapping(stored, present_files, start_note, end_note, *, seed=False,
                      new_files=None):
    """Reconcile the media folder into a sparse, exclusive 1:1 mapping."""
    present = set(present_files)
    result, used_names = {}, set()
    for note in sorted(stored):
        name = stored[note]
        if (start_note <= note <= end_note and name in present
                and name not in used_names):
            result[note] = name
            used_names.add(name)
    if seed:
        candidates = seed_distribution(order_media_files(present_files),
                                       start_note, end_note).items()
    else:
        free_notes = (note for note in range(start_note, end_note + 1)
                      if note not in result)
        candidates = ((next(free_notes, None), name)
                      for name in order_media_files(
                          present_files if new_files is None else new_files)
                      if name not in used_names)
    for note, name in candidates:
        if note is None or name in used_names or note in result:
            continue
        result[note] = name
        used_names.add(name)
    return result


def assign_mapping(mapping, note, filename):
    """Assign one note to one filename, stealing both prior assignments."""
    result = {n: name for n, name in mapping.items()
              if n != note and name != filename}
    result[note] = filename
    return result


def unmap_mapping(mapping, filename):
    """Remove a filename's mapping while leaving its media file intact."""
    return {note: name for note, name in mapping.items() if name != filename}


def make_media_entry(name):
    """Build a single note-media object for a filename in ``images/``.

    Carries a ``name`` field so the live click-to-replace path can find and
    reuse an already-loaded object for the same file (preserving the grid's
    id()-based dedup) instead of decoding it a second time."""
    filepath = os.path.join(IMAGES_DIR, name)
    ext = os.path.splitext(name)[1].lower()
    if ext in VIDEO_EXTS:
        return {'type': 'video', 'path': filepath, 'name': name,
                'loop': ext in LOOP_EXTS}
    img = pygame.image.load(filepath).convert_alpha()
    return {'type': 'image', 'surface': img, 'name': name}


def load_media(start_note, end_note):
    """Build the note -> media mapping, honoring the persistent manifest.

    The manifest is sparse: each media file has at most one note and unmapped
    files remain visible in the grid but do not trigger playback."""
    all_files = list_media_files()
    if not all_files:
        return None

    manifest_exists = os.path.exists(MAPPING_PATH)
    stored = load_mapping()
    new_files = all_files
    if manifest_exists:
        manifest_mtime = os.path.getmtime(MAPPING_PATH)
        new_files = [name for name in all_files
                     if os.path.getmtime(os.path.join(IMAGES_DIR, name)) > manifest_mtime]
    reconciled = reconcile_mapping(stored, all_files, start_note, end_note,
                                   seed=not manifest_exists, new_files=new_files)
    if reconciled != stored:
        save_mapping(reconciled)

    # Only notes inside the active range drive playback; out-of-range entries are
    # preserved in the file but not loaded here.
    in_range = {note: name for note, name in reconciled.items()
                if start_note <= note <= end_note}

    # A mapping is 1:1, but cache objects by filename for live reassignment.
    media_by_file = {}
    for name in set(in_range.values()):
        media_by_file[name] = make_media_entry(name)

    note_to_media = {note: media_by_file[name] for note, name in in_range.items()}

    num_files = len(media_by_file)
    num_videos = sum(1 for m in media_by_file.values() if m['type'] == 'video')
    print(f"Loaded {num_files} media files ({num_videos} videos), mapped across notes {start_note}-{end_note}")
    print(f"Video notes: {sorted(n for n, m in note_to_media.items() if m['type'] == 'video')}")
    return note_to_media



def choose_landscape_display():
    """
    Find a display that is in landscape orientation (width > height).
    If multiple displays are landscape, pick the first one.
    """
    desktop_sizes = pygame.display.get_desktop_sizes()

    for i, (w, h) in enumerate(desktop_sizes):
        if w > h:
            return i, w, h

    return 0, desktop_sizes[0][0], desktop_sizes[0][1]


def parse_window_size(size):
    """Resolve a ``--size`` value to concrete window dimensions."""
    if size.lower() in SIZE_PRESETS:
        return SIZE_PRESETS[size.lower()]
    return tuple(int(d) for d in size.split('x'))


def update_display_target_size(state, width, height):
    """Return the current render target and retarget an active video player."""
    target_size = (width, height)
    if state.get('video_player'):
        state['video_player'].target_size = target_size
    return target_size


def set_display_mode(fullscreen, windowed_size, state):
    """Create the requested display mode and update the active render target.

    ``pygame.display.toggle_fullscreen()`` is unreliable on several backends,
    so every transition explicitly recreates the display surface instead.
    """
    if fullscreen:
        # SDL iconifies a fullscreen window the moment it loses focus, so the
        # first click on any other window (the ShowSync editor, a terminal)
        # would MINIMIZE Keyframes — always-on-top can't reveal an iconified
        # window. SDL re-reads this hint from the environment on each focus
        # loss, so setting it here covers windows created earlier too.
        os.environ['SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS'] = '0'
        display_index, display_w, display_h = choose_landscape_display()
        flags = pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF
        screen = pygame.display.set_mode((display_w, display_h), flags,
                                         display=display_index)
        pygame.mouse.set_visible(False)
    else:
        display_w, display_h = windowed_size
        screen = pygame.display.set_mode((display_w, display_h), pygame.RESIZABLE)
        pygame.mouse.set_visible(True)
    # Fullscreen is the performance/reveal layer under the ShowSync projector,
    # so it must stay above ordinary windows; a windowed toggle stacks normally.
    set_window_always_on_top(fullscreen)
    target_size = update_display_target_size(state, display_w, display_h)
    return screen, display_w, display_h, target_size


def play_midi_file(filepath, msg_queue, stop_event, loop=False):
    """Play a MIDI file in a background thread, pushing MIDI messages to a queue."""
    midi_file = mido.MidiFile(filepath)
    print(f"Playing MIDI file: {filepath} ({midi_file.length:.1f}s)")
    while not stop_event.is_set():
        for msg in midi_file.play():
            if stop_event.is_set():
                return
            if msg.type in ('note_on', 'note_off', 'clock'):
                msg_queue.put(msg)
        if not loop:
            break
    print("MIDI file playback finished.")


# Upper bound on frames consumed (grabbed, not rendered) in one get_frame()
# call to catch up after a render stall. Past this the player resyncs and
# plays on from where it is: a burst of decode work would steal CPU from the
# audio graph, which is the exact failure pacing exists to prevent.
MAX_DECODE_CATCHUP = 5

# FFmpeg decode threads per open stream. Left alone, a 1080p H.264 open
# spawns a frame-thread pool larger than nproc (11 threads on the 6-core
# perform host) that competes with ShowSync's audio graph (canon midi:I39).
# CAP_PROP_N_THREADS as an open-parameter is honored by this OpenCV build
# (the OPENCV_FFMPEG_CAPTURE_OPTIONS env knob is NOT). With decode paced to
# media fps, 2 threads decode 1080p comfortably.
VIDEO_DECODE_THREADS = 2


def open_video_capture(path):
    """Open a video with a capped FFmpeg decode-thread pool when supported."""
    if hasattr(cv2, 'CAP_PROP_N_THREADS'):
        try:
            cap = cv2.VideoCapture(path, cv2.CAP_FFMPEG,
                                   [cv2.CAP_PROP_N_THREADS,
                                    VIDEO_DECODE_THREADS])
            if cap.isOpened():
                return cap
            cap.release()
        except cv2.error:
            pass
    return cv2.VideoCapture(path)


def make_step_clock(step, start=0.0):
    """A fake monotonic clock advancing ``step`` seconds per call.

    For tests and the packaging smoke test, where frames must be due on
    every get_frame() call regardless of real elapsed time."""
    state = [start]

    def clock():
        state[0] += step
        return state[0]

    return clock


class VideoPlayer:
    """Manages video playback for a single video file.

    Decoding is paced by the media's own frame rate, not by the caller's
    render loop: get_frame() decodes a new frame only when one is due by the
    wall clock (``clock``, injectable for tests), returning the previous
    surface otherwise. Media faster than the render loop is kept real-time by
    grab()-skipping the frames that will never be shown. Streams that don't
    report a frame rate fall back to one decode per call."""

    def __init__(self, path, target_size, loop=False, clock=time.monotonic,
                 display_mode='fill'):
        self.path = path
        self.target_size = target_size
        self.loop = loop
        self.display_mode = display_mode
        self.clock = clock
        self.cap = open_video_capture(path)
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.fps = fps if fps and fps > 0 else 0  # 0 = unknown, decode unpaced
        self.last_surface = None
        self.finished = False
        self._next_frame_due = None

    def _consume_frame(self):
        """Advance one frame without rendering it; rewind a looping stream."""
        if self.cap.grab():
            return True
        if self.loop:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            return self.cap.grab()
        return False

    def get_frame(self):
        """Return the frame due now as a pygame surface.

        At end-of-stream a looping player (animated GIFs) rewinds and keeps
        playing; a non-looping one freezes on its last frame."""
        if self.finished:
            return self.last_surface

        if self.fps:
            now = self.clock()
            if self._next_frame_due is None:
                self._next_frame_due = now
            if now < self._next_frame_due and self.last_surface is not None:
                return self.last_surface
            interval = 1.0 / self.fps
            # Behind by more than one frame (media fps > render rate, or a
            # stall): consume the frames that will never be shown, capped.
            skip = max(0, min(int((now - self._next_frame_due) / interval),
                              MAX_DECODE_CATCHUP))
            for _ in range(skip):
                if not self._consume_frame():
                    break
            self._next_frame_due += (skip + 1) * interval
            if self._next_frame_due < now:
                # Still behind after the capped catch-up — resync rather than
                # accumulate decode debt.
                self._next_frame_due = now + interval

        ret, frame = self.cap.read()
        if not ret and self.loop:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.cap.read()
        if not ret:
            # Video ended (or the loop rewind failed) — freeze on last frame
            self.finished = True
            return self.last_surface

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        th, tw = self.target_size[1], self.target_size[0]
        fh, fw = frame.shape[:2]
        if self.display_mode == 'fit':
            # Fit: scale to sit inside target, centered on black bars
            scale = min(tw / fw, th / fh)
            new_w = max(1, int(round(fw * scale)))
            new_h = max(1, int(round(fh * scale)))
            frame = cv2.resize(frame, (new_w, new_h))
            canvas = np.zeros((th, tw, 3), dtype=frame.dtype)
            x_off = (tw - new_w) // 2
            y_off = (th - new_h) // 2
            canvas[y_off:y_off+new_h, x_off:x_off+new_w] = frame
            frame = canvas
        else:
            # Crop-to-fill: scale to cover target, then center-crop
            src_ratio = fw / fh
            tgt_ratio = tw / th
            if src_ratio > tgt_ratio:
                new_h = th
                new_w = int(fw * th / fh)
            else:
                new_w = tw
                new_h = int(fh * tw / fw)
            frame = cv2.resize(frame, (new_w, new_h))
            x_off = (new_w - tw) // 2
            y_off = (new_h - th) // 2
            frame = frame[y_off:y_off+th, x_off:x_off+tw]
        surface = pygame.surfarray.make_surface(np.transpose(frame, (1, 0, 2)))
        self.last_surface = surface
        return surface

    def release(self):
        if self.cap:
            self.cap.release()
            self.cap = None


def get_zoom_ring_scale(note, note_hit_counts, enabled):
    """Return the current zoom scale for a note and advance its ring position."""
    if not enabled:
        return 1.0

    hit_index = note_hit_counts.get(note, 0)
    note_hit_counts[note] = (hit_index + 1) % ZOOM_RING_SIZE
    return 1.0 + (hit_index * ZOOM_RING_STEP)


def pitch_bend_zoom_scale(pitch, max_zoom=MAX_PITCH_BEND_ZOOM):
    """Map a pitchwheel value (-8192..8191) to a live zoom scale.

    Center and below (pitch <= 0, where a sprung wheel rests) is 1.0; upward
    bend maps continuously to 1.0..``max_zoom`` so releasing the bend returns
    the media to normal size. No quantization — every message applies."""
    if pitch <= 0:
        return 1.0
    return 1.0 + (min(pitch, 8191) / 8191.0) * (max_zoom - 1.0)


def mod_wheel_pan(value):
    """Map a mod-wheel CC1 value (0..127) to a horizontal pan in -1.0..1.0.

    Bipolar around 64: 64 is centered, 0 is full left shift, 127 full right.
    The halves are normalized separately so both extremes reach exactly ±1.0
    despite the range being asymmetric around 64. This is the ONE place the
    wheel-to-pan mapping lives — changing the feel means changing only this
    function."""
    v = max(0, min(value, 127))
    if v >= 64:
        return (v - 64) / 63.0
    return (v - 64) / 64.0


def update_pan_recenter(current_state, now):
    """Ease an off-center pan back to 0 after CC1 goes silent.

    Called once per frame. The KeyStep's mod strip stops sending the moment
    the finger lifts (no spring, no release message), so after
    PAN_RECENTER_DELAY seconds without a CC1 the pan glides home over
    PAN_RECENTER_SECONDS using smoothstep — a drift, not a jump. Any new CC1
    clears 'pan_ease' in process_midi_messages, cancelling the ease mid-glide.
    Accepted trade-off: an off-center framing cannot be held."""
    pan = current_state.get('pan', 0.0)
    if pan == 0.0:
        current_state['pan_ease'] = None
        return
    ease = current_state.get('pan_ease')
    if ease is None:
        last_cc = current_state.get('pan_cc_time')
        if last_cc is None or now - last_cc >= PAN_RECENTER_DELAY:
            current_state['pan_ease'] = {'start': now, 'from': pan}
        return
    t = (now - ease['start']) / PAN_RECENTER_SECONDS
    if t >= 1.0:
        current_state['pan'] = 0.0
        current_state['pan_ease'] = None
        return
    s = t * t * (3.0 - 2.0 * t)
    current_state['pan'] = ease['from'] * (1.0 - s)


def crop_to_fill(surface, target_size):
    """Scale surface to cover target_size, cropping edges to preserve aspect ratio."""
    sw, sh = surface.get_size()
    tw, th = target_size
    src_ratio = sw / sh
    tgt_ratio = tw / th
    if src_ratio > tgt_ratio:
        # Source is wider — scale by height, crop width
        new_h = th
        new_w = int(sw * th / sh)
    else:
        # Source is taller — scale by width, crop height
        new_w = tw
        new_h = int(sh * tw / sw)
    scaled = pygame.transform.smoothscale(surface, (new_w, new_h))
    x_offset = (new_w - tw) // 2
    y_offset = (new_h - th) // 2
    cropped = scaled.subsurface((x_offset, y_offset, tw, th)).copy()
    return cropped


def fit_to_screen(surface, target_size):
    """Scale surface to fit entirely inside target_size, preserving aspect ratio.
    The result is a target_size surface with the media centered on black
    letterbox/pillarbox bars."""
    sw, sh = surface.get_size()
    tw, th = target_size
    scale = min(tw / sw, th / sh)
    new_w = max(1, int(round(sw * scale)))
    new_h = max(1, int(round(sh * scale)))
    scaled = pygame.transform.smoothscale(surface, (new_w, new_h))
    result = pygame.Surface(target_size)
    result.blit(scaled, ((tw - new_w) // 2, (th - new_h) // 2))
    return result


def zoom_surface_to_screen(surface, target_size, zoom_scale, display_mode='fill',
                           pan=0.0):
    """Scale a surface to the target area, optionally enlarging from center.
    In 'fit' mode the zoom enlarges the letterboxed frame, so the media may
    overflow into its own bars.

    ``pan`` (-1.0..1.0) slides the whole displayed frame sideways by up to
    MAX_PAN_FRACTION of the viewport width — at ANY zoom, including 1.0 —
    with black background showing at the vacated edge. Positive pan slides
    the frame right. Composes with zoom: the slide is measured in viewport
    pixels, so the gesture feels the same zoomed in or out."""
    if display_mode == 'fit':
        fitted = fit_to_screen(surface, target_size)
    else:
        fitted = crop_to_fill(surface, target_size)
    pan = max(-1.0, min(pan, 1.0))
    zoom_scale = max(1.0, zoom_scale)
    if zoom_scale == 1.0 and pan == 0.0:
        return fitted

    # Zoom by cropping the visible window out of the fitted frame and scaling
    # it UP to the target, rather than scaling the whole frame up by zoom and
    # cropping. Same center-anchored result, but the smoothscale output is one
    # target-size surface instead of zoom^2 times that — at 4x on 1080p that's
    # the difference between ~8ms and ~136ms per bend change, i.e. between a
    # smooth pitch-bend gesture and a slideshow. Pan only ever moves the crop
    # origin (and the blit position where the frame leaves the viewport) —
    # never the amount scaled.
    tw, th = target_size
    fw, fh = fitted.get_size()
    win_w = max(1, int(round(fw / zoom_scale)))
    win_h = max(1, int(round(fh / zoom_scale)))
    # Sliding the frame right by shift_out viewport pixels is the same as
    # sliding the source window left by the equivalent source pixels.
    shift_out = pan * MAX_PAN_FRACTION * tw
    shift_src = shift_out * win_w / tw
    x0 = (fw - win_w) / 2.0 - shift_src
    y_offset = (fh - win_h) // 2
    visible_x0 = max(0.0, x0)
    visible_x1 = min(float(fw), x0 + win_w)
    result = pygame.Surface(target_size)  # black where the frame slid away
    if visible_x1 > visible_x0:
        src_x = int(round(visible_x0))
        src_w = max(1, min(fw - src_x, int(round(visible_x1 - visible_x0))))
        window = fitted.subsurface((src_x, y_offset, src_w, win_h))
        scale = tw / win_w
        out_x = int(round((visible_x0 - x0) * scale))
        out_w = max(1, int(round(src_w * scale)))
        result.blit(pygame.transform.smoothscale(window, (out_w, th)), (out_x, 0))
    return result


def effective_zoom_scale(current_state):
    """The zoom-ring scale composed (multiplied) with the live pitch bend."""
    return current_state['zoom_scale'] * current_state.get('bend_zoom', 1.0)


def render_still(current_state, surface, target_size, zoom, display_mode, pan):
    """zoom_surface_to_screen for a latched still, cached until inputs change.

    Stills redraw every frame so bend/pan apply live, but a 4x smoothscale of
    a screen-sized surface is far too slow to repeat 60x/s when nothing moved.
    One-entry cache keyed on everything that affects the pixels; any bend, pan,
    ring, resize, invert, or mode change re-renders once and then holds."""
    key = (id(surface), target_size, zoom, display_mode, pan)
    cached = current_state.get('still_render')
    if cached and cached[0] == key:
        return cached[1]
    scaled = zoom_surface_to_screen(surface, target_size, zoom, display_mode, pan)
    current_state['still_render'] = (key, scaled)
    return scaled


# --- Scenes: reusable templated playback sequences ---------------------------

# Chance that any media-triggering note-on hands presentation to a scene.
DEFAULT_SCENE_PROBABILITY = 0.05
# Seconds a four-bar-sweep bar takes to fade out once its successor lands.
SCENE_FADE_SECONDS = 1.0


def load_scenes_config(path=None):
    """Read scenes.json, tolerating a missing or malformed file.

    Returns ``{'enabled': bool, 'probability': float}`` with defaults filled
    in, so callers never need to re-validate. Out-of-range probabilities and
    wrong-typed values fall back to the defaults rather than erroring — a
    hand-edit typo must not brick startup, matching load_mapping()."""
    if path is None:
        path = SCENES_CONFIG_PATH
    config = {'enabled': True, 'probability': DEFAULT_SCENE_PROBABILITY}
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            raw = json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return config
    if not isinstance(raw, dict):
        return config
    if isinstance(raw.get('enabled'), bool):
        config['enabled'] = raw['enabled']
    probability = raw.get('probability')
    if (isinstance(probability, (int, float)) and not isinstance(probability, bool)
            and 0.0 <= probability <= 1.0):
        config['probability'] = float(probability)
    return config


def media_still_surface(media):
    """A representative still surface for any media: images as-is, videos by
    their current-position/first frame. Scenes present stills only in v1, so a
    video trigger contributes one frame rather than full playback. Returns
    None if a video can't be decoded (the scene then simply doesn't start)."""
    if media['type'] == 'image':
        return media['surface']
    cap = open_video_capture(media['path'])
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return None
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return pygame.surfarray.make_surface(np.transpose(frame, (1, 0, 2)))


class Scene:
    """Base class for scenes — pre-configured, reusable playback templates
    that occasionally take over presentation from the normal full-screen view.

    Lifecycle: constructed on the activating trigger with that media's still
    surface; ``advance()`` on every later media-triggering note-on (Keyframes
    is note-driven, so a "beat" is a trigger, not clock time); ``render()``
    each frame while active; ``done()`` True once finished, after which the
    main loop drops it and normal full-screen behavior resumes. Scene state
    stays out of the main render path except via the single
    ``current_state['active_scene']`` hook."""

    name = 'scene'

    def __init__(self, image, now, background=None):
        self.image = image
        self.activated_at = now
        # Still of whatever was on screen when the scene activated (None if
        # nothing was displayed). Scenes that composite "new over old" use it;
        # single-image scenes like the sweeps simply ignore it.
        self.background = background

    def advance(self, media, now):
        """React to the next note-on trigger while active."""

    def render(self, screen, target_size, now):
        raise NotImplementedError

    def done(self, now):
        return False


# name -> Scene subclass; activation picks randomly among registered scenes.
SCENE_REGISTRY = {}


def register_scene(cls):
    SCENE_REGISTRY[cls.name] = cls
    return cls


def scene_bar_rect(index, target_size, num_bars=4):
    """Rect (x, y, w, h) of one full-height vertical bar.

    The last bar absorbs the division remainder so the bars always tile the
    full screen width with no uncovered right edge."""
    tw, th = target_size
    base = tw // num_bars
    x = index * base
    w = base if index < num_bars - 1 else tw - x
    return x, 0, w, th


@register_scene
class FourBarSweepScene(Scene):
    """The same image steps across 4 full-height vertical bars, one per beat.

    Activation shows the activating note's image in bar 1; each following
    trigger places it in the next bar and starts the previous bar's ~1s fade
    to FADE_COLOR (fades keep running across later steps). Each bar shows a
    center crop-to-fill of the image at the bar's aspect — cropped, never
    squeezed — multiplied by that bar's BAR_TINTS entry when one is set.
    The trigger after bar 4 starts the final fade; the scene is done when
    that last fade completes.

    FADE_COLOR and BAR_TINTS are the template parameters: subclasses override
    them to register sweep variants without duplicating the mechanics."""

    name = 'four-bar-sweep'
    NUM_BARS = 4
    FADE_SECONDS = SCENE_FADE_SECONDS
    FADE_COLOR = (255, 255, 255)
    # Per-bar RGB multiplied over the bar's crop (None = untinted). Applied on
    # every activation to any source image — never gated on grayscale.
    BAR_TINTS = None

    def __init__(self, image, now, background=None):
        super().__init__(image, now, background)
        self.bars_placed = 1
        self.fade_starts = {}  # bar index -> monotonic time its fade began
        self.finishing = False
        self._bar_cache = {}  # (size, tint) -> cropped (and tinted) bar surface

    def advance(self, media, now):
        if self.finishing:
            return
        if self.bars_placed < self.NUM_BARS:
            self.fade_starts[self.bars_placed - 1] = now
            self.bars_placed += 1
        else:
            self.fade_starts[self.NUM_BARS - 1] = now
            self.finishing = True

    def done(self, now):
        return (self.finishing
                and now - self.fade_starts[self.NUM_BARS - 1] >= self.FADE_SECONDS)

    def bar_tint(self, index):
        """This bar's tint RGB, or None. Tints cycle if the list is short."""
        if not self.BAR_TINTS:
            return None
        return self.BAR_TINTS[index % len(self.BAR_TINTS)]

    def bar_surface(self, size, index=0):
        """The image center-cropped-to-fill at one bar's size, with the bar's
        tint multiplied in, cached by (size, tint): every bar shows the SAME
        image, so one crop serves all equal-width bars sharing a tint."""
        tint = self.bar_tint(index)
        key = (size, tint)
        cached = self._bar_cache.get(key)
        if cached is None:
            cached = crop_to_fill(self.image, size)
            if tint is not None:
                overlay = pygame.Surface(cached.get_size())
                overlay.fill(tint)
                cached = cached.copy()
                cached.blit(overlay, (0, 0),
                            special_flags=pygame.BLEND_MULT)
            self._bar_cache[key] = cached
        return cached

    def fade_strength(self, index, now):
        """0.0 (full image) .. 1.0 (solid FADE_COLOR) for one bar's fade."""
        start = self.fade_starts.get(index)
        if start is None:
            return 0.0
        return min(max((now - start) / self.FADE_SECONDS, 0.0), 1.0)

    def render(self, screen, target_size, now):
        screen.fill((0, 0, 0))
        for i in range(self.bars_placed):
            x, y, w, h = scene_bar_rect(i, target_size, self.NUM_BARS)
            screen.blit(self.bar_surface((w, h), i), (x, y))
            strength = self.fade_strength(i, now)
            if strength > 0.0:
                overlay = pygame.Surface((w, h), pygame.SRCALPHA)
                overlay.fill(self.FADE_COLOR
                             + (int(round(255 * strength)),))
                screen.blit(overlay, (x, y))


@register_scene
class FourBarSweepBlackScene(FourBarSweepScene):
    """Four-bar sweep whose bars fade to black instead of white."""

    name = 'four-bar-sweep-black'
    FADE_COLOR = (0, 0, 0)


@register_scene
class FourBarSweepTintedScene(FourBarSweepScene):
    """Four-bar sweep with a per-bar color tint multiplied over each bar's
    crop — duotone on B&W sources, a palette shift on color ones. Bar 4 stays
    untinted as the natural-image payoff. Fades to white like the original."""

    name = 'four-bar-sweep-tinted'
    BAR_TINTS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), None)


@register_scene
class ConcentricRingsScene(Scene):
    """Expanding concentric rings (dartboard) mask between two images.

    Even rings show the FOREGROUND (the activating trigger's still), odd rings
    the BACKGROUND (whatever was on screen at activation — the new image
    tunnels in through the old; black if nothing was displayed). Rings expand
    outward continuously on wall-clock time: existing rings grow past the
    screen edge while new ones are born at center, reading as motion INTO the
    scene. Each note-on beat swaps foreground/background for a punchy per-beat
    inversion. Exit: the scene ends ON its BEATS_TO_LIVE-th beat — a hard cut
    to that trigger's media full-screen (normal state kept updating
    underneath), so the cut itself is the final punch; no extra fade.

    Rendering precomputes per screen size a quantized center-distance field
    and both stills cropped-to-fill; each frame derives the ring-parity mask
    with a couple of integer numpy ops, writes it into the foreground's alpha
    channel, and lets two SDL blits composite — no per-frame pygame circle
    drawing, crops, or full np.where (~8ms/frame at 1080p).

    RING_THICKNESS_FRACTION / EXPANSION_SPEED_FRACTION (both of screen
    height) and BEATS_TO_LIVE are the template parameters, defaults tuned by
    eye later."""

    name = 'concentric-rings'
    RING_THICKNESS_FRACTION = 0.1   # ring width, as a fraction of screen height
    EXPANSION_SPEED_FRACTION = 0.5  # screen-heights per second of outward growth
    BEATS_TO_LIVE = 8

    def __init__(self, image, now, background=None):
        super().__init__(image, now, background)
        self.beats = 0
        self.swapped = False
        self._cache = {}  # target_size -> (dist_q, fg_surface, bg_surface)

    def advance(self, media, now):
        self.beats += 1
        self.swapped = not self.swapped

    def done(self, now):
        return self.beats >= self.BEATS_TO_LIVE

    def ring_thickness(self, target_size):
        return max(1.0, target_size[1] * self.RING_THICKNESS_FRACTION)

    def ring_cache(self, target_size):
        """(dist_q, fg_surface, bg_surface) for one screen size, cached.

        dist_q is the (w, h) center-distance field pre-divided by the ring
        thickness and scaled by 256 as int32, so the per-frame ring index is
        a subtract and an arithmetic shift. fg is the activating still
        crop_to_fill'ed with a writable per-pixel alpha channel (the mask);
        bg is the previous view's still, or solid black when there was none."""
        cached = self._cache.get(target_size)
        if cached is None:
            tw, th = target_size
            xs = np.arange(tw, dtype=np.float32) - (tw - 1) / 2.0
            ys = np.arange(th, dtype=np.float32) - (th - 1) / 2.0
            dist = np.hypot(xs[:, None], ys[None, :])
            dist_q = (dist * (256.0 / self.ring_thickness(target_size))
                      ).astype(np.int32)
            fg = pygame.Surface(target_size, pygame.SRCALPHA)
            fg.blit(crop_to_fill(self.image, target_size), (0, 0))
            bg = pygame.Surface(target_size)
            if self.background is not None:
                bg.blit(crop_to_fill(self.background, target_size), (0, 0))
            cached = (dist_q, fg, bg)
            self._cache[target_size] = cached
        return cached

    def render(self, screen, target_size, now):
        dist_q, fg, bg = self.ring_cache(target_size)
        offset = ((now - self.activated_at)
                  * target_size[1] * self.EXPANSION_SPEED_FRACTION)
        offset_q = int(round(offset * 256.0 / self.ring_thickness(target_size)))
        # Ring parity by floor((dist - offset) / thickness) & 1, all in scaled
        # integers (>> 8 floors, so the negative indices under the center —
        # the new rings being born — alternate correctly too). The growing
        # offset pushes every ring boundary outward.
        parity = (dist_q - offset_q) >> 8
        parity &= 1
        if not self.swapped:
            parity ^= 1  # even rings carry the foreground
        alpha = parity.astype(np.uint8)
        alpha *= 255
        pygame.surfarray.pixels_alpha(fg)[:, :] = alpha
        screen.blit(bg, (0, 0))
        screen.blit(fg, (0, 0))


def displayed_still_surface(current_state):
    """A still of what is on screen right now, or None if nothing is.

    Videos contribute their current frame, stills their surface — the
    inverted copy when a same-note repeat has flipped it, so the capture
    matches what the audience actually sees. Callers must capture BEFORE a
    trigger overwrites current_state (the scene hook itself runs after)."""
    player = current_state.get('video_player')
    if player:
        return player.get_frame()
    surface = current_state.get('surface')
    if (surface is not None and current_state.get('inverted')
            and current_state.get('surface_media')):
        return inverted_surface(current_state['surface_media'])
    return surface


def update_scene_on_trigger(current_state, media, now, scenes_config, rng=None,
                            prev_still=None):
    """Advance the active scene, or roll the activation dice for a new one.

    Called on every media-triggering note-on. While a scene is active each
    trigger is one beat; an active scene always runs to completion (config
    can't cancel it mid-flight). With no scene active, a roll under the
    configured probability activates a randomly chosen registered scene on
    this trigger's media. Normal state keeps updating underneath either way,
    so when the scene ends the screen resumes with the latest trigger.

    ``prev_still`` is what was on screen before this trigger (see
    displayed_still_surface) — the new scene's optional background."""
    scene = current_state.get('active_scene')
    if scene is not None:
        scene.advance(media, now)
        if not scene.done(now):
            return
        # The scene ended ON this trigger: clear it and fall through to the
        # activation roll, so a new scene can start on the very note that
        # ended the old one. Returning here instead left this note rendering
        # one normal full-screen frame before the next note could roll —
        # a visible flash between back-to-back scenes at high probability.
        current_state['active_scene'] = None
    if not scenes_config or not scenes_config.get('enabled', True):
        return
    if not SCENE_REGISTRY:
        return
    roll = (rng if rng is not None else random.random)()
    if roll >= scenes_config.get('probability', DEFAULT_SCENE_PROBABILITY):
        return
    still = media_still_surface(media)
    if still is None:
        return
    scene_cls = SCENE_REGISTRY[random.choice(sorted(SCENE_REGISTRY))]
    current_state['active_scene'] = scene_cls(still, now, background=prev_still)


def draw_performance_frame(screen, current_state, target_size, now=None,
                           display_mode='fill'):
    """Draw the media selected by MIDI.

    A same-note repeat of a still shows its colour-inverted (negative) copy; a
    different note shows the image normally. Video is unaffected (it restarts on
    retrigger, which already reads well). Pitch-bend zoom and mod-wheel pan
    apply live to whatever is on screen — stills, videos, and gif loops.

    An active scene takes over the whole frame (the narrow active_scene hook);
    once it reports done it is dropped here and the normal path resumes with
    whatever the latest triggers left in current_state."""
    scene = current_state.get('active_scene')
    if scene is not None:
        if now is None:
            now = time.monotonic()
        if scene.done(now):
            current_state['active_scene'] = None
        else:
            scene.render(screen, target_size, now)
            return
    zoom = effective_zoom_scale(current_state)
    pan = current_state.get('pan', 0.0)
    if current_state['video_player']:
        frame_surface = current_state['video_player'].get_frame()
        if frame_surface:
            screen.blit(
                zoom_surface_to_screen(
                    frame_surface, target_size, zoom, display_mode, pan),
                (0, 0)
            )
        else:
            screen.fill((0, 0, 0))
    elif current_state['surface']:
        surface = current_state['surface']
        if current_state.get('inverted') and current_state.get('surface_media'):
            surface = inverted_surface(current_state['surface_media'])
        scaled = render_still(current_state, surface, target_size, zoom,
                              display_mode, pan)
        screen.blit(scaled, (0, 0))
    else:
        screen.fill((0, 0, 0))


def process_midi_messages(msg_source, start_note, end_note, note_to_media, target_size,
                          current_state, channel=None, clock_tracker=None,
                          min_note_beats=None, zoom_ring_enabled=False,
                          note_hit_counts=None, assign_callback=None,
                          latch_mode=True, display_mode='fill',
                          scenes_config=None):
    """Process MIDI messages and update current display state.
    Returns updated current_state dict with 'surface', 'video_player', 'note_active'.
    If channel is set, only messages on that channel are processed.
    If latch_mode is false and min_note_beats is set, note-off is deferred
    until the minimum duration elapses. Every displayed note-on optionally
    starts a short black retrigger gap."""
    if note_hit_counts is None:
        note_hit_counts = {}

    messages = []
    if isinstance(msg_source, queue.Queue):
        while not msg_source.empty():
            messages.append(msg_source.get_nowait())
    else:
        for msg in msg_source.iter_pending():
            messages.append(msg)

    now = time.monotonic()

    for msg in messages:
        # Handle MIDI clock regardless of channel filter
        if msg.type == 'clock' and clock_tracker:
            clock_tracker.tick()
            continue

        # Live performance controls: pitch bend zooms the displayed media,
        # mod wheel (CC1) pans across the zoomed overflow. Channel-filtered
        # like notes; applied on every message, unquantized, so a sprung
        # wheel's release glides the media back to normal.
        if msg.type == 'pitchwheel':
            if channel is None or msg.channel == channel:
                current_state['bend_zoom'] = pitch_bend_zoom_scale(msg.pitch)
            continue
        if msg.type == 'control_change' and msg.control == MOD_WHEEL_CC:
            if channel is None or msg.channel == channel:
                current_state['pan'] = mod_wheel_pan(msg.value)
                current_state['pan_cc_time'] = now
                current_state['pan_ease'] = None  # live wheel overrides recenter
            continue

        if not hasattr(msg, 'note'):
            continue
        if channel is not None and msg.channel != channel:
            continue
        note = msg.note
        if not (start_note <= note <= end_note):
            continue

        is_note_on = msg.type == 'note_on' and msg.velocity > 0
        is_note_off = msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0)

        if is_note_on:
            if assign_callback and assign_callback(note):
                continue
            # A same-note repeat of a STILL flips it to its negative (XOR/invert)
            # and holds until the next hit, so hammering one key alternates
            # normal/negative. A different note always shows normally. Video is
            # untouched (it restarts on retrigger). last_note holds across
            # note-offs in both latch and non-latch modes.
            media = note_to_media.get(note)
            # What is on screen right now, captured before this trigger
            # rewrites the state — a newly activated scene's background. Only
            # taken when this trigger could actually activate a scene, so the
            # normal path never pays for (or touches) the capture.
            # (Captured even while a scene is active: a trigger can end the
            # old scene and activate the next one in the same call, and that
            # new scene's background is the underlying normal view.)
            prev_still = None
            if media and scenes_config and scenes_config.get('enabled', True):
                prev_still = displayed_still_surface(current_state)
            is_repeat = note == current_state.get('last_note')
            current_state['last_note'] = note
            if is_repeat and media and media['type'] == 'image':
                current_state['inverted'] = not current_state.get('inverted', False)
            else:
                current_state['inverted'] = False
            # Stop any current video
            if current_state['video_player']:
                current_state['video_player'].release()
                current_state['video_player'] = None

            # Clear any pending hold
            current_state['hold_until'] = None

            if media and media['type'] == 'video':
                current_state['zoom_scale'] = 1.0
                current_state['video_player'] = VideoPlayer(
                    media['path'], target_size, loop=media.get('loop', False),
                    display_mode=display_mode)
                current_state['surface'] = None
                current_state['surface_media'] = None
                current_state['note_active'] = note
                current_state['note_on_time'] = now
            elif media and media['type'] == 'image':
                current_state['zoom_scale'] = get_zoom_ring_scale(
                    note, note_hit_counts, zoom_ring_enabled
                )
                current_state['surface'] = media['surface']
                current_state['surface_media'] = media
                current_state['note_active'] = note
                current_state['note_on_time'] = now

            # Scenes: a media-triggering note-on is one "beat" — it advances
            # an active scene, or rolls the low-probability activation gate.
            if media:
                update_scene_on_trigger(current_state, media, now, scenes_config,
                                        prev_still=prev_still)

        elif (is_note_off and not latch_mode
              and note == current_state['note_active']):
            if min_note_beats and clock_tracker:
                min_dur = clock_tracker.note_duration(min_note_beats)
                elapsed = now - current_state.get('note_on_time', now)
                remaining = min_dur - elapsed
                if remaining > 0:
                    # Defer the note-off
                    current_state['hold_until'] = now + remaining
                    continue

            # Immediate note-off
            if current_state['video_player']:
                current_state['video_player'].release()
                current_state['video_player'] = None
            current_state['surface'] = None
            current_state['note_active'] = None
            current_state['zoom_scale'] = 1.0

    # Check if held display should expire
    if (not latch_mode and current_state.get('hold_until')
            and now >= current_state['hold_until']):
        if current_state['video_player']:
            current_state['video_player'].release()
            current_state['video_player'] = None
        current_state['surface'] = None
        current_state['note_active'] = None
        current_state['hold_until'] = None
        current_state['zoom_scale'] = 1.0

    return current_state


# --- Grid / media-manager view ---------------------------------------------

GRID_THUMB_W = 200
GRID_THUMB_H = 112  # 16:9
GRID_PAD = 16
GRID_TOP = 56  # header band height
GRID_FLASH_FADE = 0.5  # seconds a note-trigger highlight lingers after release


def make_thumbnail(media, thumb_size):
    """Build a small pygame surface for a media item.
    Videos use their first frame; images use their loaded surface."""
    if media['type'] == 'image':
        return crop_to_fill(media['surface'], thumb_size)

    cap = open_video_capture(media['path'])
    ret, frame = cap.read()
    cap.release()
    if not ret:
        placeholder = pygame.Surface(thumb_size)
        placeholder.fill((40, 40, 40))
        return placeholder
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    surface = pygame.surfarray.make_surface(np.transpose(frame, (1, 0, 2)))
    return crop_to_fill(surface, thumb_size)


def build_grid_cells(note_to_media, thumb_size):
    """Build one grid cell for every media file, with zero or one note label.

    Cells are ordered by their KEY (mapped cells first, in note order), then any
    unmapped files. Key-order keeps the grid stable across edits: replacing a
    cell by drag-drop hands its key to the new file, so the new thumbnail lands
    in the SAME spot rather than jumping to an alphabetical position."""
    media_by_name = {media['name']: media for media in note_to_media.values()}
    note_by_name = {media['name']: note for note, media in note_to_media.items()}
    all_files = list_media_files()
    mapped = sorted((n for n in all_files if n in note_by_name),
                    key=lambda n: note_by_name[n])
    unmapped = [n for n in order_media_files(all_files) if n not in note_by_name]
    cells = []
    for name in mapped + unmapped:
        media = media_by_name.get(name)
        if media is None:
            media = make_media_entry(name)
        note = note_by_name.get(name)
        cells.append({'media': media, 'type': media['type'],
                      'thumb': make_thumbnail(media, thumb_size),
                      'notes': [] if note is None else [note]})
    return cells


def format_notes(notes):
    """Return a cell's single key number, or a clear unmapped marker."""
    return str(notes[0]) if notes else '—'


def draw_text_outlined(surface, text, font, pos, color=(255, 255, 255),
                       outline=(0, 0, 0), outline_w=2):
    """Blit text with a black stroke so it stays legible over any thumbnail."""
    x, y = pos
    stroke = font.render(text, True, outline)
    for dx in (-outline_w, 0, outline_w):
        for dy in (-outline_w, 0, outline_w):
            if dx or dy:
                surface.blit(stroke, (x + dx, y + dy))
    base = font.render(text, True, color)
    surface.blit(base, (x, y))
    return base.get_size()


def cell_highlight(cell, active_note, flash_times, now):
    """Return highlight strength 0..1 for a cell: 1.0 while one of its notes is
    held, fading to 0 over GRID_FLASH_FADE seconds after the last trigger."""
    strength = 0.0
    for n in cell['notes']:
        if n == active_note:
            return 1.0
        t = flash_times.get(n)
        if t is not None:
            age = now - t
            if age < GRID_FLASH_FADE:
                strength = max(strength, 1.0 - age / GRID_FLASH_FADE)
    return strength


def grid_layout(num_cells, scroll_y, screen_size):
    """Compute the grid's shared geometry for a given cell count and scroll.

    Returned by the single source of truth that both rendering and drop
    hit-testing use, so a cell's on-screen rectangle is derived identically in
    every path (a divergent copy here is exactly the "selector that can't
    discriminate" trap). ``scroll_y`` comes back clamped to a valid offset."""
    sw, sh = screen_size
    cell_w = GRID_THUMB_W + GRID_PAD
    cell_h = GRID_THUMB_H + GRID_PAD
    cols = max(1, (sw - GRID_PAD) // cell_w)
    grid_w = cols * cell_w - GRID_PAD
    x0 = max(GRID_PAD, (sw - grid_w) // 2)
    top = GRID_TOP

    rows = (num_cells + cols - 1) // cols
    content_h = rows * cell_h
    view_h = sh - top - GRID_PAD
    max_scroll = max(0, content_h - view_h)
    scroll_y = max(0, min(scroll_y, max_scroll))
    return {'cols': cols, 'x0': x0, 'top': top,
            'cell_w': cell_w, 'cell_h': cell_h, 'scroll_y': scroll_y}


def cell_rect(index, layout):
    """Top-left (x, y) of a cell's thumbnail given a grid_layout() result."""
    col = index % layout['cols']
    row = index // layout['cols']
    x = layout['x0'] + col * layout['cell_w']
    y = layout['top'] + row * layout['cell_h'] - layout['scroll_y']
    return x, y


def grid_cell_at(cells, scroll_y, screen_size, pos):
    """Return the index of the grid cell under ``pos`` (x, y), or None.

    Drops that land on the header band, in inter-cell padding, or on empty
    space past the last cell return None rather than snapping to a neighbour —
    an off-target drop must miss, not silently reassign the wrong note."""
    mx, my = pos
    layout = grid_layout(len(cells), scroll_y, screen_size)
    if my < layout['top']:
        return None  # header band, never a drop target
    for i in range(len(cells)):
        x, y = cell_rect(i, layout)
        if x <= mx < x + GRID_THUMB_W and y <= my < y + GRID_THUMB_H:
            return i
    return None


def render_grid(screen, cells, scroll_y, fonts, active_note, flash_times, now,
                selected_index=None):
    """Draw the media-manager grid. Returns the clamped scroll offset."""
    sw, sh = screen.get_size()
    screen.fill((18, 18, 18))

    layout = grid_layout(len(cells), scroll_y, screen_size=(sw, sh))
    scroll_y = layout['scroll_y']
    top = layout['top']

    for i, cell in enumerate(cells):
        x, y = cell_rect(i, layout)
        if y + GRID_THUMB_H < top or y > sh:
            continue  # fully scrolled off-screen

        screen.blit(cell['thumb'], (x, y))

        if not cell['notes']:
            dim = pygame.Surface((GRID_THUMB_W, GRID_THUMB_H), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 115))
            screen.blit(dim, (x, y))

        hl = cell_highlight(cell, active_note, flash_times, now)
        if hl > 0:
            border = int(2 + 4 * hl)
            color = (255, int(60 + 180 * hl), 40)
            pygame.draw.rect(screen, color,
                             (x - 2, y - 2, GRID_THUMB_W + 4, GRID_THUMB_H + 4),
                             border)
        if i == selected_index:
            pygame.draw.rect(screen, (80, 210, 255),
                             (x - 4, y - 4, GRID_THUMB_W + 8, GRID_THUMB_H + 8), 4)

        draw_text_outlined(screen, format_notes(cell['notes']), fonts['note'],
                           (x + 6, y + 4))
        if cell['type'] == 'video':
            draw_text_outlined(screen, 'VID', fonts['small'],
                               (x + GRID_THUMB_W - 48, y + GRID_THUMB_H - 26),
                               color=(255, 220, 120))

    # Header band (drawn last so thumbnails scroll underneath it)
    pygame.draw.rect(screen, (30, 30, 30), (0, 0, sw, top))
    pygame.draw.line(screen, (70, 70, 70), (0, top), (sw, top), 2)
    header = (f"GRID VIEW  |  {len(cells)} media  |  "
              f"Click: select, then play a key/MIDI note to map it   "
              f"Delete: unmap   "
              f"Drop file: replace   Tab: perform   Esc: quit")
    draw_text_outlined(screen, header, fonts['header'], (GRID_PAD, 15),
                       color=(230, 230, 230), outline_w=1)

    return scroll_y


GRID_DROP_FLASH = 0.6  # seconds a drop-result border lingers


def supported_media_file(path):
    """True if ``path`` has a supported image/video extension."""
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS + VIDEO_EXTS


def normalize_drop_paths(raw):
    """Turn a DROPFILE/DROPTEXT payload into a list of local filesystem paths.

    On some Linux setups the payload arrives as a ``file://`` URI (possibly
    percent-encoded, possibly a multi-line text/uri-list with trailing
    newlines/CRs) rather than a bare path.  Decodes each non-empty line into a
    plain path; lines that aren't local files (e.g. ``http://`` URLs) are
    dropped."""
    paths = []
    for line in raw.splitlines() or [raw]:
        line = line.strip()
        if not line:
            continue
        if line.startswith('file:'):
            parsed = urllib.parse.urlparse(line)
            if parsed.netloc not in ('', 'localhost'):
                continue  # file on another host, not reachable
            line = urllib.parse.unquote(parsed.path)
        elif '://' in line:
            continue  # non-file URL, nothing to copy
        if line:
            paths.append(line)
    return paths


# Cached X11 connection: (libX11, Display*) once opened, or False after a
# failed attempt so non-X11 platforms don't retry on every use.  Shared by the
# drop-target pointer query and the always-on-top state setter — one private
# connection, no SDL internals touched.
_x11_conn = None


def _x11_connection():
    """Return the cached private (libX11, Display*) pair, or None off-X11."""
    global _x11_conn
    if _x11_conn is False:
        return None
    if _x11_conn is None:
        try:
            xlib = ctypes.CDLL('libX11.so.6')
            xlib.XOpenDisplay.restype = ctypes.c_void_p
            xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            display = xlib.XOpenDisplay(None)
        except Exception:
            display = None
        if not display:
            _x11_conn = False
            return None
        _x11_conn = (xlib, display)
    return _x11_conn


def x11_query_pointer():
    """Window-relative pointer position straight from the X server, or None.

    During an external XDND drag SDL2/X11 delivers no MOUSEMOTION events, so
    ``pygame.mouse.get_pos()`` still reports wherever the cursor last was
    *before* the drag — the drop then hit-tests a stale point.  XQueryPointer
    asks the server directly (it ignores the drag source's pointer grab), via a
    private connection so no SDL internals are touched.  Returns None off-X11
    or on any failure; callers fall back to pygame's view."""
    global _x11_conn
    try:
        window = pygame.display.get_wm_info().get('window')
        if not window:
            return None
        conn = _x11_connection()
        if conn is None:
            return None
        xlib, display = conn
        root = ctypes.c_ulong()
        child = ctypes.c_ulong()
        root_x = ctypes.c_int()
        root_y = ctypes.c_int()
        win_x = ctypes.c_int()
        win_y = ctypes.c_int()
        mask = ctypes.c_uint()
        found = xlib.XQueryPointer(
            ctypes.c_void_p(display), ctypes.c_ulong(window),
            ctypes.byref(root), ctypes.byref(child),
            ctypes.byref(root_x), ctypes.byref(root_y),
            ctypes.byref(win_x), ctypes.byref(win_y),
            ctypes.byref(mask))
        if not found:
            return None
        return win_x.value, win_y.value
    except Exception:
        _x11_conn = False
        return None


def drop_pointer_pos():
    """Best-known window-relative pointer position for resolving a drop target.

    Prefers a live X server query (fresh even mid-XDND-drag); falls back to
    ``pygame.mouse.get_pos()`` on other platforms, where SDL keeps the mouse
    state current during drags."""
    pos = x11_query_pointer()
    if pos is not None:
        return pos
    return pygame.mouse.get_pos()


# EWMH client-message constants for _NET_WM_STATE on a mapped window.
_NET_WM_STATE_REMOVE = 0
_NET_WM_STATE_ADD = 1
_X_CLIENT_MESSAGE = 33
_X_SUBSTRUCTURE_MASKS = (1 << 19) | (1 << 20)  # Notify | Redirect


class _XClientMessageEvent(ctypes.Structure):
    """Just the XClientMessageEvent members, padded out to XEvent's 192 bytes
    (``long pad[24]``) so libX11 may copy the full union safely."""
    _fields_ = [('type', ctypes.c_int),
                ('serial', ctypes.c_ulong),
                ('send_event', ctypes.c_int),
                ('display', ctypes.c_void_p),
                ('window', ctypes.c_ulong),
                ('message_type', ctypes.c_ulong),
                ('format', ctypes.c_int),
                ('data', ctypes.c_long * 5),
                ('pad', ctypes.c_byte * 104)]


def build_wm_state_event(window, state_atom, above_atom, action):
    """Build the EWMH _NET_WM_STATE client message toggling ABOVE on a window.

    A window that is already mapped ignores direct property writes; the WM only
    honors a ClientMessage sent to the root window, which is why this exists
    instead of an XChangeProperty call."""
    event = _XClientMessageEvent()
    event.type = _X_CLIENT_MESSAGE
    event.window = window
    event.message_type = state_atom
    event.format = 32
    event.data[0] = action
    event.data[1] = above_atom
    return event


def _x11_set_always_on_top(window, on_top):
    """Ask the X11 window manager to keep ``window`` above normal windows."""
    conn = _x11_connection()
    if conn is None:
        return False
    xlib, display = conn
    xlib.XInternAtom.restype = ctypes.c_ulong
    xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    state = xlib.XInternAtom(display, b'_NET_WM_STATE', 0)
    above = xlib.XInternAtom(display, b'_NET_WM_STATE_ABOVE', 0)
    xlib.XDefaultRootWindow.restype = ctypes.c_ulong
    xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    root = xlib.XDefaultRootWindow(display)
    action = _NET_WM_STATE_ADD if on_top else _NET_WM_STATE_REMOVE
    event = build_wm_state_event(window, state, above, action)
    xlib.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                ctypes.c_long, ctypes.c_void_p]
    sent = xlib.XSendEvent(display, root, 0, _X_SUBSTRUCTURE_MASKS,
                           ctypes.byref(event))
    xlib.XFlush(ctypes.c_void_p(display))
    return bool(sent)


def _windows_set_always_on_top(hwnd, on_top):
    """Pin/unpin the window in Windows' topmost band via SetWindowPos."""
    HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
    SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
    insert_after = HWND_TOPMOST if on_top else HWND_NOTOPMOST
    return bool(ctypes.windll.user32.SetWindowPos(
        hwnd, insert_after, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))


def set_window_always_on_top(on_top):
    """Set/clear always-on-top on the current display window. Best effort.

    Keyframes runs fullscreen beneath the ShowSync projector (itself fullscreen
    + always-on-top): the projector raises itself for video and hides after, so
    Keyframes must outrank every NORMAL window or whatever was clicked last is
    revealed instead of the visuals.  Fullscreen pins the window above the
    normal layer; the windowed F11 toggle clears it so a desktop window behaves
    like one.  Returns True only when the platform call reports success —
    unsupported platforms/backends (e.g. the dummy video driver, Wayland
    without XWayland) just return False and the show goes on unpinned."""
    try:
        window = pygame.display.get_wm_info().get('window')
        if not window:
            return False
        if sys.platform == 'win32':
            return _windows_set_always_on_top(window, on_top)
        return _x11_set_always_on_top(window, on_top)
    except Exception:
        return False


def import_dropped_file(src):
    """Copy a dropped file into ``images/`` if it isn't already there.

    Returns the basename to store in the mapping. A file already living in
    ``images/`` (by name) is reused as-is — matching the manifest's filename-
    keyed contract — rather than re-copied."""
    name = os.path.basename(src)
    dst = os.path.join(IMAGES_DIR, name)
    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR)
    if os.path.abspath(src) != os.path.abspath(dst) and not os.path.exists(dst):
        shutil.copy2(src, dst)
    return name


def reassign_cell_media(note_to_media, notes, name):
    """Point every note in ``notes`` at the media for filename ``name``, live.

    Reuses an already-loaded object for ``name`` if one exists so the grid's
    id()-based dedup keeps showing a single cell per file; only decodes a fresh
    object when the file isn't loaded yet."""
    existing = None
    for media in note_to_media.values():
        if media.get('name') == name:
            existing = media
            break
    if existing is None:
        existing = make_media_entry(name)
    for note in notes:
        note_to_media[note] = existing
    return existing


def remove_media_file(name, keep=None):
    """Delete a media file from ``images/`` after a replace, safely.

    No-op (returns False) when ``name`` is empty, equals ``keep`` (never delete
    the file that just replaced it), or resolves outside ``IMAGES_DIR`` — a
    realpath guard so a crafted basename can't escape the media dir and unlink
    something else. Returns True only when a file was actually removed."""
    if not name or name == keep:
        return False
    base = os.path.realpath(IMAGES_DIR)
    real = os.path.realpath(os.path.join(IMAGES_DIR, name))
    if real == base or os.path.commonpath([real, base]) != base:
        return False
    if os.path.exists(real):
        os.remove(real)
        return True
    return False


def apply_drop(filepath, cell, note_to_media):
    """Replace the targeted grid cell's media in place, keeping its key.

    Copies the dropped file B into ``images/`` (skipping the copy if it is
    already there), then:
      * If the cell has a key (note N): steal N from the old file A and assign
        N -> B through the shared mapping, so B now triggers on N (and B's own
        prior key, if any, is stolen too).
      * If the cell is unmapped: B simply replaces A in that slot and stays
        unmapped (no key to inherit).
    The old file A is then deleted from ``images/`` (never when A is B itself,
    and only after a realpath check confirms it lives inside IMAGES_DIR) so no
    orphan cell is left behind — dropped files are copies from elsewhere, so the
    source is the backup. ``note_to_media`` is live-updated in place (A and any
    stale B entry dropped, the cell's notes pointed at B, reusing an already-
    loaded object for B) and the caller rebuilds the grid. Returns True on
    success, or False for an unsupported file type (caller flashes red; nothing
    is copied or deleted)."""
    if not supported_media_file(filepath):
        return False
    old_name = cell['media']['name']
    name = import_dropped_file(filepath)
    notes = list(cell['notes'])
    target_media = next((media for media in note_to_media.values()
                         if media['name'] == name), None)
    if target_media is None:
        target_media = make_media_entry(name)
    # The dropped file may already be mapped elsewhere: steal that key, then
    # steal the cell's key (if any) onto it.
    mapping = unmap_mapping(load_mapping(), name)
    for note in notes:
        mapping = assign_mapping(mapping, note, name)
    save_mapping(mapping)
    for note, media in list(note_to_media.items()):
        if media['name'] in (old_name, name):
            del note_to_media[note]
    for note in notes:
        note_to_media[note] = target_media
    remove_media_file(old_name, keep=name)
    if notes:
        print(f"Replaced {old_name} with {name} at key {notes[0]}")
    else:
        print(f"Replaced {old_name} with {name}")
    return True


def assign_cell_note(cell, note, note_to_media):
    """Map ``note`` to the selected cell, stealing its old key if necessary."""
    name = cell['media']['name']
    save_mapping(assign_mapping(load_mapping(), note, name))
    for old_note, media in list(note_to_media.items()):
        if old_note == note or media['name'] == name:
            del note_to_media[old_note]
    note_to_media[note] = cell['media']


def grid_assign_note(cells, selected_index, note, note_to_media):
    """One-shot remap: assign ``note`` to the selected cell, consuming the
    selection.

    Selection *is* the arm step — while a cell is selected, the next played
    note (computer-piano key or incoming MIDI) remaps it via
    assign_cell_note's exclusive steal. Returns ``(rebuilt_cells, None)`` so
    one selection yields exactly one remap; further playing just previews.
    With no selection, returns the arguments unchanged."""
    if not cells or selected_index is None:
        return cells, selected_index
    assign_cell_note(cells[selected_index], note, note_to_media)
    return build_grid_cells(note_to_media, (GRID_THUMB_W, GRID_THUMB_H)), None


def unmap_cell(cell, note_to_media):
    """Clear a selected cell's key without deleting its media."""
    name = cell['media']['name']
    save_mapping(unmap_mapping(load_mapping(), name))
    for note, media in list(note_to_media.items()):
        if media['name'] == name:
            del note_to_media[note]


def draw_drop_flash(screen, cells, scroll_y, drop_flash, now):
    """Draw the success/failure border for the most recent drop, if still live.

    Green = the cell was reassigned; red = the drop was rejected (unsupported
    type or landed off any cell). Located via the same grid_layout() the drop
    hit-test used, so the flash lands exactly on the cell that was targeted.
    A flash with ``note=None`` (drop missed every cell) borders the whole
    window instead — a missed drop must never be invisible."""
    if not drop_flash or now >= drop_flash['until']:
        return
    if drop_flash['note'] is None:
        pygame.draw.rect(screen, (230, 60, 60), screen.get_rect(), 6)
        return
    index = None
    for i, cell in enumerate(cells):
        if drop_flash['note'] in cell['notes']:
            index = i
            break
    if index is None:
        return
    layout = grid_layout(len(cells), scroll_y, screen.get_size())
    x, y = cell_rect(index, layout)
    if y + GRID_THUMB_H < layout['top'] or y > screen.get_height():
        return  # cell scrolled out of view
    color = (60, 220, 90) if drop_flash['ok'] else (230, 60, 60)
    pygame.draw.rect(screen, color,
                     (x - 3, y - 3, GRID_THUMB_W + 6, GRID_THUMB_H + 6), 5)


def begin_grid_gesture(cells, scroll_y, screen_size, pos):
    """Start a held-click gesture for the optional in-place video preview."""
    idx = grid_cell_at(cells, scroll_y, screen_size, pos)
    if idx is None:
        return None
    return {'from_index': idx,
            'is_video': cells[idx]['type'] == 'video'}


def gesture_previews(gesture, cells, scroll_y, screen_size, pos):
    """True while the held gesture should show an in-place video preview.

    Requires a video cell and the pointer still over the originating cell."""
    if not gesture or not gesture.get('is_video'):
        return False
    return grid_cell_at(cells, scroll_y, screen_size, pos) == gesture['from_index']


def draw_grid_preview(screen, cells, scroll_y, preview):
    """Blit the live preview frame over its cell during press-and-hold playback.

    The VideoPlayer decodes straight to the cell's thumb size (crop-to-fill), so
    the frame drops in exactly where the still thumbnail sat. Uses the shared
    grid_layout()/cell_rect() geometry, and skips a cell scrolled out of view."""
    if not preview:
        return
    index = preview['index']
    if index >= len(cells):
        return
    frame = preview['player'].get_frame()
    if frame is None:
        return
    layout = grid_layout(len(cells), scroll_y, screen.get_size())
    x, y = cell_rect(index, layout)
    if y + GRID_THUMB_H < layout['top'] or y > screen.get_height():
        return
    screen.blit(frame, (x, y))


def select_midi_ports(available_ports, port_filter=None):
    """Select MIDI ports. If port_filter is given, return all substring matches.
    Otherwise auto-select all hardware ports (skip virtual ones)."""
    if not available_ports:
        return []

    if port_filter:
        matches = [p for p in available_ports if port_filter.lower() in p.lower()]
        return matches

    # Auto-select: prefer hardware ports (skip common virtual/software ports)
    virtual_keywords = ['through', 'virtual', 'midi through', 'rtpmidi']
    hardware = [p for p in available_ports
                if not any(kw in p.lower() for kw in virtual_keywords)]
    if hardware:
        return hardware

    return [available_ports[0]]


def run_packaging_smoke_test():
    """Exercise the shipped image, video, GIF, and RT-MIDI backend without hardware."""
    image_files = sorted(Path(IMAGES_DIR).glob('*.png'))
    video_files = sorted(Path(IMAGES_DIR).glob('*.mp4'))
    gif_files = sorted(Path(IMAGES_DIR).glob('*.gif'))
    if not image_files or not video_files or not gif_files:
        raise RuntimeError(
            'Packaging smoke test needs one .png, one .mp4, and one .gif in images/.')

    pygame.init()
    try:
        # ``convert_alpha`` deliberately verifies the pygame display backend too.
        # A tiny hidden surface keeps this test non-interactive on the build VM.
        pygame.display.set_mode((1, 1), pygame.HIDDEN)
        pygame.image.load(str(image_files[0])).convert_alpha()
        player = VideoPlayer(str(video_files[0]), (320, 180))
        try:
            if player.get_frame() is None:
                raise RuntimeError(f'OpenCV could not decode {video_files[0].name}.')
        finally:
            player.release()

        # Animated-GIF support rides on the bundled OpenCV/ffmpeg decoding
        # GIFs frame-by-frame.  Reading only the first frame would pass even
        # if animation were broken, so require a SECOND frame that differs
        # from the first.
        gif_cap = cv2.VideoCapture(str(gif_files[0]))
        try:
            got_first, first_frame = gif_cap.read()
            if not got_first:
                raise RuntimeError(f'OpenCV could not decode {gif_files[0].name}.')
            animated = False
            for _ in range(64):
                got_next, next_frame = gif_cap.read()
                if not got_next:
                    break
                if next_frame.shape != first_frame.shape or (next_frame != first_frame).any():
                    animated = True
                    break
            if not animated:
                raise RuntimeError(
                    f'{gif_files[0].name} decoded only one distinct frame; '
                    'animated GIF playback would be broken in this build.')
        finally:
            gif_cap.release()

        # GIFs play through a looping VideoPlayer: reading past end-of-stream
        # must rewind (CAP_PROP_POS_FRAMES) and keep yielding frames.
        gif_frames = int(cv2.VideoCapture(str(gif_files[0])).get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        # A stepped clock makes every get_frame() call due immediately —
        # fps pacing would otherwise let this tight loop finish without
        # ever reaching end-of-stream, proving nothing about rewind.
        looping = VideoPlayer(str(gif_files[0]), (64, 48), loop=True,
                              clock=make_step_clock(1.0))
        try:
            for _ in range(gif_frames + 2):
                if looping.get_frame() is None:
                    raise RuntimeError(
                        f'Looping playback of {gif_files[0].name} stopped yielding frames.')
            if looping.finished:
                raise RuntimeError(
                    f'Looping player finished on {gif_files[0].name}; GIF loop rewind failed.')
        finally:
            looping.release()

        # This import and enumeration load the dynamically selected mido RT-MIDI
        # backend.  No input device is required for either operation.
        import mido.backends.rtmidi  # noqa: F401
        mido.get_input_names()
    finally:
        pygame.quit()

    print('Packaging smoke test passed: image, video, animated GIF, '
          'and RT-MIDI backend are available.')


def main():
    parser = argparse.ArgumentParser(description="MIDI Note Image Display")
    parser.add_argument('--midi-file', '-f', help="Path to a MIDI file to play back")
    parser.add_argument('--loop', '-l', action='store_true', help="Loop MIDI file playback")
    parser.add_argument('--channel', '-c', type=int, choices=range(1, 17), metavar='1-16',
                        help="MIDI channel to listen on (1-16, default: all)")
    parser.add_argument('--port', '-p', type=str, default=None,
                        help="MIDI port name substring to match (e.g. 'KeyStep')")
    parser.add_argument('--start-note', type=int, default=DEFAULT_START_NOTE,
                        help=f"Lowest MIDI note number (default: {DEFAULT_START_NOTE})")
    parser.add_argument('--num-keys', type=int, default=DEFAULT_NUM_KEYS,
                        help=f"Number of keys/notes (default: {DEFAULT_NUM_KEYS})")
    parser.add_argument('--min-note', type=str, default=None, metavar='LENGTH',
                        help="Minimum display duration as note length: "
                             "whole, half, quarter, eighth, sixteenth, thirtysecond "
                             "(or 1, 1/2, 1/4, 1/8, 1/16, 1/32)")
    parser.add_argument('--no-latch', action='store_true',
                        help="Release media on note-off instead of latching the last hit")
    parser.add_argument('--bpm', type=float, default=DEFAULT_BPM,
                        help=f"Fallback BPM when no MIDI clock is present (default: {DEFAULT_BPM})")
    parser.add_argument('--zoom-ring', action='store_true',
                        help="Give each note a 16-step zoom ring: repeated hits on the same "
                             "note grow slightly larger before wrapping to normal size")
    parser.add_argument('--windowed', '-w', action='store_true',
                        help="Run in a window instead of fullscreen")
    parser.add_argument('--display-mode', choices=('fill', 'fit'), default='fill',
                        help="How media is scaled to the screen: 'fill' scales to "
                             "cover and center-crops (default); 'fit' shows the "
                             "entire media with black letterbox/pillarbox bars")
    parser.add_argument('--packaging-smoke-test', action='store_true',
                        help=argparse.SUPPRESS)
    parser.add_argument('--size', type=str, default='1280x720', metavar='WxH|PRESET',
                        help="Window size: WxH or preset name — "
                             "hd (1920x1080), 4k (3840x2160), "
                             "tiktok (1080x1920), tiktok-sm (720x1280), "
                             "square (1080x1080), ig-story (1080x1920), "
                             "reel (1080x1350) (default: 1280x720)")
    args = parser.parse_args()


    if args.packaging_smoke_test:
        run_packaging_smoke_test()
        return

    start_note = args.start_note
    num_keys = args.num_keys
    end_note = start_note + num_keys - 1

    # Parse minimum note duration
    min_note_beats = None
    if args.min_note:
        if args.min_note.lower() not in NOTE_LENGTHS:
            print(f"Unknown note length: {args.min_note}")
            print(f"  Valid values: {', '.join(sorted(NOTE_LENGTHS.keys()))}")
            sys.exit(1)
        min_note_beats = NOTE_LENGTHS[args.min_note.lower()]

    clock_tracker = MidiClockTracker(fallback_bpm=args.bpm)

    pygame.init()
    enable_all_events()

    last_windowed_size = parse_window_size(args.size)
    fullscreen = not args.windowed
    # Same path the F11 toggle takes, so launch and toggle agree on flags,
    # cursor visibility, and the always-on-top state (fullscreen only).
    screen, display_w, display_h, target_size = set_display_mode(
        fullscreen, last_windowed_size, {'video_player': None})

    pygame.display.set_caption("Keyframes")

    # Load media
    note_to_media = load_media(start_note, end_note)
    if note_to_media is None:
        show_instructions(screen, display_w, display_h)
        pygame.quit()
        return

    # Set up MIDI sources: file playback, live input, and/or keyboard
    msg_queue = queue.Queue()
    stop_event = threading.Event()
    inports = []

    if args.midi_file:
        if not os.path.exists(args.midi_file):
            print(f"MIDI file not found: {args.midi_file}")
            sys.exit(1)
        playback_thread = threading.Thread(
            target=play_midi_file,
            args=(args.midi_file, msg_queue, stop_event, args.loop),
            daemon=True
        )
        playback_thread.start()
    else:
        # Try to open MIDI devices, but don't require them (keyboard always works)
        inputs = mido.get_input_names()
        if inputs:
            port_names = select_midi_ports(inputs, args.port)
            if port_names:
                for pn in port_names:
                    inports.append(mido.open_input(pn))
                    print(f"MIDI input: {pn}")
            else:
                print("No matching MIDI input found — using keyboard only.")
                print(f"  Available ports: {inputs}")
        else:
            print("No MIDI input devices found — using keyboard only.")

    print("Keyboard: Z-M (lower octave), Q-P (upper octave). L: toggle latch. ESC to quit.")
    print("Tab: toggle grid/media-manager view (Up/Down or mouse wheel to scroll).")
    print("F1 or ?: show the on-screen help overlay again.")

    state = {'surface': None, 'video_player': None, 'note_active': None,
             'note_on_time': None, 'hold_until': None, 'zoom_scale': 1.0,
             'bend_zoom': 1.0, 'pan': 0.0, 'pan_cc_time': None, 'pan_ease': None,
             'inverted': False, 'surface_media': None, 'last_note': None,
             'active_scene': None}
    scenes_config = load_scenes_config()
    if scenes_config['enabled']:
        print(f"Scenes enabled: {scenes_config['probability']:.0%} chance per "
              f"trigger ({', '.join(sorted(SCENE_REGISTRY))}) — see scenes.json")
    else:
        print("Scenes disabled (scenes.json)")
    note_hit_counts = {}
    latch_enabled = not args.no_latch
    latch_notice_until = 0

    # Startup help overlay: shown on launch (performance view, media present),
    # dismissed on the first note played, reshowable via F1/?.
    show_help = True

    # Grid / media-manager view state
    grid_mode = False
    grid_cells = None  # built lazily the first time the grid is opened
    grid_scroll = 0
    flash_times = {}  # note -> monotonic time it was last triggered
    drop_flash = None  # {'note', 'until', 'ok'} border feedback for last drop
    grid_drag = None  # {'from_index','thumb','start','moved','is_video'} gesture
    grid_preview = None  # {'index', 'player'} live press-and-hold video preview
    selected_index = None
    prev_active = None
    grid_fonts = {
        'note': pygame.font.SysFont(None, 40),
        'small': pygame.font.SysFont(None, 26),
        'header': pygame.font.SysFont(None, 30),
    }

    def assign_if_selected(note):
        nonlocal selected_index, grid_cells
        if not (grid_mode and grid_cells and selected_index is not None):
            return False
        grid_cells, selected_index = grid_assign_note(
            grid_cells, selected_index, note, note_to_media)
        print(f"Mapped selected media to key {note}")
        return True

    if min_note_beats:
        dur = clock_tracker.note_duration(min_note_beats)
        print(f"Minimum display: {args.min_note} note = {dur:.3f}s at {clock_tracker.bpm:.0f} BPM"
              f" (live MIDI clock will override)")
    if args.zoom_ring:
        print(f"Zoom ring enabled: {ZOOM_RING_SIZE} positions, +{ZOOM_RING_STEP:.2f} scale per hit")

    midi_channel = args.channel - 1 if args.channel else None
    clock = pygame.time.Clock()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE and not fullscreen:
                display_w, display_h = event.w, event.h
                last_windowed_size = (display_w, display_h)
                screen = pygame.display.set_mode(last_windowed_size, pygame.RESIZABLE)
                target_size = update_display_target_size(
                    state, display_w, display_h)
            elif event.type == pygame.KEYDOWN:
                # Any key dismisses the startup help overlay and returns to the
                # normal view — matching "press any key to continue". The F1/?
                # reshow bindings are excepted (handled below). While the overlay
                # is up, Escape closes it instead of quitting, so it can't
                # surprise-exit the app. The key still performs its normal action
                # (a piano key also plays its note, Tab still opens the grid).
                if show_help and not grid_mode and not is_help_reshow_key(event):
                    show_help = update_help_visibility(show_help, key_pressed=True)
                    if event.key == pygame.K_ESCAPE:
                        continue  # consumed: closed the overlay, don't also quit
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif is_fullscreen_toggle_key(event):
                    if not fullscreen:
                        last_windowed_size = (display_w, display_h)
                    fullscreen = not fullscreen
                    screen, display_w, display_h, target_size = set_display_mode(
                        fullscreen, last_windowed_size, state)
                elif is_help_reshow_key(event):
                    # Reshow the startup help overlay. Handled ahead of
                    # KEY_TO_NOTE so F1/? never doubles as a played note; it
                    # dismisses again on the next note. Ignored in grid view,
                    # which has its own on-screen controls header.
                    if not grid_mode:
                        show_help = update_help_visibility(show_help, reshow_key=True)
                elif event.key == pygame.K_l:
                    latch_enabled = toggle_latch_mode(latch_enabled)
                    if latch_enabled:
                        # A pending minimum-duration release belongs to the
                        # non-latch mode that just ended.
                        state['hold_until'] = None
                    latch_notice_until = time.monotonic() + LATCH_NOTICE_SECONDS
                    print(f"Latch mode: {'on' if latch_enabled else 'off'}")
                elif event.key == pygame.K_TAB:
                    grid_mode = not grid_mode
                    if grid_mode and grid_cells is None:
                        grid_cells = build_grid_cells(
                            note_to_media, (GRID_THUMB_W, GRID_THUMB_H))
                    grid_scroll = 0
                    # Leaving the grid mid-hold: drop the gesture so it can't
                    # keep a preview alive off-screen (reconcile releases it).
                    grid_drag = None
                    selected_index = None
                elif (grid_mode and selected_index is not None and grid_cells
                      and event.key in (pygame.K_DELETE, pygame.K_BACKSPACE)):
                    unmap_cell(grid_cells[selected_index], note_to_media)
                    grid_cells = build_grid_cells(
                        note_to_media, (GRID_THUMB_W, GRID_THUMB_H))
                    selected_index = None
                    print("Unmapped selected media")
                elif grid_mode and event.key in (pygame.K_UP, pygame.K_DOWN,
                                                 pygame.K_PAGEUP, pygame.K_PAGEDOWN,
                                                 pygame.K_HOME, pygame.K_END):
                    if event.key == pygame.K_UP:
                        grid_scroll -= 80
                    elif event.key == pygame.K_DOWN:
                        grid_scroll += 80
                    elif event.key == pygame.K_PAGEUP:
                        grid_scroll -= 400
                    elif event.key == pygame.K_PAGEDOWN:
                        grid_scroll += 400
                    elif event.key == pygame.K_HOME:
                        grid_scroll = 0
                    elif event.key == pygame.K_END:
                        grid_scroll = 10 ** 9  # clamped during render
                elif event.key in KEY_TO_NOTE:
                    # Piano keys always enqueue; assign_if_selected (the queue's
                    # assign_callback) turns the note into a remap when a grid
                    # cell is selected, so keyboard and MIDI share one path.
                    note = KEY_TO_NOTE[event.key]
                    msg_queue.put(mido.Message('note_on', note=note, velocity=100))
            elif event.type == pygame.KEYUP:
                if event.key in KEY_TO_NOTE:
                    note = KEY_TO_NOTE[event.key]
                    msg_queue.put(mido.Message('note_off', note=note, velocity=0))
            elif event.type == pygame.MOUSEWHEEL and grid_mode:
                grid_scroll -= event.y * 60
            elif (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                  and grid_mode and grid_cells):
                # A held click previews videos; releasing it simply selects.
                grid_drag = begin_grid_gesture(grid_cells, grid_scroll,
                                               screen.get_size(), event.pos)
            elif (event.type == pygame.MOUSEBUTTONUP and event.button == 1
                  and grid_mode and grid_cells):
                # Release over a cell selects it (arming the next played note);
                # release over the header/padding deselects (grid_cell_at None).
                selected_index = grid_cell_at(grid_cells, grid_scroll,
                                              screen.get_size(), event.pos)
                grid_drag = None
            elif event.type in (pygame.DROPFILE, pygame.DROPTEXT):
                # Native drag-and-drop: replace the cell under the cursor with
                # the dropped media file (copy into images/, persist via the
                # mapping, delete the old file, reload live). DROPTEXT covers
                # file managers that hand SDL a text/uri-list instead of a plain
                # path; normalize_drop_paths decodes either payload. The drop
                # target comes from drop_pointer_pos() — on X11
                # pygame.mouse.get_pos() is stale during an external drag (no
                # MOUSEMOTION is delivered), so the X server is queried directly.
                raw = getattr(event, 'file', None) or getattr(event, 'text', '') or ''
                paths = normalize_drop_paths(raw)
                pointer = drop_pointer_pos()
                idx = None
                if grid_mode and grid_cells:
                    idx = grid_cell_at(grid_cells, grid_scroll,
                                       screen.get_size(), pointer)
                if not grid_mode or not grid_cells:
                    pass  # only the grid view accepts drops
                elif idx is None:
                    # Missed every cell: flash the whole window red so a failed
                    # drop is never silent.
                    drop_flash = {'note': None, 'ok': False,
                                  'until': time.monotonic() + GRID_DROP_FLASH}
                else:
                    cell = grid_cells[idx]
                    flash_note = cell['notes'][0] if cell['notes'] else None
                    ok = bool(paths) and apply_drop(paths[0], cell, note_to_media)
                    if ok:
                        grid_cells = build_grid_cells(
                            note_to_media, (GRID_THUMB_W, GRID_THUMB_H))
                    drop_flash = {'note': flash_note, 'ok': ok,
                                  'until': time.monotonic() + GRID_DROP_FLASH}

        # Process keyboard/file messages from queue
        state = process_midi_messages(msg_queue, start_note, end_note,
                                      note_to_media, target_size, state, midi_channel,
                                      clock_tracker, min_note_beats, args.zoom_ring,
                                      note_hit_counts, assign_if_selected,
                                      latch_enabled, args.display_mode,
                                      scenes_config)
        # Process live MIDI device messages
        for inport in inports:
            state = process_midi_messages(inport, start_note, end_note,
                                          note_to_media, target_size, state, midi_channel,
                                          clock_tracker, min_note_beats, args.zoom_ring,
                                          note_hit_counts, assign_if_selected,
                                          latch_enabled, args.display_mode,
                                          scenes_config)

        # Track note triggers for the grid's flash highlight (works in both views)
        now = time.monotonic()
        if PAN_AUTO_RECENTER:
            update_pan_recenter(state, now)
        cur_active = state['note_active']
        note_started = cur_active is not None and cur_active != prev_active
        if note_started:
            flash_times[cur_active] = now
        prev_active = cur_active

        # Dismiss the startup help overlay the moment a note is played. This
        # covers both keyboard piano keys and incoming MIDI notes uniformly,
        # since both surface here as a newly-active note.
        show_help = update_help_visibility(show_help, note_started=note_started)

        # Reconcile the press-and-hold preview with the current gesture. Runs
        # every frame (not just on events) so playback starts the moment a video
        # cell is pressed and stops on release, on becoming a drag, or when the
        # pointer leaves the cell — all folded into gesture_previews(). Only one
        # preview lives at a time; switching to a different held cell releases
        # the old VideoPlayer before opening the new one.
        if grid_mode and grid_cells and gesture_previews(
                grid_drag, grid_cells, grid_scroll,
                screen.get_size(), pygame.mouse.get_pos()):
            hold_idx = grid_drag['from_index']
            if grid_preview is None or grid_preview['index'] != hold_idx:
                if grid_preview:
                    grid_preview['player'].release()
                media = grid_cells[hold_idx]['media']
                grid_preview = {'index': hold_idx,
                                'player': VideoPlayer(
                                    media['path'], (GRID_THUMB_W, GRID_THUMB_H),
                                    loop=media.get('loop', False))}
        elif grid_preview:
            grid_preview['player'].release()
            grid_preview = None

        # Draw current frame
        if grid_mode:
            grid_scroll = render_grid(screen, grid_cells, grid_scroll, grid_fonts,
                                      cur_active, flash_times, now, selected_index)
            draw_drop_flash(screen, grid_cells, grid_scroll, drop_flash, now)
            draw_grid_preview(screen, grid_cells, grid_scroll, grid_preview)
        else:
            draw_performance_frame(screen, state, target_size, now,
                                   args.display_mode)

        if now < latch_notice_until:
            notice_font = pygame.font.SysFont(None, 36)
            draw_text_outlined(
                screen, f"Latch: {'ON' if latch_enabled else 'OFF'}", notice_font,
                (24, 20), color=(255, 220, 120), outline_w=1
            )

        # Startup/help overlay draws on top of the current frame in performance
        # view only (grid view has its own controls header).
        if show_help and not grid_mode:
            draw_startup_help(screen, display_w, display_h)

        pygame.display.flip()
        clock.tick(60)

    stop_event.set()
    if state['video_player']:
        state['video_player'].release()
    if grid_preview:
        grid_preview['player'].release()
    pygame.quit()


if __name__ == "__main__":
    main()
