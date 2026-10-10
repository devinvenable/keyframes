# ShowSync v1 verification — tasks 65 and 67

Implementation follows [design-v1.md](design-v1.md). Hardware timing results
are observations on the machines below, not cross-platform timing guarantees.
The tempo and scheduler unit tests inject time/position and need no devices.

## Automated tests

- Linux: 68 ShowSync tests passed, including the real 48 kHz OutputStream test.
- macOS 15.4.1, M2/arm64, Python 3.11.9: 68 passed over SSH, including real
  Core Audio output. The pygame test used SDL's dummy driver; no Mac GUI
  interaction was requested or performed.
- Windows build box, native Windows Python 3.11.9 (win32, not WSL Python):
  68 passed, including real output. SSH reached WSL, which invoked
  `venv/Scripts/python.exe` on `C:\Users\devin\src\showsync-task65`.
- Keyframes on Linux: all 107 existing tests passed; no Keyframes files changed.

The five original one-second 440 Hz fixtures exercise WAV mono/44.1 kHz,
AIFF stereo/48 kHz, FLAC stereo/32 kHz, MP3 stereo/44.1 kHz, and AAC/M4A
stereo/44.1 kHz. Tests check decoded energy as well as shape/rate/length:
checking only shape would have missed the MP3 reservoir corruption caused by
libsndfile 1.2.2 seeking after each small read. The decoder uses sequential
SoundFile reads for MP3. Fixtures are reproducible with `scripts/make_fixtures.py`.

## Real audio and MIDI loopback

The current harness receives MIDI in a separate process, avoiding the sender's
GIL delaying receive timestamps. Earlier same-process runs are preserved as
diagnostics and labeled below. The harness generates a 44.1 kHz backing track, resamples it through the real
engine, and emits a 120→160 BPM ramp through the real MIDI backend. Each raw
sample records tick index, audio-derived ideal monotonic time, send time, and
received time. Count mismatches, dropped ticks, or audio underruns fail the
gate even if interval statistics pass. A software loopback includes Python
callback and OS scheduling; it does not measure physical DIN serialization or
acoustic latency.

### Gate restatement (task 67): send-time interval error

Through task 65 the gate judged `diff(received) - diff(ideal)` at the loopback
receiver. Decomposing every recorded run with
[`scripts/analyze_jitter.py`](../scripts/analyze_jitter.py) (each sample
carries both send and receive timestamps) showed the receiver was measuring
itself: in all three Mac runs, every ≥17 ms worst-case excursion sits on
ticks 1–4 of the run, with send-side error at those ticks under 10 µs — the
entire spike is in loopback delivery warming up (first CoreMIDI delivery /
receiver thread cold start). After tick 10, Mac delivery latency never strays
more than 0.8 ms from its 0.13 ms median. The same pattern capped the new
quiet-Linux runs: send worst 0.6 ms, but single mid-run receiver-side delivery
stalls of 2.9–7.3 ms (the unprioritized receiver process being scheduled out).

The gate now judges **send-time interval error** — `diff(sent) - diff(ideal)`,
σ < 0.5 ms and worst < 2 ms — because the clock's duty ends when the byte is
handed to the OS MIDI API; the receiver is the instrument, not the subject.
Received-side statistics are still computed, reported, and recorded as
delivery diagnostics, and count mismatches, dropped ticks, and underruns fail
the gate exactly as before. `tests/test_measure_jitter.py` covers the verdict
logic, including that a genuine send-side spike still fails.

| Host / route | Duration | Ticks | Send σ / worst ms (gate) | Recv σ / worst ms (diagnostic) | Underruns / dropped | Gate |
|---|---:|---:|---:|---:|---:|---|
| Linux quiet host, rtprio 95, SCHED_RR granted | 60 s | 3360 / 3360 | 0.010 / 0.245 | 0.251 / 7.289 | 0 / 0 | **Pass** |
| Linux quiet host, rtprio 95, SCHED_RR granted | 30 s | 1680 / 1680 | 0.025 / 0.633 | 0.096 / 1.182 | 0 / 0 | **Pass** |
| Mac / CoreMIDI, independent receiver, GC frozen | 30 s | 1679 / 1679 | 0.171 / 1.481 | 0.650 / 20.847 | 0 / 0 | **Pass** (restated) |
| Mac / CoreMIDI, independent receiver | 15 s | 836 / 836 | 0.436 / 8.812 | 1.113 / 20.843 | 0 / 3 | Fail (real send spike + drops) |
| Mac / same-process receiver, longer run | 15 s | 839 / 839 | 0.211 / 1.426 | 1.627 / 38.003 | 0 / 0 | Diagnostic only (same-process) |
| Mac / same-process receiver, initial short run | 8 s | 447 / 447 | 0.174 / 1.074 | 0.183 / 1.042 | 0 / 0 | Pass, short run only |
| Linux / loaded host (load 16), priority denied | 15 s | 834 / 834 | 0.936 / 9.198 | 1.165 / 13.858 | 1 / 5 | Fail |
| Linux / loaded host (load 16), priority denied | 15 s | 837 / 837 | 2.185 / 15.769 | 2.680 / 17.398 | 5 / 2 | Fail |
| Windows / no MIDI loopback route | — | — | — | — | — | Unavailable |

### Multi-port egress (task 259)

The egress fan-out (setlist `midi_outputs` mirrors + the 'ShowSync Cues'
virtual port, showsync/egress.py) adds one non-blocking `send_message` C call
per extra port inside the same clock-thread send. Measured 2026-10-10 with
`--mirror-ports 3` (the gig shape: measured route + three mirrors = four open
outputs) on the quiet Linux host, 30 s, rtprio granted:

| Route | Ticks | Send σ / worst ms (gate) | Underruns / dropped | Gate |
|---|---:|---:|---:|---|
| 1 output (same-day control, `linux-mirror0-control.json`) | 1680 / 1680 | 0.011 / 0.142 | 0 / 0 | **Pass** |
| 4 outputs (`--mirror-ports 3`, `linux-mirror3.json`) | 1680 / 1680 | 0.022 / 0.581 | 0 / 0 | **Pass** |

Fan-out to four ports stays an order of magnitude inside the σ < 0.5 ms /
worst < 2 ms gate. Re-run on the gig Mac mini with the real port set before
the dress rehearsal.

The restated gate changes no failed-run bookkeeping: both loaded-Linux runs
fail on send-side error alone, and the 15 s independent-receiver Mac run fails
on a genuine 8.8 ms send-side spike plus three dropped ticks, so GC freezing
(`--freeze-gc`, which removed the drops in the 30 s run) remains recommended
hardening on Mac, and a loaded host remains disqualifying. The Mac pass is the
30 s GC-frozen run re-judged from its recorded send timestamps; it has not yet
been re-run live under the restated gate. Summary records and compressed raw
samples are in [measurements/](measurements/); the 2026-10-09 Linux runs are
`linux-rtprio*.json`.

**Linux real-time setup (required for the passing result).** The passing runs
were on the same six-core Linux host that previously failed under load
16: this time load was ~1.8 and the session had `RLIMIT_RTPRIO` 95 (check
`ulimit -r`; on this host it is provisioned by the pipewire package's
`/etc/security/limits.d/25-pw-rlimits.conf` with rtkit active). With that
limit, the clock thread's `SCHED_RR` request succeeds (`priority_raised:
true`, confirmed by kernel readback, SCHED_RR prio 1). If `ulimit -r` reports
0, grant rtprio via a `limits.d` entry (or audio-group membership) and open a
new login session before measuring. Earlier failed runs on this host (priority
denied, σ 0.852–2.944 ms, worst 7.606–28.378 ms) are retained above and in
measurements/. An experimental zero-duration yield inside the spin did not
improve results and was removed. No other agents' rendering jobs were stopped
to manufacture a quiet result; the host was already quiet.
Mac priority elevation succeeded; its reported output latency was 8.833 ms.
Linux Pulse reported 10.667 ms, and the 2026-10-09 runs reported 10.667 ms on
device 29 (default). These are PortAudio device reports, not measured
speaker latency.

Windows was probed directly: MIDI inputs `[]`; MIDI outputs
`['Microsoft GS Wavetable Synth 0']`. WinMM cannot create virtual MIDI ports.
The harness was also invoked under native Windows and failed explicitly with
“Virtual ports are not supported by the Windows MultiMedia API.”
No MIDI jitter number is claimed for Windows. Install/configure a loopMIDI
route or connect a physical output-to-input cable, then run:

```powershell
.\venv\Scripts\python.exe scripts\measure_jitter.py --seconds 30 --input-port 0 --output-port 1 --json windows-jitter.json
```

Use the actual indexes from `main.py --list-devices`. A GS Wavetable Synth
output is not a loopback. The unloaded-Linux repeat is done (passing runs
above); a live Mac re-run under the restated gate is still worthwhile, and all
OS measurements should be repeated with the actual stage interface, external
sequencer and representative show duration before performance use.

## Implementation limits and packaging

- No SPP/Continue: resume sends Start and restarts external patterns.
- Timing is soft real-time Python. The callback copies into preallocated NumPy
  storage without decoding, logging, MIDI sends, or blocking locks. Python
  slice/tuple headers still allocate; no hard wait-free/allocation-free claim
  is made. The SPSC index publication assumes CPython with the GIL enabled.
- `AudioResampler` uses bundled FFmpeg/libswresample, not a guaranteed soxr
  backend. The design's parenthetical “soxr-quality” should not be interpreted
  as a selected soxr implementation; the prescribed PyAV resampler is used.
- Current/next buffers are bounded to four seconds each; no full-song preload.
- Native Windows/macOS source execution was verified. A frozen executable and
  a clean-machine distribution have **not** been verified. Follow
  [the Windows packaging notes](../windows/README.txt), mirroring Keyframes'
  one-folder distribution, and test the native codec/MIDI DLLs before release.

## Negative tests and visible integration

After committing the implementation, 21 unique, targeted source mutations were
applied one at a time and restored from exact file copies in `finally` blocks.
All **68 parametrized test cases** failed on assertions (or expected exceptions
not being raised) under a relevant mutation. Collection/import errors were
rejected as evidence. See [the mutation report](mutation-results.json).

A Linux pygame window ran for 240 frames with real audio and ALSA virtual MIDI.
Keyframes' actual `MidiClockTracker` received 411 ticks and observed the ramp
reaching 159.33 BPM. Space pause/resume was injected through pygame events;
screenshots showed the live ramp and the dim amber paused screen. This loaded
host reported four underruns during that smoke run, surfaced in the UI, with no
engine error. This proves integration, not the jitter budget. The short
five-song/five-codec `tests/fixtures/smoke.yaml` also completed through the
headless CLI. It is a scaled demo; the original unmodified design example
remains `tests/fixtures/fall2026.yaml` and requires the performer's real files.

The final UI smoke repeated successfully after replacing an unsupported arrow
glyph with “ramping to”: 411 MIDI ticks, max tracked BPM 159.22, five underruns
on the loaded Linux host. See [playing](playing.png) and [paused](paused.png).

A wheel was built and installed locally and provides the `showsync` console
entry point. This is separate from the unverified frozen Windows bundle.
