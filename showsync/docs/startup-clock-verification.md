# Task 87: startup clock counts and transport preference

Positive compensation now clamps pre-start tick deadlines instead of dropping
indices. At 100 BPM with +32 ms, indices 0 and 1 fire at startup, index 2
at 18 ms, then ticks retain their 25 ms interval. Tests check every index and
simulate a six-clocks-per-step slave using received message counts alone.
They cover +32/+250 ms, steady/ramped tempo, gap transitions, and restart.

Scheduler audit: a new song/epoch resets the index to zero; resuming the same
song retains the next unsent index. Neither path advances an index without
sending it. Startup backlog is protected from stale-tick dropping. During
established playback, the existing OS-stall/live-offset anti-burst policy
still drops stale indices, retaining absolute phase. Live retuning can thus
require manually re-triggering tick-counting gear; tune before performance.

Preferences has a default-on, per-machine Send MIDI Start/Stop checkbox.
It applies to the next playback. Off suppresses transport on start, pause,
song change, restart, end, and close, while retaining clock messages.
Cancel leaves both the current selection and stored preference unchanged.

Verification from `showsync/`:

```sh
QT_QPA_PLATFORM=offscreen /home/devin/src/2026/midi/venv/bin/python -m pytest -q
```

172 passed, exit 0. Running pytest from the repository root instead does not
load ShowSync's pytest configuration and fails collection; use its project directory.

Negative tests ran after committing, with exact file backups restored in
`finally` and unique mutation targets. Every mutation failed on assertions:

- Restoring the original scheduler: four startup/counting-slave cases fail.
- Restoring the resume skip: resume index assertion fails.
- Removing startup protection from stale-tick dropping: four cases fail.
- Inverting transport enablement: four message-sequence cases fail.
- Omitting persistence or accepting invalid stored values: state test fails.
- Omitting Preferences saving: dialog persistence test fails.
- Ignoring the preference during engine creation: wiring test fails.

Keyframes is untouched. No physical KeyStep/drum-machine test was performed;
Devin will verify the hardware after merge.
