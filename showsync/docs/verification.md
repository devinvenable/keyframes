# ShowSync v1 verification — task 65

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
received time. Interval error is `diff(received) - diff(ideal)`; p99 and worst
are absolute errors. Phase error includes MIDI loopback delivery latency.
Count mismatches, dropped ticks, or audio underruns fail the gate even if
interval statistics pass. A software loopback includes Python callback and OS
scheduling; it does not measure physical DIN serialization or acoustic latency.

| Host / route | Duration | Ticks sent/received | σ ms | p99 abs ms | Worst abs ms | Underruns / dropped | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| Mac / CoreMIDI, independent receiver, GC frozen | 30 s | 1679 / 1679 | 0.650 | 0.875 | 20.847 | 0 / 0 | Fail |
| Mac / CoreMIDI, independent receiver | 15 s | 836 / 836 | 1.113 | 1.362 | 20.843 | 0 / 3 | Fail |
| Linux / ALSA virtual, Pulse, independent receiver | 15 s | 834 / 834 | 1.165 | 4.867 | 13.858 | 1 / 5 | Fail |
| Mac / same-process receiver, initial short run | 8 s | 447 / 447 | 0.183 | 0.926 | 1.042 | 0 / 0 | Pass, short run only |
| Mac / same-process receiver, longer run | 15 s | 839 / 839 | 1.627 | 1.407 | 38.003 | 0 / 0 | Fail |
| Linux / ALSA virtual, Pulse output, loaded host | 15 s | 837 / 837 | 2.680 | 10.319 | 17.398 | 5 / 2 | Fail |
| Windows / no MIDI loopback route | — | — | — | — | — | — | Unavailable |

**Neither Linux nor Mac has demonstrated a consistently passing timing gate.**
The initial Mac short pass did not hold in longer runs. In the longer
same-process Mac run the largest error was in receiver dispatch (38 ms), which
motivated the independent receiver. That measurement still exposed dropped
ticks, so no failed result is discarded. Summary records and compressed raw samples are checked in under
[measurements/](measurements/). Optional `--freeze-gc` was tested on Mac for
30 seconds: it removed observed dropped ticks in that run, but σ 0.650 ms /
worst 20.847 ms still failed. It is available as opt-in hardening, not a fix
claimed to satisfy the budget.

Linux reported 16.19 load average on a six-core machine with multiple Blender
processes running. Clock priority elevation was denied. The failed run is
retained explicitly; this host has **not** met the design jitter target. Earlier
runs ranged from σ 0.852–2.944 ms, worst 7.606–28.378 ms. An experimental
zero-duration yield inside the spin did not improve the result and was removed.
No other agents' rendering jobs were stopped to manufacture a quiet result.
Mac priority elevation succeeded; its reported output latency was 8.833 ms.
Linux Pulse reported 10.667 ms. These are PortAudio device reports, not measured
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
output is not a loopback. Repeat Linux measurements on an unloaded performance
machine, and repeat all OS measurements with the actual stage interface,
external sequencer and representative show duration before performance use.

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
