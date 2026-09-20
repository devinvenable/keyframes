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
                  GUI (gui.py, PySide6): song / BPM / elapsed / next up
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
    restart: <boolean>         # optional Stop/Start here to reset patterns (default false)
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
(song-time of beat *b*) — both closed-form (§5). A set-level clock map
translates these maps onto a continuous beat grid
(see handover below). Tick *k* must fire at `T_set(k/24)` in absolute audio
time, i.e. at a specific **audio frame**. The clock thread:

```
loop:
    t_now   = absolute audio time (published frame counter, §3) + clock_offset_ms / 1000
    k_next  = next undelivered tick index
    t_tick  = T_set(k_next / 24)
    dt      = t_tick - t_now
    if dt > 2 ms:  sleep(dt - 2 ms)          # coarse sleep
    else:          spin on time.monotonic()  # burn the last ≤2 ms
    midiout.send(0xF8); k_next += 1
```

Every ideal deadline comes from the **absolute** beat index against the
**absolute** audio position. A late tick does not move later ideal deadlines;
the rate-limited catch-up below can temporarily lag that grid while recovering.
Ramps need no special casing — `T(b)` returns non-uniform tick spacing.

### Live rig compensation

A Linux monitor/loopback probe measured MIDI ticks about 32 ms behind audio,
including before the Qt migration. Reported output latency does not model the
whole rig. `clock_offset_ms` (−250..+250, default 0) shifts only the clock's
snapshot of audio time: tick k is due at `T_set(k/24) - clock_offset_ms/1000`.
Positive means earlier MIDI: **increase if gear sounds late; decrease if gear
sounds early**. Audio frames, tempo maps, transport epochs, Start and Stop
remain unchanged. One scalar snapshot is read per scheduler iteration; its
10 ms sleep cap bounds reaction time. Positive jumps use the rate-limited
catch-up below; negative jumps wait on the next absolute tick.
The adjusted position may be negative at startup: beat lookup clamps to zero,
but deadline comparisons retain the signed time so delayed tick zero waits.
Clocks due before transport starts cannot be emitted; use a lead-in longer
than positive compensation when the first beat must retain exact phase.

Playback and File-menu controls update live, with 1 ms fine and 10 ms coarse
steps. The rig preference is merged into appstate `state.json` independently
of the last-setlist pointer. `--clock-offset MS` overrides it without persisting
changes during that run. Skip/restart and new engine creation retain the
session value. Tune by ear with `demo/click-test.yaml` (generated audio has
500 ms silent lead-in), comparing external gear to the clicks; +32 ms is the
motivating Linux example, not a universal default.

### Continuous handover and beat/bar position

Audio is unchanged. For incoming song *i*, let `a_i = start_frame_i / RATE +
offset_i`, its actual first beat. In the outgoing set clock map, find the two
integer beats bracketing `a_i` and choose the one whose **time** is nearest
(ties go earlier). Call its time `h_i` and integer beat index `q_i`. From that
beat onward, use `T_set(b) = h_i + T_i(b - q_i) - offset_i`. All of that song's
tempo events, including its ramps, receive the same translation. No ramp
integration or inverse mathematics changes.

The phase error `h_i - a_i` is at most half the bracketing beat's duration
(`30 / BPM` seconds for constant tempo; at most `30 / minimum_BPM` for a
ramping beat). Each incoming anchor uses its actual audio frame and offset,
never a sum of previous shifts: errors stay locally bounded across the set.
Ramps retain their shape but their clock events may lead/lag the corresponding
audio by this local phase error. This is an explicit tradeoff for continuous
hardware phase. Extremely short songs may quantize to the same beat; the last
map takes over there without inserting or removing a tick.

The target is one beat, **not a four-beat bar**: bar snapping could move the
handover by two beats. Tick `k` stays gapless across all natural boundaries;
beat position is `k/24`, four-beat bar phase is `(k/24) % 4`. A 16-step slave
advances on every sixth F8, retaining its phrase through ramps and gaps.
Incoming songs can start partway through that phrase; `restart: true` is the
explicit choice when gear must return to step 1. At set start, manual skip,
set restart, or an explicit per-song reset, a new clock sequence starts at 0.
Pause/resume keeps the next unsent index but Start resets the hardware pattern
(the existing no-SPP limitation).

The outgoing map runs through gaps and natural lead-ins until the quantized
handover, which may lie just before or after the incoming first beat. Start
and Stop are not sent at these natural boundaries. A Position carries the
same immutable Layout used to derive its frame and song, giving the clock
future boundaries even when it must hand over early. Reorder rebuilds the
clock map from this snapshot. Live reorder is refused, with a visible notice,
within `max(0.5, 30 / slowest_set_BPM + 0.250)` seconds of the next audio
boundary, including when paused: an early incoming clock cannot be retracted.
The 250 ms allowance covers the largest positive rig compensation. Manual
skip/restart epochs and T80 decoder-slot invalidation retain their behavior;
a natural boundary does not change epoch or reset the clock index.

### Late ticks and recovery

Never drop F8 indices: tick-counting gear cannot recover phase from a missing
clock. On established playback, send one overdue tick per scheduler step,
spacing catch-up ticks by at least half their ideal scheduled interval (at
most twice that interval's normal rate). Once caught up, absolute audio
positions determine deadlines again. For constant tempo, a three-second
stall takes approximately three more seconds to catch up at twice the rate;
the audio keeps running. A truly catastrophic stall calls for manual Restart
(Stop/Start), not prolonged catch-up during a show. `dropped_ticks` remains a
vestigial, always-zero status attribute for compatibility.

At Start, clocks already due are instead emitted in order with compressed
startup intervals (T87): there was no opportunity to emit them before Start.
That includes tick zero under positive rig compensation. Start/resume retains
this intentional startup exception to the steady-playback rate limit.

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
| Play set | `Start` once, then ticks |
| Pause | `Stop` (0xFC), ticks cease |
| Resume | `Start`, ticks resume from current audio position — **gear restarts its pattern**; documented v1 limitation, acceptable for loop-based hardware |
| Skip to next song | `Stop` → seek audio to next song → `Start` at its 0:00 |
| Natural song boundary, gap, or lead-in | No transport messages; outgoing ticks continue until the nearest-beat handover, then the incoming map takes over. Tick indices never reset |
| Song with `restart: true` | `Stop` → `Start` at its first audio frame; clock index resets to zero, respecting its first-beat offset |
| Set start, skip, or explicit restart with `offset` | `Start` at the first audio frame, then wait for tick zero at the offset (adjusted for rig compensation). Natural lead-ins keep the outgoing clock running |
| End of set | `Stop` |

The **Send MIDI Start/Stop** preference governs every transport byte, including
per-song restarts. When disabled, internal timing still resets at an explicit
restart, but only clocks are sent; hardware must be triggered manually.

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

Each song retains its file-local tempo map for validation and the GUI's
`bpm_at(song_time)` readout, including mid-ramp values. The clock composes
these maps onto the continuous set beat grid described in §4. The GUI reports
the audio-local BPM; during a shifted handover/ramp it can briefly differ from
the clock's translated BPM.

Compile-time validation: monotonic events, non-overlapping ramps, bpm > 0,
positions within file duration.

---

## 6. GUI — Qt / PySide6 (supersedes the original Pygame UI)

Decision `showsync-qt-pivot` (midi:D5) replaces the keyboard-first Pygame
interface with a conventional desktop application that David can discover
without knowing shortcuts. PySide6 supplies LGPL pip wheels and PyInstaller
support; its larger distribution size is accepted.

A single `QMainWindow` owns a `QStackedWidget` with editor and playback views.
Standard window chrome supports resize/maximize/close. The menu bar provides:

- File: New Set, Open, Save, Save As, Recent Sets, Quit.
- Set: Play Set, Pause / Resume, Skip, Restart, Stop, Return to Editor.
- View: Fullscreen (F11).
- Help: About.

A prominent Play Set button switches from editor to playback. Visible transport
buttons accompany the large song, live BPM/ramp target, elapsed/remaining,
progress, state, and next-song readouts. Paused uses amber; lead-in, gap, and
end-of-set are explicit states. End of set offers Restart and Return to Editor.
Live restart, early return, and window close ask for confirmation. Stop closes
the devices and returns to editing. Shortcuts are menu accelerators, never
primary instructions painted on the dashboard.

The editor is a `QTableView` adapter over the unchanged `Document`. Columns are
song, file, BPM, offset, end BPM, ramp start, ramp duration, and a small
**Restart patterns** checkbox (default off). Native Qt dialogs
and file drops add audio; Move Up/Down reorder; Remove confirms deletion.
Cells use a native delegate; the BPM cell shows Queued, animated Analyzing,
~estimate, or confirmed numeric values. The existing Suggestions worker is
polled only in the editor, cancelled/joined before starting playback, and never
replaces a manual BPM. Periodic refresh does not reset an active cell editor.

Document remains lenient, autosaves every edit through the ruamel round trip,
and gates playback with the first problem's song name. New sets ask for a path
once; after cancellation, only explicit Save asks again. Save As preserves audio
references when relocating a set. Custom tempo maps stay read-only in the simple
ramp cells. A simple ramp defaults to offset → end of file; clearing its duration
restores that end point. The original frozen demo ramp fixture remains the
reference for editor-to-engine equivalence.

No-argument CLI launch reads existing `appstate` and opens the editor. Qt
`QSettings` adds a ten-entry Recent Sets list. The engine factory still belongs
to CLI wiring. The main-thread QTimer runs every 33 ms and only reads engine
snapshots; the callback and MIDI thread never call Qt. Transport handlers call
the existing engine APIs. Shutdown closes the clock (sending Stop), audio,
and MIDI in that order. Live reorder still uses `AudioEngine.move` and persists
the resulting order through Document.

Historical rationale: the original Pygame choice reused Keyframes' toolchain
and packaging, and cheaply drew a glanceable performance dashboard at 30 fps.
Tkinter was rejected for inconsistent packaging/fonts; DearPyGui added a heavy
dependency for a small dashboard. That rationale suited display-only use, but
editing a set exposed an unintended keyboard-first, chromeless workflow. Qt
supersedes the GUI choice; audio, clock, tempo math, Document, BPM estimator,
and appstate remain GUI-independent and unchanged by this rewrite.

---

## 7. Program structure

```
showsync/
  README.md
  docs/design-v1.md          (this doc)
  requirements.txt           sounddevice, soundfile, av, mido, python-rtmidi,
                             PySide6, PyYAML, ruamel.yaml, numpy
  main.py                    CLI entry: parse args, load setlist, wire engines, run GUI loop
  showsync/
    __init__.py
    setlist.py               YAML parse + validation → Setlist/Song dataclasses
    tempomap.py              pure tempo math: compile, B(t), T(b), bpm_at(t)
    audio.py                 Decoder interface (soundfile/PyAV), resampler,
                             ring buffer, OutputStream callback, frame counter
    clock.py                 clock thread, tick scheduling, Start/Stop, transport state
    gui.py                   Qt window, table adapter, stacked views + input handling
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
| **Cross-platform audio latency differences** | The shared frame counter prevents drift, but a constant rig-specific phase offset can remain; the live MIDI clock offset compensates it. Output latency is also reported by PortAudio and subtracted when publishing position, keeping MIDI aligned with what's *audible*, not what's queued. `--audio-device` + `latency='low'` for tuning per machine. |
| **Gapless across different sample rates** | Single never-closed 48 kHz stream; per-song resampling at decode time; next-song prefetch so the boundary is a pointer swap. |
| **m4a decoder dependency (PyAV) packaging** | PyAV ships bundled-FFmpeg wheels for all three OSes; isolated behind the `Decoder` interface so it can be swapped (or m4a re-exported as flac) without touching the engine. |
| **No SPP: gear restarts patterns on resume** | Documented v1 semantic (decision midi:D2 excludes SPP); pause is a show-stop anyway. Revisit SPP in v2 if it bites in rehearsal. |
| **Ring-buffer underrun on slow disks / m4a decode spikes** | 4 s buffer, prefetch thread, silence-and-log policy keeps the clock honest; underruns surface in the GUI as a warning flash. |
