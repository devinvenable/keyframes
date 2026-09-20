# showsync v1 — Design

Design for the requirements in [../README.md](../README.md), within the locked
stack decisions (canon `showsync-v1-stack`, midi:D2): Python, cross-platform
(Linux/Mac/Windows), simple performer-facing GUI, WAV/AIFF + mp3/m4a/flac,
MIDI out = 24 PPQN clock + Start/Stop (no SPP).

Out of scope (deferred by spec): time-stretching, video playback, video mixing.

---

## 1. Architecture overview

```
 setlist.yaml ──► setlist.py ──► TempoMap per song (tempomap.py)
                       │                 │
                       ▼                 ▼
              AudioEngine (audio.py)   ClockEngine (clock.py)
              sounddevice callback ──► frame counter = MASTER CLOCK
              decode/resample thread     │  song time → beat position
                       │                 ▼
                       │            python-rtmidi out:
                       │            0xF8 ticks, Start/Stop
                       ▼
                  GUI (gui.py, pygame): song / BPM / elapsed / next up
                  transport: play ▸ pause ⏸ skip ⏭
```

Three time domains, one master:

1. **Audio frames** — the number of frames handed to the output device by the
   sounddevice callback. This is the master clock; everything else derives
   from it.
2. **Song time (seconds)** — `frames_played / engine_rate`, offset per song.
3. **Beat position** — `B(t) = ∫ bpm(τ)/60 dτ`, computed by the tempo map.
   MIDI clock tick *k* fires when the beat position crosses `k / 24`.

The MIDI clock is never free-running: every tick is scheduled against the
audio frame counter, so clock and backing track cannot drift apart, and tempo
ramps are tracked exactly because ticks come from the beat integral, not from
a "current BPM" interval.

---

## 2. Setlist config format

**YAML** (via PyYAML, `safe_load`). Rationale over JSON: hand-edited by Devin
between rehearsals — comments, no quote/comma ceremony, multi-song files stay
readable. The parsed structure is validated by `setlist.py` with precise error
messages (file+song+field), so YAML's loose typing costs nothing.

### Schema

```yaml
# setlist.yaml
title: <string>                # optional, shown in GUI
audio_root: <path>             # optional; song paths resolved relative to this,
                               # else relative to the setlist file itself
songs:
  - name: <string>             # required, shown in GUI
    file: <path>               # required; .wav .aiff .flac .mp3 .m4a
    bpm: <number>              # required to play; the GUI editor may leave it
                               # unset while a set is being built (playback is
                               # gated until every song has one)
    offset: <seconds>          # optional first-beat offset (default 0): beat 0
                               # of the tempo map anchors here; earlier audio
                               # plays as lead-in
    gap: <seconds>             # optional silence AFTER this song (default 0.0)
    tempo:                     # optional list of tempo events, ascending by `at`
      - at: <position>         # required; seconds ("95.5") or "m:ss.sss" ("1:35.5")
        bpm: <number>          # required; tempo reached
        ramp: <seconds>        # optional; 0/absent = hard jump AT `at`;
                               # >0 = linear ramp STARTING at `at`, lasting `ramp`
                               # seconds, ending at the new bpm
```

Rules enforced by the validator:

- Positions are **seconds within the audio file** (the audio was rendered at
  fixed tempo, so time — not beats — is the ground truth). `m:ss.sss`
  is accepted for readability and normalized to seconds.
- **Source-audio contract (DAW-agnostic):** showsync reads no DAW metadata —
  the declared `bpm`/`tempo` entries are the sole tempo authority. Files may
  come from Logic (Devin) or from David's Windows setup (wav/mp3, no DAW
  assumed). Rhythmic material must therefore be recorded to a click at the
  declared BPM, or the emitted clock will walk out of phase with the audio;
  beatless material is exempt. Tempo-map fitting for freely-recorded audio is
  deferred to v2.
- Events sorted ascending; a ramp may not overlap the next event
  (`at + ramp <= next.at`); events must lie within the file's duration
  (checked at load, when durations are known).
- `offset` must satisfy `0 <= offset < duration`; tempo event positions remain
  absolute file positions and must not precede the offset (`at == offset` is
  legal: the event takes effect exactly on beat 0, e.g. a whole-song ramp).
- `Stop` is implied at end of set; `gap` inserts silence between songs while
  the clock keeps running at the outgoing tempo (see §4 Start/Stop semantics
  for the alternative).

### Example — full 5-song setlist

```yaml
title: "Fall 2026 set"
audio_root: ~/shows/fall2026/audio
songs:
  - name: "Cold Open"
    file: 01-cold-open.wav
    bpm: 92

  - name: "Signal Path"
    file: 02-signal-path.flac
    bpm: 120
    tempo:
      - at: "2:04.000"     # hard jump into the bridge
        bpm: 126
      - at: "3:30.500"     # back to verse tempo
        bpm: 120

  - name: "Interlude (beatless)"
    file: 03-interlude.m4a
    bpm: 120
    gap: 1.5
    tempo:
      # ambient section: linear ramp 120 -> 140 over 45 s starting at 0:20
      - at: "0:20.000"
        bpm: 140
        ramp: 45.0

  - name: "Fourteen Hundred"
    file: 04-fourteen-hundred.mp3
    bpm: 140

  - name: "Closer"
    file: 05-closer.aiff
    bpm: 140
    tempo:
      - at: "4:10.000"     # slow outro ramp-down
        bpm: 96
        ramp: 30.0
```

---

## 3. Playback engine

### Backend: `sounddevice` (PortAudio)

| Option | Verdict |
|---|---|
| **sounddevice** | **Chosen.** Callback-driven with an exact frame counter (`time.outputBufferDacTime` / frames delivered) — exactly what a slaved MIDI clock needs. Wheels bundle PortAudio on all three OSes. Low, controllable latency (`blocksize`, `latency='low'`). |
| pygame.mixer | No playback-position API with frame accuracy, no callback, gapless queueing is fragile, format support limited. Fine for Keyframes' needs, wrong tool here. |
| pyaudio | Same PortAudio underneath but clunkier API, weaker wheel story than sounddevice. |

### Decoding: `soundfile` primary, `PyAV` for m4a

- **soundfile** (libsndfile): wav, aiff, flac, **and mp3** — PyPI wheels bundle
  libsndfile ≥ 1.2, which decodes mp3 via mpg123. Simple, seekable, streams in
  blocks.
- **m4a/AAC**: libsndfile cannot. Options considered:
  - external `ffmpeg` binary — an install step on three OSes and a subprocess
    to babysit; rejected.
  - **PyAV** (`av`) — FFmpeg *libraries* bundled in the wheel for
    Linux/mac/Windows; no system install. **Chosen** for m4a only.
- Both are hidden behind one `Decoder` interface in `audio.py`:
  `open(path) -> Decoder` with `.samplerate`, `.duration`, and
  `read(n) -> float32 ndarray (n, 2)`. Extension picks the implementation.

If packaging friction with PyAV shows up in practice, the fallback is to drop
to soundfile-only and ask for m4a to be exported as flac from Logic — but the
decision (midi:D2) requires m4a in v1, so PyAV ships.

### Engine format and gapless playback

- **One `sounddevice.OutputStream` for the whole set**, fixed engine format:
  float32 stereo at **48 000 Hz** (mono sources duplicated to both channels).
  The stream is opened at show start and never closed between songs — this is
  what makes transitions gapless: song boundaries are invisible to the device.
- Each song is decoded and **resampled to the engine rate at decode time**
  (PyAV's `AudioResampler` — soxr-quality, already a dependency; used for
  every file whose native rate ≠ 48 kHz, regardless of container). This also
  resolves the "gapless across different sample rates" risk in one place.
- **Streaming, not preload**: a decoder thread fills a ring buffer
  (~4 s of float32 ≈ 1.5 MB) ahead of the callback; long files never sit in
  RAM. The callback only does `ringbuffer.read(frames)` + a memcpy — no
  decode, no allocation, no locks held across the copy (single-producer
  single-consumer ring with atomic indices).
- **Prefetch next song**: when the current song is within ~10 s of its end,
  the decoder thread opens the next file and begins filling its ring buffer,
  so the boundary is a pointer swap in the producer, not an I/O stall.
- Buffer underrun policy: output silence, log it, keep the frame counter
  advancing (the clock stays honest even through a glitch).

### Position reporting

The callback increments `frames_played` (int, under the GIL a plain int store
is atomic enough; wrapped in a lock-free published tuple
`(frames_played, monotonic_stamp)` for readers). Any thread can compute
"song time now" as
`(frames_played - song_start_frame) / 48000 + (monotonic_now - stamp)`,
the extrapolation term keeping readers smooth between callbacks.

---

## 4. MIDI clock engine

### Principle: invert the tempo map against the audio clock

The tempo map gives `B(t)` (beats at song-time *t*) and its inverse `T(b)`
(song-time of beat *b*) — both closed-form (§5). Tick *k* must fire at
`T(k/24)` in song time, i.e. at a specific **audio frame**. The clock thread:

```
loop:
    t_now   = current song time (from published frame counter, §3)
    k_next  = next undelivered tick index
    t_tick  = T(k_next / 24)
    dt      = t_tick - t_now
    if dt > 2 ms:  sleep(dt - 2 ms)          # coarse sleep
    else:          spin on time.monotonic()  # burn the last ≤2 ms
    midiout.send(0xF8); k_next += 1
```

Because every tick is scheduled from the **absolute** beat index against the
**absolute** audio position, errors never accumulate: a late tick does not
push later ticks; drift is structurally impossible. Ramps need no special
casing — `T(b)` just returns non-uniform tick spacing through the ramp.

### Threading model

- **Do not send MIDI from the audio callback.** PortAudio callbacks must be
  wait-free; rtmidi sends can block in the OS MIDI layer. Also tick times
  rarely align with buffer boundaries (at 140 BPM a tick every ~17.9 ms vs a
  ~5.3 ms/256-frame buffer), so callback-driven ticks would quantize to
  buffer edges — that *is* jitter.
- **Dedicated clock thread**, the loop above, using `time.monotonic()`
  exclusively (never wall clock). `sleep` granularity: on Linux/mac ~1 ms is
  dependable; on Windows sounddevice/PortAudio already raises the timer
  resolution, but the clock thread sleeps only to `t - 2 ms` and spins the
  remainder, so Windows' 15.6 ms default timer never touches tick accuracy —
  at the cost of ≤2 ms of one core, which a performance machine can spare.
- Raise thread priority where the OS allows (best-effort, non-fatal):
  `SetThreadPriority` on Windows, `pthread_setschedparam`/nice on POSIX.
- Optional hardening, applied if measurement demands it: `gc.freeze()` after
  startup + tuned GC thresholds, so collector pauses stay off the clock
  thread's tail.

### Jitter budget

Target: **σ < 0.5 ms, worst case < 2 ms** tick-to-tick error against ideal.
For reference, MIDI DIN itself serializes a byte in ~0.32 ms, and hardware
sequencers tolerate a few ms; the sleep-then-spin pattern in CPython reliably
lands ~±0.1–0.3 ms on all three OSes. Phase 3 includes a **measurement
harness** (loopback MIDI port, record `monotonic()` per received tick,
report σ/p99 vs the tempo map's ideal) so the target is verified, not assumed.

### Start / Stop semantics (no SPP in v1)

Without Song Position Pointer, external gear always restarts at its pattern
start on `Start` (0xFA). Rules:

| Event | MIDI |
|---|---|
| Play (set or song start) | `Start`, then ticks |
| Pause | `Stop` (0xFC), ticks cease |
| Resume | `Start`, ticks resume from current audio position — **gear restarts its pattern**; documented v1 limitation, acceptable for loop-based hardware |
| Skip to next song | `Stop` → seek audio to next song → `Start` at its 0:00 |
| Between songs (`gap` silence) | ticks continue at the outgoing tempo (keeps arps/LFOs alive); the next song's map takes over at its first frame |
| Song with `offset` (first-beat lead-in) | `Start` at the song's first frame as usual, then **no ticks through the lead-in**; tick 0 (beat 0) fires exactly at `offset`. Slaves reset on `Start` and step on the next `0xF8`, so their first step lands on the song's true downbeat. Falls out of the offset-shifted tempo map (`B(t)=0` for `t<=offset`, `T(0)=offset`) — no special-casing in the clock engine |
| End of set | `Stop` |

`Continue` (0xFB) is deliberately unused: without SPP it lies about position
to any gear that tracks bars.

---

## 5. Tempo model

`tempomap.py` — pure functions/dataclasses, no I/O, no threads.

A song's map is compiled from config into segments, each
`(t0, t1, bpm0, bpm1, beats_before)` where `beats_before = B(t0)`:

- **Constant** segment (`bpm0 == bpm1`):
  `B(t) = beats_before + bpm0 · (t − t0) / 60`
- **Linear ramp**: bpm(τ) linear from bpm0 to bpm1 over d = t1 − t0, so
  `B(t) = beats_before + [bpm0·(t−t0) + (bpm1−bpm0)·(t−t0)²/(2d)] / 60`
- Inverse `T(b)`: constant segments invert linearly; ramps solve the
  quadratic (positive root; discriminant is provably ≥ 0 for bpm > 0).
  Both directions are exact closed forms — no numeric integration, no
  accumulation error.

Set-level: each song owns its map anchored at its own t=0; the engine tracks
`(song_index, song_time)`. Beat position resets to 0 per song (matches gear
restarting on `Start` at each song anyway). `bpm_at(t)` feeds the GUI readout,
including mid-ramp values.

Compile-time validation: monotonic events, non-overlapping ramps, bpm > 0,
positions within file duration.

---

## 6. GUI

### Framework: **pygame**

Consistent with the locked "same toolchain family as Keyframes" decision and
this repo's reality: pygame is already a working dependency with a solved
Windows packaging path (`keyframes/windows/`, `test_windows_packaging.py`),
and the performance screen is a glanceable dashboard — exactly what pygame
draws well at trivial cost. tkinter rejected (inconsistent packaging/fonts
across OSes, ugly at "readable from across the stage" sizes); DearPyGui
rejected (new heavyweight dependency for four text fields and three buttons).
The GUI loop runs at ~30 fps in the **main thread** (pygame requirement on
macOS) and only *reads* published state; audio and clock threads never touch
pygame.

### Performance screen wireframe

```
┌────────────────────────────────────────────────────────────┐
│  FALL 2026 SET                                   3/5 songs │
│                                                            │
│              INTERLUDE (BEATLESS)                          │  ← current song, huge
│                                                            │
│        ▶  128.4 BPM  (ramping → 140)                       │  ← live bpm_at(t), huge
│                                                            │
│        01:12  ────────●──────────────  -02:48              │  ← elapsed / bar / remaining
│                                                            │
│  NEXT:  Fourteen Hundred  (140 BPM)                        │
│                                                            │
│      [ SPACE pause ]   [ N skip ]   [ Q quit ]             │
└────────────────────────────────────────────────────────────┘
```

- State colour: playing = normal, paused = whole screen dimmed amber (visible
  peripheral cue), ramp active = BPM shown with target, lead-in (audio before
  a song's first-beat `offset`) = LEAD-IN.
- Input: keyboard + click on the big buttons; the setlist path CLI argument is
  optional — no argument reopens the last-used set (per-user state file) or a
  new empty one.
- **Setlist editor (pre-show)**: launching without a playable show opens an
  editor over a mutable Document instead of the dashboard. Drag-and-drop audio
  files (pygame `DROPFILE`) or a native picker (stdlib tkinter, withdraw-root
  so no Tk loop competes with pygame's) add rows: name = filename stem, BPM
  empty, offset 0. Per-row editing of name/BPM/offset plus one optional tempo
  ramp (RAMP = end BPM, START = seconds into the file defaulting to the
  offset, DUR = seconds defaulting to the end of the file), stored as a single
  ordinary tempo event. Hand-authored maps the controls can't express (hard
  jumps, several events) show a read-only "custom tempo map (edit in YAML)"
  badge and pass through saves verbatim. Shift+Up/Down reorder,
  double-Delete remove. Every edit auto-saves through the ruamel round trip
  (a pathless new set asks where once, defaulting next to the first audio
  file). Playback is gated until every row is valid, then SPACE builds the
  engines (audio/MIDI devices are only claimed for the show itself). YAML
  stays the storage format — hand edits, gaps, and tempo ramps are respected
  but never required. The saved file may hold songs without a BPM yet: the
  Document loader is lenient, while the engine-facing loader stays strict.
  At END OF SET, E closes the engines and re-enters the editor.
- **BPM suggestions**: empty rows loaded or added in the editor queue a single
  background worker. NumPy spectral flux and autocorrelation over up to 90 s
  of middle-file audio (existing Decoder, 12 kHz mono analysis) search 60–200
  BPM; near ties prefer 90–180 BPM and the shorter beat period. Weak transient
  or periodic evidence yields no estimate. The demo ramp returns its dominant
  140 BPM section, not a reconstructed ramp. Estimates display `~` until
  Enter/edit, and save as normal BPM numbers without schema changes. Only the
  main thread applies results, by row identity and only while still empty and
  untouched. The worker is cancelled and joined before leaving the editor,
  so analysis never overlaps playback. Sequential decoding may traverse the
  prefix to reach the middle (the MP3 decoder cannot seek).
- Tab toggles a setlist panel (kept off the glanceable performance screen):
  Up/Down select, Shift+Up/Down move a song that has not started yet (any song
  once the set has ended); refusals show an on-screen notice. The new order is
  written back to the setlist YAML via a ruamel.yaml round trip, preserving
  hand-written comments (byte-stable when the order is unchanged).
- End of set shows a Restart control: R (or its button) restarts from song 1 —
  Stop was already sent, restart sends Start per §4. Mid-show R requires a
  second press within 3 s.

---

## 7. Program structure

```
showsync/
  README.md
  docs/design-v1.md          (this doc)
  requirements.txt           sounddevice, soundfile, av, mido, python-rtmidi,
                             pygame, PyYAML, numpy
  main.py                    CLI entry: parse args, load setlist, wire engines, run GUI loop
  showsync/
    __init__.py
    setlist.py               YAML parse + validation → Setlist/Song dataclasses
    tempomap.py              pure tempo math: compile, B(t), T(b), bpm_at(t)
    audio.py                 Decoder interface (soundfile/PyAV), resampler,
                             ring buffer, OutputStream callback, frame counter
    clock.py                 clock thread, tick scheduling, Start/Stop, transport state
    gui.py                   pygame screen + input handling
  tests/
    test_setlist.py
    test_tempomap.py
    test_clock.py
    test_audio_decode.py
```

### Testing strategy

The two correctness-critical pieces are testable **without audio hardware or
MIDI devices**, by design:

- **tempomap** — pure math. Property tests: `T(B(t)) == t` round-trip across
  jumps and ramps; ramp beat counts match analytic integrals; segment
  boundaries continuous; validator rejects overlapping/retrograde events.
- **clock** — the engine takes an injected `now()` time source, an injected
  position provider, and an injected `send(msg)` sink. Tests drive a fake
  clock forward and assert exact tick timestamps against `T(k/24)`, including
  through a ramp; Start/Stop ordering on pause/skip; no tick after Stop.
- **setlist** — fixture YAMLs: valid, mis-ordered events, overlapping ramp,
  bad time strings, missing file.
- **audio** — decode tiny checked-in fixtures (1 s per format) and assert
  rate/shape/length; ring-buffer unit tests (wrap-around, underrun). The
  callback path gets a smoke test behind a "device available" skip marker.
- **Jitter harness** (not CI): `scripts/measure_jitter.py` against a loopback
  MIDI port, reports σ/p99 per platform.

### Phased implementation plan

Each phase is one agent-sized task, independently verifiable:

1. **T-A: Setlist + tempo map.** `setlist.py`, `tempomap.py`, full test
   suites, the example setlist as a fixture. *Verify:* pytest green;
   round-trip property tests pass.
2. **T-B: Audio engine.** `audio.py` — decoders (incl. m4a via PyAV),
   resample-to-48k, ring buffer, gapless OutputStream, frame-counter
   position API. Headless CLI: `python -m showsync.audio setlist.yaml` plays
   the set. *Verify:* decode tests green; audible gapless boundary between
   two fixtures at different sample rates.
3. **T-C: MIDI clock engine.** `clock.py` with injected time/position/sink,
   tests, jitter harness, Start/Stop semantics wired to a transport-state
   object. *Verify:* clock tests green; harness shows σ < 0.5 ms against a
   loopback port with real audio running.
4. **T-D: GUI + integration.** `gui.py`, `main.py`, transport actions
   (pause/skip) driving both engines; paused/ramp visual states. *Verify:*
   run against the example setlist; Keyframes' `MidiClockTracker` displays
   the ramping BPM (existing keyframes code doubles as an end-to-end check).
5. **T-E: Cross-platform pass.** Windows/mac run-through, thread-priority
   shims, device-selection flag (`--audio-device`, `--midi-port`),
   packaging notes mirroring `keyframes/windows/`. *Verify:* jitter harness
   numbers recorded per OS in docs.

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Python timing jitter on MIDI clock** (GC, scheduler, Windows timer) | Ticks scheduled against absolute beat index × audio frame counter (no cumulative error); sleep-to-2ms-then-spin; thread priority raise; optional `gc.freeze`; measured, not assumed, via the jitter harness (phase 3/5 gates on σ < 0.5 ms). Residual risk: a pathologically loaded machine — mitigated operationally (dedicated performance laptop). |
| **Cross-platform audio latency differences** | Latency shifts *audio* relative to the room, but clock and audio share the frame counter so they cannot separate — the sync contract survives any latency. Output latency is also reported by PortAudio and subtracted when publishing position, keeping MIDI aligned with what's *audible*, not what's queued. `--audio-device` + `latency='low'` for tuning per machine. |
| **Gapless across different sample rates** | Single never-closed 48 kHz stream; per-song resampling at decode time; next-song prefetch so the boundary is a pointer swap. |
| **m4a decoder dependency (PyAV) packaging** | PyAV ships bundled-FFmpeg wheels for all three OSes; isolated behind the `Decoder` interface so it can be swapped (or m4a re-exported as flac) without touching the engine. |
| **No SPP: gear restarts patterns on resume** | Documented v1 semantic (decision midi:D2 excludes SPP); pause is a show-stop anyway. Revisit SPP in v2 if it bites in rehearsal. |
| **Ring-buffer underrun on slow disks / m4a decode spikes** | 4 s buffer, prefetch thread, silence-and-log policy keeps the clock honest; underruns surface in the GUI as a warning flash. |
