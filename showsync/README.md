# showsync

Live-performance backing-track player and MIDI clock master for Devin and
David's live show. **Requirements spec only — no implementation yet.**

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
