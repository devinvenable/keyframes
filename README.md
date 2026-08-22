# Keyframes

Real-time MIDI-triggered image and video display using pygame, mido, and OpenCV. Press a key on your MIDI controller — or your computer keyboard — and the corresponding media fills the screen. Designed for live performance and VJ setups.

## Windows download build

The Windows release is a self-contained folder: unzip `Keyframes_Windows.zip`,
then double-click `Keyframes.exe`.  No Python installation is needed.  Keep the
`images/` folder beside the executable and replace its starter media with your
own images and videos whenever you like.  `README.txt` inside the release gives
the same quick-start instructions.

Maintainers can build it on the Windows VM with:

```bash
scripts/build-windows.sh --clean
```

The driver pushes the current branch, builds it on the VM, verifies the frozen
app can load an image, decode a video, and initialize the RT-MIDI backend, then
copies `dist/Keyframes_Windows.zip` back to this checkout.

## How it works

- Maps MIDI notes (C2–B6, notes 36–99) to images and videos in the `images/` directory
- Drop any mix of images (`.png`, `.jpg`, `.jpeg`, `.bmp`) and videos (`.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`) into the folder
- Media files are automatically distributed evenly across the note range — videos are interleaved with images so they spread across all keys
- Every note triggers something — no dead keys
- By default, the last triggered image or video latches on screen; note-off does not clear it
- Every hit briefly cuts to black (40 ms by default), so rapid retriggers of one key read as distinct flashes
- Videos restart on every hit and freeze on their last frame until the next trigger
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

# Use hold-while-held behavior instead of the default latch
python main.py --no-latch

# Change the retrigger black gap (0 disables it)
python main.py --strobe-ms 60

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

White keys are on the letter rows, black keys (sharps/flats) are on the row above. By default, a hit latches its media until the next hit; press **L** to toggle latch mode live (a brief on-screen label confirms the mode). Run with `--no-latch` for hold-while-held behavior, where releasing a key stops it.

If a MIDI device is connected, both the device and keyboard work simultaneously.

### Grid / media-manager view

Press **Tab** to toggle between the performance display and a scrollable grid of
every media file. Each thumbnail is labeled with its one MIDI note, or `—` when
unmapped; unmapped thumbnails are dimmed. Videos are marked with a `VID` badge
and their first frame.

MIDI stays live in grid view: playing a note flashes its thumbnail, so you can
see at a glance which media is bound to which key. Scroll with **Up/Down**,
**PageUp/PageDown**, **Home/End**, or the **mouse wheel**. Press **Tab** again to
return to the performance view, or **Esc** to quit.

Each thumbnail maps to exactly one key or none. Click a thumbnail to select it —
the next computer-piano or incoming MIDI note maps to that media, steals the
note from its prior media, and deselects (one click = one remap). Clicking
empty grid space or leaving the grid deselects without remapping. Press
**Delete** or **Backspace** to unmap the selected media without deleting its
file. With nothing selected, playing keys only previews/flashes media and never
changes mappings.

**Drag-to-replace:** drag an image or video from your file manager
(Explorer/Finder) and drop it onto a grid cell to replace that cell's media *in
place*. The dropped file is copied into `images/` (if it isn't already there)
and takes over the cell: if the cell has a key, that key now triggers the new
file; if the cell is unmapped, the new file just fills the slot with no key. The
cell's **old file is deleted** from `images/` so no orphan cell is left behind —
dropped files are copies, so your original is the backup. The change is saved to
`mapping.json` and the media updates live — no restart. A green border flashes on
success; an unsupported file type or a drop that misses every cell flashes red
and is ignored (nothing copied or deleted).

## Media folder

Drop any images or videos into the `images/` directory — any filenames, any order. Supported formats:

- **Images**: `.png`, `.jpg`, `.jpeg`, `.bmp`
- **Videos**: `.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`

On a first launch, files are sorted and each receives one distinct key in order.
Videos are interleaved with images so they don't cluster together. Later files
take the next free key when one exists, otherwise remain unmapped.

### `mapping.json`

The note→file assignment is remembered in a sparse `mapping.json` manifest beside the `images/` folder (next to the executable in a packaged build). It is plain, human-readable JSON (`{"36": "sunrise.png"}`) you can hand-edit: only mapped notes appear. Each note and each media file can occur at most once. On launch, deleted files are removed; later-added files get the next free key if possible, otherwise remain visible but unmapped.

## Configuration

- `START_NOTE` and `NUM_KEYS` in `main.py` can be adjusted for your keyboard layout
- Multi-monitor aware — automatically picks a landscape display
- `--zoom-ring` gives each MIDI note its own 16-step repeat-hit cycle: first hit is normal size, then each hit on that note scales slightly larger until it wraps back to normal
- Latch mode is on by default, so short percussive MIDI notes still leave the last hit visible; use `--no-latch` or press **L** at runtime to return to note-off release behavior
- `--strobe-ms` controls the black retrigger gap (default `40`; `0` disables it)
