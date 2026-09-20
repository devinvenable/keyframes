# Qt desktop verification — task 79

Verified on Linux/X11 (`xcb`, display `:0`), Python 3.13.3, PySide6 6.11.2.

## Automated checks

```
QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q showsync/tests
140 passed; exit code 0
```

Pygame was uninstalled from the verification venv before the final full run.
The 21 pytest-qt cases cover building a set by file drop, native table edits,
playability notices, suggestion states and manual precedence, autosave/cancel,
Save As across directories, recent/open/new sets, ramp bounds/defaults/custom
maps, the frozen T73 demo ramp equivalence, transport/mode transitions,
fullscreen, live reorder, confirmed close with Stop before device shutdown,
engine failure handling, and unchanged no-argument appstate startup.

All 119 non-GUI tests and their source files are unchanged relative to main.
The additional audio restart tests arrived through the merge of task 80
(`951c0cb`). Keyframes files and tests are unchanged by this task.
The sounddevice tests emit existing NumPy 2.5 shape-assignment deprecation
warnings; they do not fail.

[Mutation results](mutations.json): 19 targeted mutation runs cover all 21
widget-test cases (the suggestion case has three input-source parameters).
Every mutation failed on an assertion, not import/collection errors.
Implementation was committed before mutation; each target was asserted unique
and restored from an exact temporary backup. The final full suite passed after
restoration. These are behavioral mutations of the Qt implementation; restoring
the removed Pygame module would only produce irrelevant import errors.

## Real-display interaction check

Used the real CLI engine factory, PortAudio output, RtMidi, the real BPM worker,
and native Qt file dialog. QtTest mouse/key events and a Qt file-drop event drove
the actual X11 window; screenshots were visually inspected. This was an agent-driven
real-display check, not a claim of a human acceptance test. No fake engine or
position jump was used. The first native Save dialog was completed via xdotool;
the repeat run selected the path through the real QFileDialog.

Launched without a **setlist argument**, with `--midi-port 0` to select MIDI
Through among this machine's three outputs. The literal no-argument appstate
path is separately covered by the CLI widget test; multiple-output selection
semantics are unchanged from the previous release.

| State | Evidence |
|---|---|
| New empty editor | [01-empty-editor.png](01-empty-editor.png) |
| Dropped `songs/neon_undertow_trimmed.wav`; suggestion **~111.9** saved | [02-bpm-suggestion.png](02-bpm-suggestion.png) |
| Confirmed **112**, Play Set opens playback | [03-playing.png](03-playing.png) |
| Pause; resume continues playback | [04-paused.png](04-paused.png) |
| Natural end of the 49.162-second track; Restart and Return visible | [05-end-of-set.png](05-end-of-set.png) |
| Restart button begins at the top (position about 1 second) | [06-restarted.png](06-restarted.png) |
| Skip reaches end; Return to Editor closes engines | [07-returned-editor.png](07-returned-editor.png) |

The screenshot runs logged two audio underruns by natural end, and two more
around restart/skip; they recorded zero dropped MIDI ticks at natural end.
Those observations are retained rather than treated as a clean jitter result.
The final GUI avoids reapplying the playback stylesheet on every timer tick.

## MIDI sanity check

A final 12-second run of the real Qt playback window on **Midi Through Port-0**
measured **111.994832 BPM** at the declared 112 BPM: **540 ticks**, one Start,
one Stop, **zero audio underruns**, and **zero dropped ticks**. Exit code **0**.
Four `aconnect -l` snapshots showed only this run's sender and receiver attached
to MIDI Through. See [midi-check.json](midi-check.json) and the
[received MIDI timestamps](midi-check-raw.json).

This is an average-tempo sanity check, not a new cross-platform jitter/phase
qualification. It uses `60 * (tick_count - 1) / (24 * elapsed_tick_seconds)`.

The earlier full desktop runs saw five Start/Stop pairs instead of the expected
three, with mixed readings of 143 and 160 BPM. They are **excluded from tempo
validation**, but their UI assertions all succeeded. The PM confirmed concurrent
MIDI Through probes during the first run; the second run also contained extra
transport messages, with no source attribution established. The original
reports and raw events remain in `desktop-run*.json` and `midi-received*.json`;
their `passed: false` reflects the invalid combined tempo measurement. This
machine was being used concurrently for other audio/MIDI work.

## Remaining platform coverage

Windows/macOS native behavior and a PyInstaller distribution were not exercised
in this task. Packaging instructions cover the new PySide6 dependency and Qt
platform plugins. The original GUI-independent engines and timing contracts
remain unchanged by the Qt implementation.
