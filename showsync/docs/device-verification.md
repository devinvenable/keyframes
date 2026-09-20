# Playback device verification — task 85

The PM relayed Devin's amended requirement: no chooser on Play. Preferences is
optional; missing choices fall back automatically, including audio-only playback
when no MIDI output exists.

Validation (2026-09-20):

- `QT_QPA_PLATFORM=offscreen /home/devin/src/2026/midi/venv/bin/python -m pytest -q`
  from `showsync/`: **162 passed in 5.79s, exit 0**.
- Six new pytest-qt/controller tests cover fresh-state Play without a prompt,
  Preferences selection and persistence across windows, unplugged-device fallback,
  a lone virtual output and zero outputs, Refresh/Cancel, CLI precedence and
  audio-only engine startup.
- Each new test was run against a targeted mutation after committing the
  implementation. All six failed on assertions (exit 1), then exact file backups
  were restored. See `device-mutations.json` for targets and results.
- Real hardware enumeration returned Midi Through and both MIDIPLUS TBOX outputs.
  Fresh-state resolution picked
  `MIDIPLUS TBOX 2x2:MIDIPLUS TBOX 2x2 Midi Out 1 36:0`; audio remained system
  default (`None`). Eleven audio output devices were enumerated.
- No audible hardware playback was performed. GUI playback tests use real Qt
  widgets and the audio model with mocked device access.
- Keyframes was untouched.
