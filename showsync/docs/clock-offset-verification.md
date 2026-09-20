# MIDI clock offset verification — 2026-09-20

Task 83, Linux workstation. Positive offset means earlier MIDI ticks.

## Automated verification

`QT_QPA_PLATFORM=offscreen python3 -m pytest -q` in `showsync/`:
156 passed, exit 0. Covers exact ±32/±250 ms timing with steady and ramped
tempo, live changes without transport messages or epoch changes, persistence
through skip/restart, appstate merging, playback/menu controls without audio
transport writes, and temporary CLI override including subsequent engine creation.

Negative verification was performed after committing the implementation.
Each mutation used a unique replacement and an exact file backup restored in
`finally`. All failures were assertions, not import/collection errors:

- Removing the scheduling offset: all 12 new clock cases failed.
- Omitting offset from the appstate merge: persistence test failed.
- Accepting boolean stored offsets: invalid-setting test failed.
- Forcing the GUI's clock update to zero: live-control test failed.
- Ignoring the CLI override: temporary-override test failed.

An existing document test now checks `offset:` instead of the word `offset`:
the latter matched this worktree's path in the saved audio filename.

## Linux audio/MIDI phase probe

PM confirmed no competing ShowSync instances before measurement. Used PM's
`phase_probe.py` with `--clock-offset` forwarded to the child application,
14-second runs, MIDI Through (avoiding the KeyStep echo loop), 48 kHz stereo
PulseAudio input from `alsa_output.pci-0000_00_1f.3.analog-stereo.monitor`.
Both input paths use monotonic timestamps. The Qt app ran offscreen with real
audio/MIDI devices. This is a monitor/loopback measurement, not a microphone
measurement of speaker latency or a human listening test.

Positive offsets can place initial ticks before playback starts. For a
reliable beat-zero label (`ticks[::24]`), the calibration fixture adds 500 ms
silence and sets the first-beat offset to 0.5 seconds. Otherwise dropped
startup ticks can cause this counting probe to label the wrong beat phase.

| Clock offset | Median click minus MIDI beat | Offset spread |
|---|---:|---:|
| 0 ms | −12.4 ms | 0.2 ms |
| +32 ms | +22.2 ms | 0.3 ms |
| −32 ms | −40.7 ms | 0.5 ms |

All runs recorded 22 clicks, one Start, mean click spacing 0.6000 seconds
and spacing standard deviation 0.02 ms. The two signed settings span 62.9 ms
for a commanded 64 ms change. Relative to the separate zero run, the shifts
were +34.6 and −28.3 ms. The original no-lead-in fixture measured −40.0 ms
in this session, versus PM's earlier approximately −32 ms. Device/monitor
startup timing varies between runs: these measurements confirm direction
and approximate magnitude, not a universal +32 ms calibration. Injected-clock
assertions verify the exact shift independently of capture timing.

Live changes are verified by injected-clock tests and Qt interaction tests;
the physical-device phase measurements above are separate fixed-offset runs.
Keyframes code is unchanged.
