# Keyframes

Real-time MIDI-triggered image and video display using pygame, mido, and OpenCV. Press a key on your MIDI controller and the corresponding media fills the screen. Designed for live performance and VJ setups.

## How it works

- Maps MIDI notes (C2–B6, notes 36–99) to images and videos in the `images/` directory
- Drop any mix of images (`.png`, `.jpg`, `.jpeg`, `.bmp`) and videos (`.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`) into the folder
- Media files are automatically distributed evenly across the note range — videos are interleaved with images so they spread across all keys
- Every note triggers something — no dead keys
- Videos play back in real-time and stop immediately on note-off
- If a note is held past the end of a video, it freezes on the last frame
- Displays fullscreen on the first landscape monitor it finds
- 60 FPS render loop, hardware-accelerated

## Requirements

- Python 3 (any recent version — tested with 3.13)
- A MIDI input device (keyboard, controller, DAW output) — or use `--midi-file` to play back a `.mid` file
- `pip` (comes with Python on most systems)

## Setup

If you've never used Python before, follow these steps for your operating system.

### 1. Install Python

- **macOS**: Download from [python.org](https://www.python.org/downloads/) or run `brew install python` if you have Homebrew.
- **Windows**: Download from [python.org](https://www.python.org/downloads/). **Check "Add Python to PATH"** during installation.
- **Linux**: Python is usually pre-installed. If not: `sudo apt install python3 python3-venv python3-pip` (Debian/Ubuntu) or `sudo dnf install python3` (Fedora).

To verify it's installed, open a terminal (or Command Prompt on Windows) and run:

```bash
python3 --version
```

On Windows, use `python` instead of `python3` in all commands below.

### 2. Create a virtual environment

A virtual environment keeps this project's dependencies separate from the rest of your system. Run these commands from the project folder:

```bash
# macOS / Linux
python3 -m venv venv
source venv/bin/activate

# Windows (Command Prompt)
python -m venv venv
venv\Scripts\activate

# Windows (PowerShell)
python -m venv venv
venv\Scripts\Activate.ps1
```

You'll see `(venv)` at the start of your terminal prompt when the environment is active.

### 3. Install dependencies

With the virtual environment active:

```bash
pip install -r requirements.txt
```

This installs pygame, mido, python-rtmidi, opencv-python-headless, and numpy.

### 4. MIDI driver (Windows only)

Windows doesn't have built-in virtual MIDI support. If you want to use `test_midi.py` (the virtual test keyboard), install [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) first. macOS and Linux work natively.

## Usage

```bash
# Make sure your virtual environment is active first:
# macOS/Linux: source venv/bin/activate
# Windows: venv\Scripts\activate

# Live MIDI input (auto-detects first available device and landscape monitor)
python main.py

# Play back a MIDI file instead of live input
python main.py --midi-file path/to/song.mid

# Loop a MIDI file
python main.py --midi-file path/to/song.mid --loop

# Press ESC to quit
```

## Media folder

Drop any images or videos into the `images/` directory — any filenames, any order. Supported formats:

- **Images**: `.png`, `.jpg`, `.jpeg`, `.bmp`
- **Videos**: `.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`

Files are sorted and distributed evenly across the 64-note range. Videos are interleaved with images so they don't cluster together. The more files you add, the more variety per key.

## Testing

`test_midi.py` creates a virtual MIDI output that cycles through all notes. Use it to test without a physical controller:

```bash
# In one terminal — start the virtual keyboard
python test_midi.py

# In another terminal — run the display (it will auto-connect to "Virtual Keyboard")
python main.py
```

Requires a virtual MIDI driver on Windows (e.g., loopMIDI). Works natively on macOS/Linux.

## Configuration

- `START_NOTE` and `NUM_KEYS` in `main.py` can be adjusted for your keyboard layout
- Multi-monitor aware — automatically picks a landscape display
