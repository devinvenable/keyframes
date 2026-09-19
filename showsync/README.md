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

## Run v1

Use Python 3.11 or newer. From this `showsync/` directory:

```sh
python3 -m venv venv
. venv/bin/activate
python -m pip install -r requirements-dev.txt
python main.py --list-devices
python main.py path/to/setlist.yaml --audio-device DEVICE --midi-port PORT
# Or install the showsync command:
python -m pip install .
showsync path/to/setlist.yaml --midi-port PORT
```

`DEVICE` accepts an audio index or device-name substring; `PORT` accepts a
MIDI output index or exact name. A single MIDI output is selected automatically;
otherwise selection is required. Windows instructions and distribution notes
are in [windows/README.txt](windows/README.txt).

The [design and five-song example](docs/design-v1.md) define the YAML format.
The original example is also in `tests/fixtures/fall2026.yaml`; its audio paths
are placeholders. All source files are checked before opening the audio device,
including tempo-event/ramp bounds against decoded file durations. Mono is
duplicated to stereo; multichannel source files must first be exported as stereo.
Each file is streamed and resampled to 48 kHz, using bounded current/next buffers.
The final song's `gap` is ignored; earlier gaps retain the outgoing tempo.

Space toggles pause, N skips to the next song, Q quits; the three large buttons
also work. Paused is dim amber. Ramps display their target BPM. An underrun
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
