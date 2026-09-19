# showsync

Live-performance backing-track player and MIDI clock master for Devin and
David's live show. Python v1 implementation with a pygame performance dashboard.

## What it does

showsync plays a set's backing tracks end-to-end as one continuous performance
and, while playing, acts as the MIDI clock master so external hardware (KeyStep,
modular sequencers) stays tempo-locked for live playing over the tracks.

## Requirements

### Setlist configuration

The configuration is a setlist: an ordered list of audio files — songs recorded
at different BPMs — each annotated with:

- its BPM, and
- its tempo-change points (positions within the file where the tempo changes).

showsync is DAW-agnostic: it never reads DAW metadata. Devin records in Logic
on the Mac; David records at his house on Windows (wav or mp3, no Logic). The
one requirement on any source: rhythmic material must be recorded to a
metronome at a declared BPM — that BPM goes in the setlist, and the MIDI clock
is only as true as it. Beatless/ambient material is exempt. Fitting a tempo
map to a freely-recorded file is deferred alongside time-stretching.

### Playback

- Plays the setlist's audio files end-to-end as one continuous set.
- While playing, emits MIDI clock/sync at the current section's BPM so external
  hardware stays tempo-locked.

### Tempo ramps

Supports gradual tempo ramps (e.g. 120 → 140 BPM) across ambient/beatless
transition sections — not just hard tempo jumps at change points.

### Runs alongside Keyframes

showsync drives audio + MIDI clock; [Keyframes](../keyframes/README.md) listens
to live MIDI (e.g. from the KeyStep) and generates visuals. They are two
independent programs run side by side — showsync has no dependency on
Keyframes and vice versa.

### Cross-platform

Must run on Linux and Mac (Devin — Logic lives on the Mac) and Windows (David).

## Later / out of scope

Explicitly deferred:

- Time-stretching / tempo scaling of the audio.
- A synced video playback channel.
- Mixing showsync video with Keyframes output.

## Quick start — build a set in the app (no YAML needed)

Use Python 3.11 or newer. From this `showsync/` directory:

```sh
python3 -m venv venv
. venv/bin/activate
python -m pip install -r requirements-dev.txt
python main.py
```

Launched with no arguments, showsync reopens your last-used setlist
automatically (the pointer lives in a small per-user state file); the first
time, it opens a new empty set. From there everything happens in the window:

1. **Add songs** — drag audio files (wav/aiff/flac/mp3/m4a) onto the window,
   or press **A** for a native file picker. Each file becomes a row named
   after the file; unsupported or undecodable files are rejected with a
   notice.
2. **Set each song's BPM** — select a row (Up/Down) and cell (Left/Right),
   press **Enter**, type, **Enter** again. BPM is never guessed: you always
   know the tempo your track was recorded at. A song with no BPM is marked
   and the show cannot start until every row is valid.
3. **Optional first-beat offset** — seconds into the file where beat 1 lands
   (default 0). Audio before it plays as a lead-in: Start is sent at the
   song's first frame, no clock ticks are sent through the lead-in, and the
   first tick fires exactly on the offset, so clock-following gear plays its
   first step on the true downbeat.
4. **Rename / reorder / remove** — Enter on the name cell; Shift+Up/Down;
   Delete twice.
5. **Saving is automatic** — the first edit of a brand-new set asks where to
   save (defaulting next to your first audio file); after that every edit
   saves silently. **S** saves explicitly, **O** opens another setlist.
6. **SPACE starts the show** — audio and MIDI devices are only opened for the
   show itself. At the end of the set, **R** restarts from the top and **E**
   returns to the editor (mid-show, editing is limited to reordering unplayed
   songs — end the set or quit to change fields).

The setlist is still stored as ordinary YAML, so hand edits between rehearsals
(comments, `gap`, tempo ramps) are preserved verbatim by every in-app save —
they're just never required.

Devices and show-mode launch:

```sh
python main.py --list-devices
python main.py path/to/setlist.yaml --audio-device DEVICE --midi-port PORT
# Or install the showsync command:
python -m pip install .
showsync path/to/setlist.yaml --midi-port PORT
```

`DEVICE` accepts an audio index or device-name substring; `PORT` accepts a
MIDI output index or exact name. A single MIDI output is selected automatically;
otherwise selection is required. Passing a fully playable setlist path starts
the show immediately, exactly as before; a set that isn't playable yet opens
in the editor with the reason on screen. Windows instructions and distribution
notes are in [windows/README.txt](windows/README.txt).

The [design and five-song example](docs/design-v1.md) define the YAML format.
The original example is also in `tests/fixtures/fall2026.yaml`; its audio paths
are placeholders. All source files are checked before opening the audio device,
including tempo-event/ramp bounds against decoded file durations. Mono is
duplicated to stereo; multichannel source files must first be exported as stereo.
Each file is streamed and resampled to 48 kHz, using bounded current/next buffers.
The final song's `gap` is ignored; earlier gaps retain the outgoing tempo.

Space toggles pause, N skips to the next song, Q quits; the three large buttons
also work. Tab opens a setlist panel: Up/Down select a song, Shift+Up/Down move
it. Songs that have not started yet can be moved while playing (the current song
keeps playing); once the set has ended, everything can be reordered. Moves are
refused — with an on-screen notice — while a skip is settling or in a song's
final half-second. The new order is saved back to the setlist YAML immediately,
preserving hand-written comments and formatting (ruamel.yaml round trip), so it
is what loads next time. At the end of the set, R (key or button) restarts from
song 1 (Stop was sent at the end; restart sends Start again). Mid-show, R asks
for a second R within 3 s so a stray keypress cannot restart a live set.
Paused is dim amber. Ramps display their target BPM. An underrun
flashes a warning and is logged while silence occupies the missing audio frames.
Late decoded samples are discarded to preserve alignment. Decode/MIDI failures
stop playback and report an error. **Resume sends Start: external patterns
restart at their beginning** even though audio resumes in place. No Continue
or Song Position Pointer messages are emitted.

Audio-only playback (no GUI or MIDI) is available with:

```sh
python -m showsync.audio path/to/setlist.yaml --audio-device DEVICE
python -m pytest
python scripts/measure_jitter.py --seconds 15 --json jitter.json
```

The jitter script requires real audio and MIDI loopback, uses a ramp, records
raw send/receive/ideal times, and returns nonzero on missing devices or failed
σ < 0.5 ms / worst < 2 ms gates. On Windows, supply `--input-port` and
`--output-port` for a pre-existing loopback route. Device tests skip only if
there is no usable output; tempo/config/clock tests need no audio or MIDI devices.
See [verification](docs/verification.md) for measured platform results.

A short runnable five-codec demo is `tests/fixtures/smoke.yaml`. Optional
`--freeze-gc` on the main CLI and jitter harness freezes startup objects to
reduce garbage-collector pauses; measure on the target machine before relying
on it. It does not provide real-time scheduling guarantees.
