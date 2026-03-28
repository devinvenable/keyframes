# Keyframes

Real-time MIDI-triggered image and video display using pygame, mido, and OpenCV. Press a key on your MIDI controller — or your computer keyboard — and the corresponding media fills the screen. Designed for live performance and VJ setups.

## How it works

- Maps MIDI notes (C2–B6, notes 36–99) to images and videos in the `images/` directory
- Drop any mix of images (`.png`, `.jpg`, `.jpeg`, `.bmp`) and videos (`.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`) into the folder
- Media files are automatically distributed evenly across the note range — videos are interleaved with images so they spread across all keys
- Every note triggers something — no dead keys
- Videos play back in real-time and stop immediately on note-off
- If a note is held past the end of a video, it freezes on the last frame
- Displays fullscreen on the first landscape monitor it finds
- 60 FPS render loop, hardware-accelerated
- No MIDI hardware required — built-in computer keyboard works as a piano

## Requirements

- Python 3 (any recent version — tested with 3.13)
- `pip` (comes with Python on most systems)
- Optional: a MIDI input device (keyboard, controller, DAW output)

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

## Usage

```bash
# Make sure your virtual environment is active first:
# macOS/Linux: source venv/bin/activate
# Windows: venv\Scripts\activate

# Run the display (auto-detects MIDI devices and landscape monitor)
python main.py

# Play back a MIDI file
python main.py --midi-file path/to/song.mid

# Loop a MIDI file
python main.py --midi-file path/to/song.mid --loop

# Listen on a specific MIDI channel only (1-16)
python main.py --channel 1

# Run in a window instead of fullscreen
python main.py --windowed

# Enable per-note zoom ring (16 repeat-hit positions)
python main.py --zoom-ring

# Custom window size
python main.py --windowed --size 1920x1080

# Press ESC to quit
```

### Computer keyboard controls

No MIDI hardware needed — your computer keyboard works as a piano:

```
Upper octave (C4-E5):
 2 3   5 6 7   9 0
Q W E R T Y U I O P

Lower octave (C3-B3):
 S D   G H J
Z X C V B N M
```

White keys are on the letter rows, black keys (sharps/flats) are on the row above. Hold a key to sustain, release to stop.

If a MIDI device is connected, both the device and keyboard work simultaneously.

## Media folder

Drop any images or videos into the `images/` directory — any filenames, any order. Supported formats:

- **Images**: `.png`, `.jpg`, `.jpeg`, `.bmp`
- **Videos**: `.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`

Files are sorted and distributed evenly across the 64-note range. Videos are interleaved with images so they don't cluster together. The more files you add, the more variety per key.

## Configuration

- `START_NOTE` and `NUM_KEYS` in `main.py` can be adjusted for your keyboard layout
- Multi-monitor aware — automatically picks a landscape display
- `--zoom-ring` gives each MIDI note its own 16-step repeat-hit cycle: first hit is normal size, then each hit on that note scales slightly larger until it wraps back to normal
