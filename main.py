import argparse
import os
import queue
import sys
import threading

import cv2
import numpy as np
import pygame
import mido

# Configure the note range for your 64-key keyboard
START_NOTE = 36  # C2
NUM_KEYS = 64
END_NOTE = START_NOTE + NUM_KEYS - 1  # inclusive

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(SCRIPT_DIR, 'images')

IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.bmp')
VIDEO_EXTS = ('.mp4', '.avi', '.mov', '.mkv', '.webm')


def load_media(start_note, end_note):
    """Load all media files and distribute them evenly across the note range.
    Videos are interleaved with images so they spread across the full range."""
    all_files = [f for f in os.listdir(IMAGES_DIR)
                 if f.lower().endswith(IMAGE_EXTS + VIDEO_EXTS)]

    if not all_files:
        print("No media files found in images/ directory.")
        sys.exit(1)

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


def choose_midi_input():
    """Attempt to choose a MIDI input. On Mac/Linux, this may need adjustment."""
    inputs = mido.get_input_names()
    if not inputs:
        print("No MIDI input devices found.")
        sys.exit(1)
    return mido.open_input(inputs[0])


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
                          current_state):
    """Process MIDI messages and update current display state.
    Returns updated current_state dict with 'surface', 'video_player', 'note_active'."""
    messages = []
    if isinstance(msg_source, queue.Queue):
        while not msg_source.empty():
            messages.append(msg_source.get_nowait())
    else:
        for msg in msg_source.iter_pending():
            messages.append(msg)

    for msg in messages:
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


def main():
    parser = argparse.ArgumentParser(description="MIDI Note Image Display")
    parser.add_argument('--midi-file', '-f', help="Path to a MIDI file to play back")
    parser.add_argument('--loop', '-l', action='store_true', help="Loop MIDI file playback")
    args = parser.parse_args()

    pygame.init()

    # Attempt to pick a landscape display
    display_index, display_w, display_h = choose_landscape_display()

    # Attempt a hardware-accelerated fullscreen display on chosen monitor
    flags = pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF
    screen = pygame.display.set_mode((display_w, display_h), flags, display=display_index)
    pygame.mouse.set_visible(False)
    pygame.display.set_caption("MIDI Note Image Display")

    target_size = (display_w, display_h)

    # Load media
    note_to_media = load_media(START_NOTE, END_NOTE)

    # Set up MIDI source: file playback or live input
    msg_queue = queue.Queue()
    stop_event = threading.Event()

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
        msg_source = msg_queue
    else:
        msg_source = choose_midi_input()

    state = {'surface': None, 'video_player': None, 'note_active': None}

    clock = pygame.time.Clock()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

        state = process_midi_messages(msg_source, START_NOTE, END_NOTE,
                                      note_to_media, target_size, state)

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
