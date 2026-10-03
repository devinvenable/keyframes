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
keyframes/scripts/build-windows.sh --clean   # from the repo root
```

The driver pushes the current branch, builds it on the VM, verifies the frozen
app can load an image, decode a video, and initialize the RT-MIDI backend, then
copies `keyframes/dist/Keyframes_Windows.zip` back to this checkout.

## How it works

- Maps MIDI notes (C2–B6, notes 36–99) to images and videos in the `images/` directory
- Drop any mix of images (`.png`, `.jpg`, `.jpeg`, `.bmp`) and videos (`.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`) into the folder
- Media files are automatically distributed evenly across the note range — videos are interleaved with images so they spread across all keys
- Every note triggers something — no dead keys
- By default, the last triggered image or video latches on screen; note-off does not clear it
- Hitting the *same* key again flips its still image to a colour negative (and back), so rapid retriggers of one key read as a strobing invert; different notes swap cleanly. Videos restart on retrigger and are left unaltered
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

## Scenes

Scenes are pre-configured, reusable playback templates that occasionally take
over presentation of the triggered media instead of the normal full-screen
flash. On any media-triggering note-on there is a small random chance (5% by
default) that a scene activates; once active it runs to completion, then
disappears and normal full-screen behavior resumes with the latest trigger.

**Four-bar sweep** (the first scene): the screen divides into 4 full-height
vertical bars and the image from the note that activated the scene steps
across them — the *same* image, one bar per beat, where a "beat" is simply
the next note-on trigger (no MIDI clock needed). Each bar shows a center
crop-to-fill of the image at the bar's aspect ratio (cropped, never
squeezed). When a bar's successor appears, the previous bar fades to white
over ~1 second; the trigger after the fourth bar starts the final fade, and
the scene ends when it completes.

Two variants of the sweep are registered alongside it, plus the concentric
rings scene below (activation picks randomly among all four):

**Four-bar sweep (black)**: identical mechanics, but bars fade to *black*
instead of white — same template, different fade target color.

**Four-bar sweep (tinted)**: each bar's crop gets a per-bar color tint,
multiplied over the image (`BLEND_MULT`) — a duotone look on black-and-white
sources, a palette shift on color ones. The tint always applies, to any
source image. The default tint list is red, green, blue, untinted — bar 4
shows the natural image as the payoff. The list is a template parameter
(`BAR_TINTS` on the scene class), so other combinations are a one-line
subclass. Bars fade to white, as in the original.

**Concentric rings**: expanding concentric rings — a dartboard — act as a
per-pixel mask between two full-screen images. Even rings show the
*foreground* (the activating note's image), odd rings show the *background*
(whatever was on screen when the scene activated, so the new image tunnels
in through the old; black if nothing was displayed). Rings expand outward
continuously on wall-clock time — existing rings grow past the screen edge
while new ones are born at center — reading as motion *into* the scene.
Every note-on beat swaps foreground and background for a punchy per-beat
inversion. After 8 beats the scene ends *on* that 8th beat with a hard cut
to that trigger's media full-screen: the cut itself is the final punch.
There is deliberately no timed exit fade — the sweep's wall-clock fade tail
reads as a pause during fast playing, and a beat-locked cut avoids that
entirely. Ring thickness (default 1/10 screen height), expansion speed
(default half a screen height per second) and beat count are template
parameters on `ConcentricRingsScene` (`RING_THICKNESS_FRACTION`,
`EXPANSION_SPEED_FRACTION`, `BEATS_TO_LIVE`).

Simplifications in this first version: if a *video* note activates a scene,
its first frame is used as the scene's still (a video triggered *during* a
scene only advances the beat — per design, the activating image is the one
that steps across the bars, so no per-trigger frame is shown). Scene config
lives in `scenes.json` beside `mapping.json` (it can't live inside
`mapping.json`, which is rewritten as a pure note→file manifest):

```json
{"enabled": true, "probability": 0.05}
```

Both keys are optional; a missing or malformed file means scenes are enabled
at the 5% default. New scenes subclass `Scene` in `main.py` and register with
`@register_scene` — activation picks randomly among registered scenes, and
the main loop only ever sees the one `active_scene` hook. A trigger that
ends the active scene falls straight through to the activation roll, so a
new scene can start on the very note that ended the old one — no one-frame
full-screen flash between back-to-back scenes.

## Media folder

Drop any images or videos into the `images/` directory — any filenames, any order. Supported formats:

- **Images**: `.png`, `.jpg`, `.jpeg`, `.bmp`
- **Videos**: `.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`, `.gif` (animated GIFs loop while held)

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
