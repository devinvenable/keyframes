import argparse
import os
import queue
import sys
import threading

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
            if msg.type in ('note_on', 'note_off'):
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
        frame = cv2.resize(frame, self.target_size)
        surface = pygame.surfarray.make_surface(np.transpose(frame, (1, 0, 2)))
        self.last_surface = surface
        return surface

    def release(self):
        if self.cap:
            self.cap.release()
            self.cap = None


def process_midi_messages(msg_source, start_note, end_note, note_to_media, target_size,
                          current_state, channel=None):
    """Process MIDI messages and update current display state.
    Returns updated current_state dict with 'surface', 'video_player', 'note_active'.
    If channel is set, only messages on that channel are processed."""
    messages = []
    if isinstance(msg_source, queue.Queue):
        while not msg_source.empty():
            messages.append(msg_source.get_nowait())
    else:
        for msg in msg_source.iter_pending():
            messages.append(msg)

    for msg in messages:
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

            media = note_to_media.get(note)
            if media and media['type'] == 'video':
                current_state['video_player'] = VideoPlayer(media['path'], target_size)
                current_state['surface'] = None
                current_state['note_active'] = note
            elif media and media['type'] == 'image':
                current_state['surface'] = media['surface']
                current_state['note_active'] = note

        elif is_note_off and note == current_state['note_active']:
            # Stop video on note-off, go to black
            if current_state['video_player']:
                current_state['video_player'].release()
                current_state['video_player'] = None
            current_state['surface'] = None
            current_state['note_active'] = None

    return current_state


def select_midi_port(available_ports, port_filter=None):
    """Select a MIDI port. If port_filter is given, match by substring.
    Otherwise auto-select, preferring hardware ports over virtual ones."""
    if not available_ports:
        return None

    if port_filter:
        matches = [p for p in available_ports if port_filter.lower() in p.lower()]
        if matches:
            return matches[0]
        return None

    # Auto-select: prefer hardware ports (skip common virtual/software ports)
    virtual_keywords = ['through', 'virtual', 'midi through', 'rtpmidi']
    hardware = [p for p in available_ports
                if not any(kw in p.lower() for kw in virtual_keywords)]
    if hardware:
        return hardware[0]

    return available_ports[0]


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
    parser.add_argument('--windowed', '-w', action='store_true',
                        help="Run in a window instead of fullscreen")
    parser.add_argument('--size', type=str, default='1280x720', metavar='WxH',
                        help="Window size in windowed mode (default: 1280x720)")
    args = parser.parse_args()

    start_note = args.start_note
    num_keys = args.num_keys
    end_note = start_note + num_keys - 1

    pygame.init()

    if args.windowed:
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
    inport = None

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
        # Try to open a MIDI device, but don't require one (keyboard always works)
        inputs = mido.get_input_names()
        if inputs:
            port_name = select_midi_port(inputs, args.port)
            if port_name:
                inport = mido.open_input(port_name)
                print(f"MIDI input: {port_name}")
            else:
                print("No matching MIDI input found — using keyboard only.")
                print(f"  Available ports: {inputs}")
        else:
            print("No MIDI input devices found — using keyboard only.")

    print("Keyboard: Z-M (lower octave), Q-P (upper octave). ESC to quit.")

    state = {'surface': None, 'video_player': None, 'note_active': None}

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
                                      note_to_media, target_size, state, midi_channel)
        # Process live MIDI device messages
        if inport:
            state = process_midi_messages(inport, start_note, end_note,
                                          note_to_media, target_size, state, midi_channel)

        # Draw current frame
        if state['video_player']:
            frame_surface = state['video_player'].get_frame()
            if frame_surface:
                screen.blit(frame_surface, (0, 0))
            else:
                screen.fill((0, 0, 0))
        elif state['surface']:
            scaled = pygame.transform.scale(state['surface'], target_size)
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
