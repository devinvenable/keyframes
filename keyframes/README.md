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

# Use KeyStep USB for notes/CC (practice without the TBOX rig)
python main.py --note-source usb

# Legacy input from all controllers, with cross-port note echo suppression
python main.py --note-source all

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

### Live bank state (for the live supervisor)

When `KEYFRAMES_BANK_STATE` names a file (set by `scripts/live.sh`),
Keyframes writes the active bank name there on every bank load — launch
bank and F5/F6 switches alike — so a crash-restart relaunches into the
bank that was live on stage. Off by default: no env var, no file.

### Live MIDI note source

`--note-source tbox` is the default: performance messages come from **TBOX
In 1** only, including KeyStep notes mirrored through DIN and other hardware
on the thru box. Some drivers label this input `TBOX ... Midi Out 1`; port 2
is excluded. Use `--note-source usb` for KeyStep USB, or `--note-source all`
for other controllers and the legacy multi-input behavior. Echo suppression
remains active as a safety net.

The selection covers notes, CC, pitch bend, and program changes. Clock and
transport still arrive from all opened ports; **ShowSync Cues** is always
exempt, including after a reconnect. Computer-keyboard and MIDI-file playback
are independent. `--port` still limits which hardware ports are opened.

If the requested source is absent or fails to open at startup, Keyframes
prints a warning and uses the other rig source. If neither is open, it warns
that hardware notes are unavailable; keyboard/cues still work, and other
controllers can be used with `--note-source all`. Selection is fixed until
inputs are reopened after a MIDI worker restart. Startup output and the MIDI sidecar record the requested source, actual
source, port name, and any fallback warning.

### MIDI I/O recovery and rollback

Live input defaults to `--midi-io process`: a helper owns MIDI enumeration,
open, reads, cue rescans, and close. The renderer receives the original MIDI
bytes through a local socket and applies the existing note/clock/cue routing.
This isolates native port-close deadlocks, including ones holding Python's
GIL, from the display and keyboard. Cue connections still refresh every five
seconds, including when ShowSync reuses the same port name.

A worker silent for two seconds is killed and restarted (startup allows ten
seconds). Hardware notes and cues can be lost during this recovery and the
usual startup drain; the current image/bank remains on screen. Recovery is
reported to the console and, when enabled, the MIDI sidecar as `midi_io`.
Quitting allows a quarter second for normal port closure before terminating
the helper. On Linux the helper also dies if `live.sh` terminates the renderer.

For emergency rollback, `--midi-io inproc` restores the previous direct-port
startup, polling, and cue rescan behavior, including its original close-stall
risk. With the live launcher, set:

```bash
LIVE_KEYFRAMES_ARGS="--midi-io inproc" scripts/live.sh songs/fullshow-set.yaml
```

MIDI-file playback does not start a helper in either mode.

### MIDI event log (take sidecar)

During `scripts/perform.sh` captures (which set `KEYFRAMES_MIDI_LOG`), or when
run manually with `--midi-log <path>`, Keyframes appends incoming MIDI
events from accepted sources to a JSON Lines sidecar — ground truth of the performance (which keys
fired when), and for sequenced material the clock stream *is* the beat grid, so
later edits never have to re-derive tempo from audio. Off by default: normal
playing writes no files.

One JSON object per line. The first line is a self-describing reference:

```json
{"event": "log_open", "epoch": 1759600000.123, "monotonic": 5123.456}
{"epoch": 1759600001.001, "monotonic": 5124.334, "port": "KeyStep 32", "type": "note_on", "channel": 0, "note": 60, "velocity": 100, "mapped": true}
```

- Every event carries `epoch` (wall clock) and `monotonic` timestamps plus the
  source `port` (`"keyboard"` for computer-keyboard notes). Timestamps are
  arrival times — USB/ALSA adds a few ms of latency, accepted by design.
- **Alignment contract:** event `epoch` minus the `.markers` sidecar's
  `recording_start` epoch = `t_rec`, seconds on the recorded video's timeline.
- Real note-ons (velocity > 0) carry `mapped`: whether the note currently
  triggers media (in range, on the listened channel, and mapped to a file).
- All message types are logged (`control_change`, `program_change`,
  `pitchwheel`, `clock`, ...). Clock ticks appear only when the connected
  sequencer actually sends MIDI clock, and can dominate the file (24/beat).
- A `note_source` startup record identifies the requested/effective source
  and selected ports. Ignored channel messages produce `note_source_filtered`
  summaries instead of raw events: counts by message type and one example,
  at most once per five seconds per port. Pending counts flush on clean close;
  a crash can lose ignored-source counts since the last summary.
- Crash-safe: performance events are flushed per line, so a killed process
  loses at most buffered clock ticks. Stale events drained at startup are
  never logged.

At take end, `perform.sh` derives a best-effort `<take>.mid`
(`scripts/midi_log_to_mid.py`): a type-0 standard MIDI file at a **fixed
arbitrary 120 BPM** (480 ticks/beat, so 1 tick = 1/960 s) with tick 0 at
recording start, for DAW/Blender import. The jsonl remains the ground truth.

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

A scene "beat" is *any* in-range note-on, mapped or not — a key with no
media still advances an active scene and clears a finished one (so playing
outside a bank's mapped note window can never leave a finished scene's held
frame stuck on screen), but only a mapped key can roll the activation gate,
since activation needs media to show. Unmapped keys also leave the normal
view untouched: whatever is on screen keeps showing (a playing video keeps
playing) — they never blank it.

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

Videos and animated GIFs play *live* inside scenes, through the same
VideoPlayer pipeline as the normal view: a GIF keeps looping, a video plays
once and freezes on its last frame, and playback is paced by the media's
own frame rate — scene motion (ring expansion, bar fades) stays wall-clock
smooth regardless. All four sweep bars always show the *same* synchronized
frame (one decode per render tick). A rings scene activated while a video
is on screen adopts that live player as its background, continuing from the
current playback position rather than restarting. Still images keep their
fully-cached zero-rebuild path, so all-image performance is unchanged. (A
video triggered *during* a sweep still only advances the beat — per design,
the activating media is the one that steps across the bars.) Scene config
lives in `scenes.json` beside `mapping.json` (it can't live inside
`mapping.json`, which is rewritten as a pure note→file manifest):

```json
{"enabled": true, "probability": 0.05, "allow": ["concentric-rings"]}
```

All keys are optional; a missing or malformed file means scenes are enabled
at the 5% default with every registered scene allowed. `allow` restricts the
activation picker to the listed scenes (`[]` = none may activate). New scenes
subclass `Scene` in `main.py` and register with `@register_scene`, carrying a
unique append-only `midi_id` — activation picks randomly among allowed scenes, and
the main loop only ever sees the one `active_scene` hook. A trigger that
ends the active scene falls straight through to the activation roll, so a
new scene can start on the very note that ended the old one — no one-frame
full-screen flash between back-to-back scenes.

## Overlays (periodic alpha titles)

Overlays are transparent title animations composited **on top of** whatever
is showing — the normal view *or* an active scene — never replacing either
and never touching scene/trigger logic. Unlike scenes, which are note-driven,
overlays run on the **wall clock**: after a random interval (45–120 s by
default) the next overlay appears, plays its animation a few loops (2–3 by
default), disappears, and the next interval starts. Variants rotate
round-robin in name order, or randomly per cycle with `shuffle`.

Overlays ship disabled. To enable: edit `overlays.json` and set
`"enabled": true`.

```json
{
  "enabled": false,
  "dir": "overlays",
  "fps": 30,
  "interval_min_s": 45,
  "interval_max_s": 120,
  "loops_min": 2,
  "loops_max": 3,
  "shuffle": false
}
```

All keys are optional; missing or invalid values fall back to the defaults
above. A bank may carry its own `overlays.json` (same fallback rule as
`scenes.json`); a bank switch adopts the new settings but never cancels a
showing already on screen.

Overlay media lives in `overlays/` (or `dir`, resolved relative to the app
folder): **each subdirectory is one variant, holding an RGBA PNG sequence**
sorted by filename (symlinked directories work — the six Clock Divider
titles are installed as symlinks to `generated/clockdivider/<variant>/png/`).
PNG sequences are the one reliable alpha source: pygame cannot decode ProRes
4444 and cv2 drops alpha on most video codecs. Frames composite fit-inside
at native aspect, centered, never cropped — square titles sit centered on a
16:9 screen, wide ones fill it edge to edge.

Performance: frames are decoded lazily on a 2-thread pool into a small
in-order ring buffer — nothing is preloaded (a naive preload is ~1.5 GB per
1080p variant) and resident decode memory is hard-capped at 160 MB (~66 MB
actual at 1080p). One thread decodes a 1080p RGBA PNG in ~36 ms, slower than
the 33 ms frame interval at 30 fps, but cv2 releases the GIL so two workers
sustain ~18 ms effective. The overlay is wall-clock paced at its own fps; a
frame the pool hasn't finished yet holds the previous one — the base layer
never waits on the decoder.

## Media folder

Drop any images or videos into the `images/` directory — any filenames, any order. Supported formats:

- **Images**: `.png`, `.jpg`, `.jpeg`, `.bmp`
- **Videos**: `.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`, `.gif` (animated GIFs loop while held)

On a first launch, files are sorted and each receives one distinct key in order.
Videos are interleaved with images so they don't cluster together. Later files
take the next free key when one exists, otherwise remain unmapped.

### `mapping.json`

The note→file assignment is remembered in a sparse `mapping.json` manifest beside the `images/` folder (next to the executable in a packaged build). It is plain, human-readable JSON (`{"36": "sunrise.png"}`) you can hand-edit: only mapped notes appear. Each note and each media file can occur at most once. On launch, deleted files are removed; later-added files get the next free key if possible, otherwise remain visible but unmapped.

## Media banks

A bank is a named folder containing media and its own note assignments:

```text
keyframes/                  # or the folder beside Keyframes.exe
  images/                   # original library: the implicit "default" bank
  mapping.json              # default bank assignments
  scenes.json               # global scene settings
  overlays.json             # global overlay settings
  overlays/                 # overlay variants (RGBA PNG sequence per subdir)
  banks/
    insect-war-aged/
      insect-war-03-tower-10s-aged.gif
      ...
      mapping.json          # this bank's assignments only
      scenes.json           # optional override of global scene settings
      overlays.json         # optional override of global overlay settings
```

Launch with `python main.py --bank insect-war-aged`. With no `--bank` flag
(or with `--bank default`), the original `images/` and `mapping.json` are used.
Bank names are folder names under `banks/`; `default` is reserved for the
original library. An unknown launch name reports the available names.

Press **F5** for the previous bank or **F6** for the next, in either performance
or grid view. The order is `default`, then named banks alphabetically, wrapping
at either end. A brief **Bank: name** overlay confirms the switch. These keys
do not overlap the computer piano. The folder list is refreshed on each switch.

Media, note assignments, thumbnails, and scene settings load before the new
bank becomes active. A load failure leaves the previous bank active and shows
an error. Switching clears grid selection, scrolling, previews, and repeat-hit
counts. Existing playback stays visible until the next trigger, and an active
scene keeps its media and runs to completion; new triggers resolve in the new
bank. Loading is synchronous, so a large bank can briefly pause input/rendering.

Grid assignment, unmapping, drag-to-replace, and automatic reconciliation all
use the **active bank's** media folder and `mapping.json`. Scene settings stay
in a separate `scenes.json`: mappings are always pure note-to-filename JSON.

## MIDI visual control (per-song banks and scenes)

Banks and scene settings can be driven over MIDI — ShowSync cues them per
song from the setlist, and a KeyStep's program-change buttons switch banks
live. A Program Change selects the bank (`0` = default, `1..N` = banks
sorted); CC 102/103/104/105 reset/enable/probability/allow-scene override the
active bank's `scenes.json` until the next reset. These messages are accepted
on **any** channel (notes still honour `--channel`), so keep other
PC-emitting gear off Keyframes' input port. Full message map, scene id table,
and setlist YAML syntax: [`docs/visual-control-midi.md`](../docs/visual-control-midi.md).
If the bank has no `scenes.json`, the global file applies. A bank can be empty
or contain unmapped media; use the grid to assign keys.

The included **insect-war-aged** bank contains nine looping animated GIFs on
notes **48–56**, playable with **Z S X D C V G B H**, in this order: tower, duel,
black-and-white loop, hover, loop, dogfight, feeding, push-in, charge. The source
clips are `generated/insect-war/*_aged.mp4` in the project checkout; they remain
unchanged. GIFs retain each clip's full duration and square aspect ratio at
480×480, 15 fps, with an optimized 256-color palette and infinite looping.
To reproduce a GIF from a source clip (use lowercase, hyphenated output names):

```bash
ffmpeg -i source_aged.mp4 -filter_complex \
  '[0:v]fps=15,scale=480:480:flags=lanczos,split[a][b];[a]palettegen=max_colors=256[p];[b][p]paletteuse=dither=sierra2_4a' \
  -loop 0 output-aged.gif
```

V1 switching uses the launch flag and hotkeys only. MIDI program-change bank
selection is deferred to a later version; ShowSync behavior is unchanged.

## Configuration

- `START_NOTE` and `NUM_KEYS` in `main.py` can be adjusted for your keyboard layout
- Multi-monitor aware — automatically picks a landscape display
- `--zoom-ring` gives each MIDI note its own 16-step repeat-hit cycle: first hit is normal size, then each hit on that note scales slightly larger until it wraps back to normal
- Latch mode is on by default, so short percussive MIDI notes still leave the last hit visible; use `--no-latch` or press **L** at runtime to return to note-off release behavior
