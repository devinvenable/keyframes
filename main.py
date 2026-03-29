import argparse
import os
import queue
import sys
import threading
import time

import cv2
import numpy as np
import pygame
import mido

# Default note range for a 64-key keyboard
DEFAULT_START_NOTE = 36  # C2
DEFAULT_NUM_KEYS = 64

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(SCRIPT_DIR, 'images')

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

    y = height // 2 - len(lines) * 20
    for text, f, color in lines:
        if text:
            rendered = f.render(text, True, color)
            screen.blit(rendered, (width // 2 - rendered.get_width() // 2, y))
        y += f.get_height() + 8

    pygame.display.flip()

    # Wait for ESC or quit
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return


def load_media(start_note, end_note):
    """Load all media files and distribute them evenly across the note range.
    Videos are interleaved with images so they spread across the full range."""
    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR)

    all_files = [f for f in os.listdir(IMAGES_DIR)
                 if f.lower().endswith(IMAGE_EXTS + VIDEO_EXTS)]

    if not all_files:
        return None

    # Separate images and videos, then interleave videos evenly among images
    images = sorted(f for f in all_files if f.lower().endswith(IMAGE_EXTS))
    videos = sorted(f for f in all_files if f.lower().endswith(VIDEO_EXTS))

    media_files = list(images)
    if videos:
        interval = max(1, len(media_files) // (len(videos) + 1))
        for vi, v in enumerate(videos):
            insert_pos = min(interval * (vi + 1) + vi, len(media_files))
            media_files.insert(insert_pos, v)

    # Build list of loaded media
    media_list = []
    for f in media_files:
        filepath = os.path.join(IMAGES_DIR, f)
        ext = os.path.splitext(f)[1].lower()
        if ext in VIDEO_EXTS:
            media_list.append({'type': 'video', 'path': filepath})
        else:
            img = pygame.image.load(filepath).convert_alpha()
            media_list.append({'type': 'image', 'surface': img})

    # Distribute evenly across the note range
    num_notes = end_note - start_note + 1
    note_to_media = {}
    for i, note in enumerate(range(start_note, end_note + 1)):
        media_index = int(i * len(media_list) / num_notes)
        note_to_media[note] = media_list[media_index]

    num_videos = sum(1 for m in note_to_media.values() if m['type'] == 'video')
    print(f"Loaded {len(media_list)} media files ({len(videos)} videos), mapped across notes {start_note}-{end_note}")
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
    parser.add_argument('--size', type=str, default='1280x720', metavar='WxH|PRESET',
                        help="Window size: WxH or preset name — "
                             "hd (1920x1080), 4k (3840x2160), "
                             "tiktok (1080x1920), tiktok-sm (720x1280), "
                             "square (1080x1080), ig-story (1080x1920), "
                             "reel (1080x1350) (default: 1280x720)")
    args = parser.parse_args()

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

    state = {'surface': None, 'video_player': None, 'note_active': None,
             'note_on_time': None, 'hold_until': None, 'zoom_scale': 1.0}
    note_hit_counts = {}

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
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key in KEY_TO_NOTE:
                    note = KEY_TO_NOTE[event.key]
                    msg_queue.put(mido.Message('note_on', note=note, velocity=100))
            elif event.type == pygame.KEYUP:
                if event.key in KEY_TO_NOTE:
                    note = KEY_TO_NOTE[event.key]
                    msg_queue.put(mido.Message('note_off', note=note, velocity=0))

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

        # Draw current frame
        if state['video_player']:
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

        pygame.display.flip()
        clock.tick(60)

    stop_event.set()
    if state['video_player']:
        state['video_player'].release()
    pygame.quit()


if __name__ == "__main__":
    main()
