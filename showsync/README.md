# showsync

Live-performance backing-track player and MIDI clock master for Devin and
David's live show. Python application with a Qt / PySide6 desktop interface.

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
- Sends MIDI Start once at set begin and Stop once at set end. Natural song
  transitions keep the clock and external patterns running continuously.

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
time, it opens a new empty set. Passing a file (`python main.py path/to/setlist.yaml`)
opens that set in the same editor and adds it to **File → Recent Sets**.
Playback starts only when you choose **Play**. Incomplete songs stay editable
with their problems marked; unreadable setlists show a notice in the window.
From there everything happens in the window:

1. **Add Songs** — click the button or drop wav/aiff/flac/mp3/m4a files onto
   the editor. Unsupported or undecodable files produce a notice.
2. **Tempo and first beat are detected automatically** — songs without a BPM
   or tempo map are analyzed in the background, showing Queued / Analyzing.
   Steady rhythmic tracks get precise BPM and first-beat offset suggestions
   marked **~**. Double-click either cell to confirm or correct it. The full
   precision is saved and used for MIDI clock timing, even when the table
   shows fewer digits. Audio is never stretched or modified.
   Existing BPMs, tempo maps, and manual BPM edits always win. Existing offsets
   (including an explicit zero) and offset edits also remain authoritative.
   Saved estimates become ordinary values and are not reanalyzed on reopening;
   clear the BPM to request fresh analysis when reopening the set.
   Beatless material, changing tempos, or inconsistent grids show **No estimate**
   and need a manual BPM / tempo map.
3. **First-beat offset** — seconds into the file where beat 1 lands. Detection
   fits the first supported rhythmic pulse; it does not infer musical meter,
   bar one, or whether an intro is a pickup. Correct the offset if needed.
   At set start or an intentional restart, MIDI Start goes out at the first
   audio frame and the first clock tick lands at the offset (adjusted for rig
   compensation). At natural song transitions, the outgoing clock continues
   through the lead-in until the nearest-beat handover.
4. **Optional tempo ramp** — enter **End BPM**, **Ramp start (s)**, and
   **Ramp duration (s)**. A new ramp runs from the first-beat offset to the
   end of the file. Clear duration to restore that end point; clear End BPM
   to remove the ramp. Complex hand-authored maps show a read-only **Custom**
   badge and remain intact.
   Check **Restart patterns** on a song when you want Stop/Start at that
   song and external gear to return to step 1; it is off by default. The
   **Send MIDI Start/Stop** preference must be enabled to reset the gear.
5. **Rename / reorder / remove** — double-click the song name, or select a
   row and use **Move Up**, **Move Down**, and **Remove**.
6. **Saving is automatic** — the first edit asks where to save, defaulting
   next to the first audio file. Later edits save silently. Cancelling that
   first dialog suppresses repeat prompts until you choose **File > Save**.
   File also offers **New Set**, **Open**, **Save As**, and **Recent Sets**.
7. **Play Set** — the prominent editor button starts playback. A notice names
   the first song that still needs attention. The playback view has **Pause**,
   **Skip**, **Restart**, **Stop**, and **Return to Editor** buttons. Restart
   and Return to Editor remain available when the set ends. Returning early
   asks to stop the performance; Stop closes the engines and opens the editor.

The standard window can be resized and maximized. **View > Fullscreen** (F11)
removes the chrome when desired. All shortcuts are listed in the menus;
buttons need no keyboard knowledge. Closing during a performance asks for
confirmation and sends MIDI Stop before closing the devices.

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
MIDI output index or exact name. These flags override saved device choices for
this run only.

**File → Preferences…** offers MIDI and audio output dropdowns with a refresh
button. Explicit choices are saved on this machine. Play never asks you to
configure devices: audio uses the system default unless you picked an output;
MIDI uses your saved output, otherwise the first hardware output (preferring
ports without “Through”, “virtual”, or “loopback” in their names), then the first
available output. With no MIDI output, the show plays audio only. Unplugged
choices fall back automatically with a status notice, without erasing your saved
choice. The active MIDI output appears in the status bar during playback.
Stop playback to change device preferences. Passing a fully playable setlist path starts
the show immediately, exactly as before; a set that isn't playable yet opens
in the editor with the reason on screen. Windows instructions and distribution
notes are in [windows/README.txt](windows/README.txt).

Preferences also includes **Send MIDI Start/Stop**, enabled by default and
saved on this machine. Turn it off to send clock ticks only and trigger your
gear manually. This applies to the next playback, including explicit per-song
restarts, pause, restart, end of set, and closing playback. Natural song
boundaries never send transport messages.

The [design and five-song example](docs/design-v1.md) define the YAML format.
The original example is also in `tests/fixtures/fall2026.yaml`; its audio paths
are placeholders. All source files are checked before opening the audio device,
including tempo-event/ramp bounds against decoded file durations. Mono is
duplicated to stereo; multichannel source files must first be exported as stereo.
Each file is streamed and resampled to 48 kHz, using bounded current/next buffers.
The final song's `gap` is ignored; earlier gaps keep the clock running.

Natural transitions anchor the incoming song's first beat to the nearest
outgoing clock beat. Audio is never moved or stretched. The clock map can
shift by up to half a beat (half the bracketing beat interval for a ramp),
and the error is measured afresh against each actual song start plus its
first-beat offset, so it does not accumulate across the set. The outgoing
clock runs through gaps and lead-ins until that handover, which can be just
before or after the first beat. Ramps retain their shape on the shifted map.
We snap to beats, not four-beat bars: bar snapping could shift by two beats.
A 16-step pattern keeps its phrase, but the next song need not begin on step 1.
Use **Restart patterns** (YAML `restart: true`) when a reset is wanted.

Space pauses/resumes during playback (also in the Set menu). The playback
song list has Move Up / Move Down buttons for reordering unplayed songs.
Once the set ends, any song can move. Moves during a pending skip or near the
next song boundary are refused with a notice. The protected window is at least
half a second, or half a beat at the slowest set tempo plus 250 ms, whichever
is longer. This also applies when paused, because the next map may already
have sent clocks ahead of its audio. Order changes save immediately.
Restart during a live performance asks for confirmation; at end of set it
starts immediately from song 1.
Paused is dim amber. Ramps display their target BPM. An underrun
flashes a warning and is logged while silence occupies the missing audio frames.
Late decoded samples are discarded to preserve alignment. Decode/MIDI failures
stop playback and report an error. **Resume sends Start: external patterns
restart at their beginning** even though audio resumes in place. No Continue
or Song Position Pointer messages are emitted.

Audio-only playback (no GUI or MIDI) is available with:

```sh
python -m showsync.audio path/to/setlist.yaml --audio-device DEVICE
QT_QPA_PLATFORM=offscreen python -m pytest  # Linux headless widget tests
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

### Tune MIDI clock timing for your rig

A Linux phase measurement found MIDI about **32 ms later** than the audible
clicks, consistently across the older and Qt versions. PortAudio's reported
latency cannot account for the entire audio and downstream MIDI/gear path.

Run `python demo/make_demo.py`, then play `demo/click-test.yaml`. Enable a
repeating beat on your external gear and adjust **MIDI clock offset (ms)** in
the playback view until it lands on the clicks. **Increase if gear sounds
late; decrease if gear sounds early.** Positive values send ticks earlier;
negative values send them later. For the measured Linux rig, try **+32 ms**.
Use the spinbox for 1 ms steps or the ±10 ms buttons for coarse tuning.
The same live control is available under **File → MIDI clock offset…**.

The range is −250 to +250 ms, default 0. Changes apply immediately while
playing, without restarting transport or changing the audio. Large increases
catch up without dropping clocks, at up to twice the normal tick rate;
decreases briefly wait before continuing at the new phase. Tune before the performance. The click test includes a 500 ms silent
lead-in so even positive offsets can advance its very first tick. Without
sufficient lead-in, clocks due before playback starts are clamped to startup
and emitted in order, with compressed initial intervals. No leading tick
indices are skipped, so tick-counting slaves stay step-aligned. The same rule
applies at intentional restarts; natural transitions retain continuous indices. At +32 ms and 100 BPM, ticks 0 and 1
are sent at startup, tick 2 at 18 ms, and subsequent intervals are 25 ms.

The offset is saved per machine in ShowSync's existing `state.json`, separate
from setlists. `--clock-offset 32` overrides it for one run; adjustments during
that overridden run also remain temporary. Restarting or skipping retains it.

After an OS stall, every overdue clock is retained. Catch-up is limited to
roughly twice the scheduled rate, then locks back to absolute audio timing;
at constant tempo, a three-second stall takes about three seconds to recover.
Use manual Restart after a catastrophic stall instead of waiting through a
long recovery. Hardware verification of continuous transitions is deferred
to Devin using `three-song-set.yaml` on the live rig.
