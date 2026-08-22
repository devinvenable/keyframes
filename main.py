import argparse
import json
import os
import queue
import shutil
import sys
import threading
import time
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

IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.bmp')
VIDEO_EXTS = ('.mp4', '.avi', '.mov', '.mkv', '.webm')

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
        ("     Supported: .png .jpg .jpeg .bmp .mp4 .avi .mov .mkv .webm", font, (140, 140, 140)),
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
        ("Tab    Grid manager: view, rearrange, replace media", font_small, (180, 180, 180)),
        ("Esc    Quit", font_small, (180, 180, 180)),
        ("", font_small, (180, 180, 180)),
        ("Press any key to start playing.", font, (255, 220, 120)),
        ("Press F1 or ? anytime to show this help again.", font_small, (140, 185, 225)),
    ]
    _blit_overlay_lines(screen, width, height, lines)


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
    """The original even-distribution: note -> filename across the note range.

    Used both to seed a fresh manifest and to fill any note a stored manifest
    leaves uncovered."""
    num_notes = end_note - start_note + 1
    n = len(ordered_files)
    if n == 0:
        return {}
    return {note: ordered_files[int(i * n / num_notes)]
            for i, note in enumerate(range(start_note, end_note + 1))}


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


def reconcile_mapping(stored, present_files, start_note, end_note):
    """Overlay a stored manifest on the auto-distribution seed.

    Rules:
      * A stored note keeps its filename while that file still exists on disk.
      * Notes with no (surviving) stored assignment fall back to the seed.
      * Files present on disk but referenced by no note are surfaced by taking
        over a duplicated, non-pinned slot, so newly-dropped media isn't lost.
      * Stored entries outside the active note range are preserved as long as
        their file still exists (so narrowing the range temporarily doesn't
        discard a user's pinned assignments).

    Returns a fresh ``{int note: str filename}`` mapping."""
    present = set(present_files)
    ordered = order_media_files(present_files)
    seed = seed_distribution(ordered, start_note, end_note)

    result = {}
    for note in range(start_note, end_note + 1):
        stored_name = stored.get(note)
        if stored_name in present:
            result[note] = stored_name
        elif note in seed:
            result[note] = seed[note]

    # Surface present files that no note points at by evicting a duplicated slot
    # that the user hasn't explicitly pinned in the stored manifest.
    referenced = set(result.values())
    counts = {}
    for name in result.values():
        counts[name] = counts.get(name, 0) + 1
    for new_name in ordered:
        if new_name in referenced:
            continue
        victim = None
        for note in range(start_note, end_note + 1):
            current = result.get(note)
            if current is None:
                victim = note
                break
            if counts.get(current, 0) > 1 and stored.get(note) != current:
                victim = note
                break
        if victim is None:
            break  # every note holds a distinct/pinned file; extras stay unshown
        old = result.get(victim)
        if old is not None:
            counts[old] -= 1
        result[victim] = new_name
        counts[new_name] = counts.get(new_name, 0) + 1
        referenced.add(new_name)

    # Keep valid out-of-range stored assignments so they survive this run.
    for note, name in stored.items():
        if not (start_note <= note <= end_note) and name in present:
            result[note] = name

    return result


def make_media_entry(name):
    """Build a single note-media object for a filename in ``images/``.

    Carries a ``name`` field so the live click-to-replace path can find and
    reuse an already-loaded object for the same file (preserving the grid's
    id()-based dedup) instead of decoding it a second time."""
    filepath = os.path.join(IMAGES_DIR, name)
    if os.path.splitext(name)[1].lower() in VIDEO_EXTS:
        return {'type': 'video', 'path': filepath, 'name': name}
    img = pygame.image.load(filepath).convert_alpha()
    return {'type': 'image', 'surface': img, 'name': name}


def load_media(start_note, end_note):
    """Build the note -> media mapping, honoring the persistent manifest.

    The manifest (``mapping.json``) is an overlay on top of the historical
    even-distribution seed: stored assignments win, holes are seeded, and the
    reconciled result is written back so it survives restarts and reflects the
    current contents of ``images/``."""
    all_files = list_media_files()
    if not all_files:
        return None

    stored = load_mapping()
    reconciled = reconcile_mapping(stored, all_files, start_note, end_note)
    if reconciled != stored:
        save_mapping(reconciled)

    # Only notes inside the active range drive playback; out-of-range entries are
    # preserved in the file but not loaded here.
    in_range = {note: name for note, name in reconciled.items()
                if start_note <= note <= end_note}

    # Load one media object per unique filename so notes that share a file share
    # the object (the grid view collapses cells by ``id(media)``).
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


class VideoPlayer:
    """Manages video playback for a single video file."""

    def __init__(self, path, target_size):
        self.path = path
        self.target_size = target_size
        self.cap = cv2.VideoCapture(path)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.last_surface = None
        self.finished = False

    def get_frame(self):
        """Read next frame and return as a pygame surface. Loops if video ends."""
        if self.finished:
            return self.last_surface

        ret, frame = self.cap.read()
        if not ret:
            # Video ended — freeze on last frame
            self.finished = True
            return self.last_surface

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # Crop-to-fill: scale to cover target, then center-crop
        th, tw = self.target_size[1], self.target_size[0]
        fh, fw = frame.shape[:2]
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


def zoom_surface_to_screen(surface, target_size, zoom_scale):
    """Scale a surface to fill the target area, optionally enlarging from center."""
    fitted = crop_to_fill(surface, target_size)
    if zoom_scale <= 1.0:
        return fitted

    zoomed_size = (
        max(1, int(round(target_size[0] * zoom_scale))),
        max(1, int(round(target_size[1] * zoom_scale))),
    )
    zoomed = pygame.transform.smoothscale(fitted, zoomed_size)
    x_offset = (zoomed_size[0] - target_size[0]) // 2
    y_offset = (zoomed_size[1] - target_size[1]) // 2
    return zoomed.subsurface((x_offset, y_offset, target_size[0], target_size[1]))


def process_midi_messages(msg_source, start_note, end_note, note_to_media, target_size,
                          current_state, channel=None, clock_tracker=None,
                          min_note_beats=None, zoom_ring_enabled=False,
                          note_hit_counts=None):
    """Process MIDI messages and update current display state.
    Returns updated current_state dict with 'surface', 'video_player', 'note_active'.
    If channel is set, only messages on that channel are processed.
    If min_note_beats is set, note-off is deferred until minimum duration elapses."""
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
            # Stop any current video
            if current_state['video_player']:
                current_state['video_player'].release()
                current_state['video_player'] = None

            # Clear any pending hold
            current_state['hold_until'] = None

            media = note_to_media.get(note)
            if media and media['type'] == 'video':
                current_state['zoom_scale'] = 1.0
                current_state['video_player'] = VideoPlayer(media['path'], target_size)
                current_state['surface'] = None
                current_state['note_active'] = note
                current_state['note_on_time'] = now
            elif media and media['type'] == 'image':
                current_state['zoom_scale'] = get_zoom_ring_scale(
                    note, note_hit_counts, zoom_ring_enabled
                )
                current_state['surface'] = media['surface']
                current_state['note_active'] = note
                current_state['note_on_time'] = now

        elif is_note_off and note == current_state['note_active']:
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
    if current_state.get('hold_until') and now >= current_state['hold_until']:
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

    cap = cv2.VideoCapture(media['path'])
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
    """Collapse note_to_media into one cell per unique media item, recording
    every note that maps to it. Cells are ordered by their first (lowest) note."""
    cells = []
    seen = {}  # id(media) -> index into cells
    for note in sorted(note_to_media):
        media = note_to_media[note]
        key = id(media)
        if key in seen:
            cells[seen[key]]['notes'].append(note)
        else:
            seen[key] = len(cells)
            cells.append({
                'media': media,
                'type': media['type'],
                'thumb': make_thumbnail(media, thumb_size),
                'notes': [note],
            })
    return cells


def format_notes(notes):
    """Compact label for the note(s) a cell maps to (e.g. '36' or '36-39')."""
    if len(notes) == 1:
        return str(notes[0])
    return f"{min(notes)}-{max(notes)}"


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


def render_grid(screen, cells, scroll_y, fonts, active_note, flash_times, now):
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

        hl = cell_highlight(cell, active_note, flash_times, now)
        if hl > 0:
            border = int(2 + 4 * hl)
            color = (255, int(60 + 180 * hl), 40)
            pygame.draw.rect(screen, color,
                             (x - 2, y - 2, GRID_THUMB_W + 4, GRID_THUMB_H + 4),
                             border)

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
              f"Drag a thumbnail onto another to swap   Drop a file to replace   "
              f"Ctrl+Z: undo   Tab: performance view   Wheel: scroll   Esc: quit")
    draw_text_outlined(screen, header, fonts['header'], (GRID_PAD, 15),
                       color=(230, 230, 230), outline_w=1)

    return scroll_y


GRID_DROP_FLASH = 0.6  # seconds a drop-result border lingers


def supported_media_file(path):
    """True if ``path`` has a supported image/video extension."""
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS + VIDEO_EXTS


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


def apply_drop(filepath, cell, note_to_media):
    """Reassign one grid cell's notes to a dropped media file.

    Copies the file into ``images/`` (if needed), persists the reassignment
    through the shared mapping (load_mapping/save_mapping — never touching
    mapping.json directly), and live-updates ``note_to_media`` in place reusing
    any already-loaded object for the file. Returns True on success, or False
    for an unsupported file type (caller flashes red). The caller rebuilds the
    grid cells afterwards so the new thumbnail appears."""
    if not supported_media_file(filepath):
        return False
    name = import_dropped_file(filepath)
    notes = list(cell['notes'])
    mapping = load_mapping()
    for note in notes:
        mapping[note] = name
    save_mapping(mapping)
    reassign_cell_media(note_to_media, notes, name)
    return True


def swap_cell_mapping(mapping, notes_a, name_a, notes_b, name_b):
    """Swap two cells' note->filename entries in a mapping dict, in place.

    Every note that backed ``name_a`` now points at ``name_b`` and vice versa.
    A cell can back multiple notes (a shared file), so this swaps *all* notes of
    each side, mirroring how apply_drop reassigns cell['notes'] together.
    Returns the same dict for convenience."""
    for note in notes_a:
        mapping[note] = name_b
    for note in notes_b:
        mapping[note] = name_a
    return mapping


def swap_cells_media(note_to_media, notes_a, media_a, notes_b, media_b):
    """Swap two cells' live media objects across their notes, in place.

    Takes the already-loaded objects (``cells[i]['media']``) directly and moves
    each onto the other side's notes, so the grid's id()-based dedup keeps one
    cell per file — no re-decode, no second object for a file still on screen.
    Captures happen at the call site (both objects passed in) so neither is lost
    when the first assignment removes the last note referencing it."""
    for note in notes_a:
        note_to_media[note] = media_b
    for note in notes_b:
        note_to_media[note] = media_a


def apply_swap(cell_a, cell_b, note_to_media):
    """Swap which notes two grid cells map to: rearrange by manifest edit.

    Persists the swap through the shared mapping (load_mapping/save_mapping —
    never touching mapping.json directly) and live-updates ``note_to_media`` in
    place, reusing both already-loaded objects. Returns True on a real swap, or
    False when the two cells are the same (a no-op drop onto self). The caller
    rebuilds the grid cells afterwards so the moved thumbnails appear."""
    if cell_a is cell_b:
        return False
    notes_a = list(cell_a['notes'])
    notes_b = list(cell_b['notes'])
    name_a = cell_a['media']['name']
    name_b = cell_b['media']['name']
    mapping = load_mapping()
    swap_cell_mapping(mapping, notes_a, name_a, notes_b, name_b)
    save_mapping(mapping)
    swap_cells_media(note_to_media, notes_a, cell_a['media'],
                     notes_b, cell_b['media'])
    return True


def draw_drop_flash(screen, cells, scroll_y, drop_flash, now):
    """Draw the success/failure border for the most recent drop, if still live.

    Green = the cell was reassigned; red = the drop was rejected (unsupported
    type or landed off any cell). Located via the same grid_layout() the drop
    hit-test used, so the flash lands exactly on the cell that was targeted."""
    if not drop_flash or now >= drop_flash['until']:
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


GRID_DRAG_THRESHOLD = 6  # pixels of travel before a mouse-down becomes a drag


def draw_drag_feedback(screen, cells, scroll_y, drag, mouse_pos):
    """Draw the in-progress rearrange: highlight the drop target and float a
    ghost of the dragged thumbnail under the cursor.

    Uses the same grid_layout()/grid_cell_at() the drop uses, so the highlighted
    target is exactly the cell the release will act on. Only draws once the
    drag has actually moved (a plain click shows nothing)."""
    if not drag or not drag.get('moved'):
        return
    mx, my = mouse_pos
    target = grid_cell_at(cells, scroll_y, screen.get_size(), mouse_pos)
    if target is not None and target != drag['from_index']:
        layout = grid_layout(len(cells), scroll_y, screen.get_size())
        x, y = cell_rect(target, layout)
        pygame.draw.rect(screen, (90, 170, 255),
                         (x - 3, y - 3, GRID_THUMB_W + 6, GRID_THUMB_H + 6), 4)
    ghost = drag['thumb'].copy()
    ghost.set_alpha(180)
    screen.blit(ghost, (mx - GRID_THUMB_W // 2, my - GRID_THUMB_H // 2))


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
    """Exercise the shipped image, video, and RT-MIDI backend without hardware."""
    image_files = sorted(Path(IMAGES_DIR).glob('*.png'))
    video_files = sorted(Path(IMAGES_DIR).glob('*.mp4'))
    if not image_files or not video_files:
        raise RuntimeError('Packaging smoke test needs one .png and one .mp4 in images/.')

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

        # This import and enumeration load the dynamically selected mido RT-MIDI
        # backend.  No input device is required for either operation.
        import mido.backends.rtmidi  # noqa: F401
        mido.get_input_names()
    finally:
        pygame.quit()

    print('Packaging smoke test passed: image, video, and RT-MIDI backend are available.')


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
    parser.add_argument('--bpm', type=float, default=DEFAULT_BPM,
                        help=f"Fallback BPM when no MIDI clock is present (default: {DEFAULT_BPM})")
    parser.add_argument('--zoom-ring', action='store_true',
                        help="Give each note a 16-step zoom ring: repeated hits on the same "
                             "note grow slightly larger before wrapping to normal size")
    parser.add_argument('--windowed', '-w', action='store_true',
                        help="Run in a window instead of fullscreen")
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

    if args.windowed:
        if args.size.lower() in SIZE_PRESETS:
            w, h = SIZE_PRESETS[args.size.lower()]
        else:
            w, h = (int(d) for d in args.size.split('x'))
        screen = pygame.display.set_mode((w, h), pygame.RESIZABLE)
        display_w, display_h = w, h
    else:
        display_index, display_w, display_h = choose_landscape_display()
        flags = pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF
        screen = pygame.display.set_mode((display_w, display_h), flags, display=display_index)
        pygame.mouse.set_visible(False)

    pygame.display.set_caption("Keyframes")

    target_size = (display_w, display_h)

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

    print("Keyboard: Z-M (lower octave), Q-P (upper octave). ESC to quit.")
    print("Tab: toggle grid/media-manager view (Up/Down or mouse wheel to scroll).")
    print("F1 or ?: show the on-screen help overlay again.")

    state = {'surface': None, 'video_player': None, 'note_active': None,
             'note_on_time': None, 'hold_until': None, 'zoom_scale': 1.0}
    note_hit_counts = {}

    # Startup help overlay: shown on launch (performance view, media present),
    # dismissed on the first note played, reshowable via F1/?.
    show_help = True

    # Grid / media-manager view state
    grid_mode = False
    grid_cells = None  # built lazily the first time the grid is opened
    grid_scroll = 0
    flash_times = {}  # note -> monotonic time it was last triggered
    drop_flash = None  # {'note', 'until', 'ok'} border feedback for last drop
    grid_drag = None  # {'from_index', 'thumb', 'start', 'moved'} in-grid rearrange
    undo_stack = []   # snapshots {'mapping', 'note_to_media'} for Ctrl+Z
    prev_active = None
    grid_fonts = {
        'note': pygame.font.SysFont(None, 40),
        'small': pygame.font.SysFont(None, 26),
        'header': pygame.font.SysFont(None, 30),
    }

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
                elif is_help_reshow_key(event):
                    # Reshow the startup help overlay. Handled ahead of
                    # KEY_TO_NOTE so F1/? never doubles as a played note; it
                    # dismisses again on the next note. Ignored in grid view,
                    # which has its own on-screen controls header.
                    if not grid_mode:
                        show_help = update_help_visibility(show_help, reshow_key=True)
                elif event.key == pygame.K_TAB:
                    grid_mode = not grid_mode
                    if grid_mode and grid_cells is None:
                        grid_cells = build_grid_cells(
                            note_to_media, (GRID_THUMB_W, GRID_THUMB_H))
                    grid_scroll = 0
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
                elif (grid_mode and event.key == pygame.K_z
                      and event.mod & pygame.KMOD_CTRL and undo_stack):
                    # Undo the last rearrange: restore the mapping and the live
                    # note->media assignments from before the swap. Checked ahead
                    # of KEY_TO_NOTE so Ctrl+Z isn't also played as note 48.
                    snap = undo_stack.pop()
                    save_mapping(snap['mapping'])
                    note_to_media.clear()
                    note_to_media.update(snap['note_to_media'])
                    grid_cells = build_grid_cells(
                        note_to_media, (GRID_THUMB_W, GRID_THUMB_H))
                    print("Undo: reverted last rearrange")
                elif event.key in KEY_TO_NOTE:
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
                # Begin a potential in-grid rearrange. Not a drag yet — it only
                # becomes one once the cursor travels past GRID_DRAG_THRESHOLD,
                # so a plain click never swaps anything.
                idx = grid_cell_at(grid_cells, grid_scroll,
                                   screen.get_size(), event.pos)
                if idx is not None:
                    grid_drag = {'from_index': idx,
                                 'thumb': grid_cells[idx]['thumb'],
                                 'start': event.pos, 'moved': False}
            elif event.type == pygame.MOUSEMOTION and grid_drag:
                sx, sy = grid_drag['start']
                if (abs(event.pos[0] - sx) + abs(event.pos[1] - sy)
                        > GRID_DRAG_THRESHOLD):
                    grid_drag['moved'] = True
            elif (event.type == pygame.MOUSEBUTTONUP and event.button == 1
                  and grid_drag):
                # Drop the dragged thumbnail: if it lands on a different cell,
                # swap which notes the two cells map to (persisted via the shared
                # mapping) and rebuild so both moved thumbnails appear.
                if grid_drag['moved'] and grid_cells:
                    target = grid_cell_at(grid_cells, grid_scroll,
                                          screen.get_size(), event.pos)
                    from_idx = grid_drag['from_index']
                    if target is not None and target != from_idx:
                        cell_a = grid_cells[from_idx]
                        cell_b = grid_cells[target]
                        undo_stack.append({
                            'mapping': dict(load_mapping()),
                            'note_to_media': dict(note_to_media),
                        })
                        if apply_swap(cell_a, cell_b, note_to_media):
                            grid_cells = build_grid_cells(
                                note_to_media, (GRID_THUMB_W, GRID_THUMB_H))
                            print(f"Rearranged: notes "
                                  f"{format_notes(cell_a['notes'])} <-> "
                                  f"{format_notes(cell_b['notes'])}")
                            drop_flash = {'note': cell_b['notes'][0], 'ok': True,
                                          'until': time.monotonic() + GRID_DROP_FLASH}
                        else:
                            undo_stack.pop()  # no-op swap, nothing to undo
                grid_drag = None
            elif event.type == pygame.DROPFILE and grid_mode and grid_cells:
                # Native drag-and-drop: reassign the cell under the cursor to the
                # dropped media file (copy into images/, persist via the mapping,
                # reload live). Ignore drops outside grid view or off any cell.
                idx = grid_cell_at(grid_cells, grid_scroll,
                                   screen.get_size(), pygame.mouse.get_pos())
                if idx is not None:
                    cell = grid_cells[idx]
                    flash_note = cell['notes'][0]
                    ok = apply_drop(event.file, cell, note_to_media)
                    if ok:
                        grid_cells = build_grid_cells(
                            note_to_media, (GRID_THUMB_W, GRID_THUMB_H))
                        print(f"Replaced note(s) {format_notes(cell['notes'])} "
                              f"-> {os.path.basename(event.file)}")
                    else:
                        print(f"Ignored unsupported drop: {event.file}")
                    drop_flash = {'note': flash_note, 'ok': ok,
                                  'until': time.monotonic() + GRID_DROP_FLASH}

        # Process keyboard/file messages from queue
        state = process_midi_messages(msg_queue, start_note, end_note,
                                      note_to_media, target_size, state, midi_channel,
                                      clock_tracker, min_note_beats, args.zoom_ring,
                                      note_hit_counts)
        # Process live MIDI device messages
        for inport in inports:
            state = process_midi_messages(inport, start_note, end_note,
                                          note_to_media, target_size, state, midi_channel,
                                          clock_tracker, min_note_beats, args.zoom_ring,
                                          note_hit_counts)

        # Track note triggers for the grid's flash highlight (works in both views)
        now = time.monotonic()
        cur_active = state['note_active']
        note_started = cur_active is not None and cur_active != prev_active
        if note_started:
            flash_times[cur_active] = now
        prev_active = cur_active

        # Dismiss the startup help overlay the moment a note is played. This
        # covers both keyboard piano keys and incoming MIDI notes uniformly,
        # since both surface here as a newly-active note.
        show_help = update_help_visibility(show_help, note_started=note_started)

        # Draw current frame
        if grid_mode:
            grid_scroll = render_grid(screen, grid_cells, grid_scroll, grid_fonts,
                                      cur_active, flash_times, now)
            draw_drop_flash(screen, grid_cells, grid_scroll, drop_flash, now)
            draw_drag_feedback(screen, grid_cells, grid_scroll, grid_drag,
                               pygame.mouse.get_pos())
        elif state['video_player']:
            frame_surface = state['video_player'].get_frame()
            if frame_surface:
                screen.blit(
                    zoom_surface_to_screen(frame_surface, target_size, state['zoom_scale']),
                    (0, 0)
                )
            else:
                screen.fill((0, 0, 0))
        elif state['surface']:
            scaled = zoom_surface_to_screen(state['surface'], target_size, state['zoom_scale'])
            screen.blit(scaled, (0, 0))
        else:
            screen.fill((0, 0, 0))

        # Startup/help overlay draws on top of the current frame in performance
        # view only (grid view has its own controls header).
        if show_help and not grid_mode:
            draw_startup_help(screen, display_w, display_h)

        pygame.display.flip()
        clock.tick(60)

    stop_event.set()
    if state['video_player']:
        state['video_player'].release()
    pygame.quit()


if __name__ == "__main__":
    main()
