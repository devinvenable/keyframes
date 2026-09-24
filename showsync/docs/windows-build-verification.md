# Native Windows build verification

Current release: built and exercised on the physical Windows box
`192.168.1.225` on 2026-09-24 (America/Chicago) for task 123, using native
x64 Python 3.11.9, PyInstaller 6.22.x and PySide6 6.11.x on Windows build
26200. SSH lands in WSL; PowerShell, pip, PyInstaller, the verifiers and
ShowSync.exe all run natively. The previous release (task 107, source
`3c3f546`, ZIP SHA-256 `92ce3c2e…ee827`) followed the same procedure; its
narrative is preserved by git history.

Delivered artifact: `dist/ShowSync_Windows.zip`.
Source revision: `232153e91fe245662288c58cbdd6c0f2b3ded0ad` — main @
`0308779` (T112 per-song GM MIDI, T114 video + projector window, T115 show
bundle import, T118+T120 windowed partial BPM, T121 per-song trim +
Align-to-the-one) plus verification-script-only commits.
ZIP SHA-256: `61908dd341937156f3d65d0fc72273291aefb2eb081d0ba7ccb22cfd28a562c0`.
Local suite at this revision: 532 passed, 4 skipped
(`QT_QPA_PLATFORM=offscreen`; the skips need real devices).

## Reproduce

From a clean committed checkout:

```sh
showsync/scripts/build-windows.sh
# Reuse the dedicated Windows venv on subsequent builds:
showsync/scripts/build-windows.sh --skip-deps
```

The driver pushes and checks out the exact source revision, then returns
`showsync/dist/ShowSync_Windows.zip` and `showsync/dist/windows-verification/`.
It refuses uncommitted source and does not return a release if verification
fails. See [the Windows README](../windows/README.txt) for native PowerShell
commands, host overrides, requirements and standalone verification.

## Standard smoke (scripts/verify_windows.py, run by the build)

The verifier extracts the ZIP into a temporary directory containing spaces,
outside the checkout, clears Python/Qt search paths, restricts PATH to Windows
System32 and uses isolated application state. It drives the frozen executable
through Windows UI Automation, without importing ShowSync into the verifier.

- `--list-devices` listed the box's PortAudio endpoints (MME, DirectSound,
  WASAPI, WDM-KS) and `Microsoft GS Wavetable Synth 0`.
- The frozen CLI exported a show bundle; the verifier extracted it elsewhere
  and opened that YAML in the editor.
- Play Set opened the MIDI output and played the generated 100 BPM WAV;
  WASAPI loopback captured click intervals of 0.600 s on the default
  endpoint. Pause silenced the capture exactly; Stop returned to the editor
  and the application exited normally.
- A second set decoded M4A repeatedly, proving the FFmpeg path beyond
  libsndfile. The DLL inventory includes Qt's Windows platform plugin,
  PortAudio, libsndfile and FFmpeg libraries.

Evidence: `dist/windows-verification/` (report.json with ZIP SHA-256 and
source commit, screenshots, device list, DLL inventory, loopback WAVs).

## Feature verification (scripts/verify_windows_features.py)

A second UI-Automation pass over the *same delivered ZIP* exercises the
features new since the task-107 release, using Devin's real 215 MB
`demo_with_video.zip` show bundle (SHA-256 `ba73bbbd…fd29`, validated
untouched). Evidence: `dist/windows-features/`.

- **Bundle import (T115)** — frozen `--import-bundle` unpacked the bundle;
  all six files matched the archive's sizes and the reported setlist opened.
- **Video playback + projector window (T114)** — the imported set's first
  song (`clock_divider_missing_on_the_one.mp4`) played with audible loopback
  output (peak 0.749) and the separate ShowSync Video window appeared and
  was captured mid-playback, then hid on Stop. Note for UIA scripting: Qt
  surfaces the owned projector window *nested under the main window*, not
  as a top-level window.
- **Per-song GM MIDI (T112)** — a generated 24-beat `.mid` beside a silent
  WAV produced loopback audio (peak 0.137) that can only originate from
  MIDI events rendered by the GS Wavetable synth; the same silent WAV
  without the `midi:` key captured exactly 0.0 in the same window.
- **Per-song trim (T121)** — a file silent for its first 10 s with a tone
  after, played with `trim: 10`, was audible immediately (RMS 0.283) and
  reported exactly 10 s less remaining than the untrimmed control run of
  the same file, which stayed silent through the same capture window.
- **Windowed partial BPM (T118+T120)** — a setlist row referencing the
  bundle's video song without any `bpm:` showed the partial estimate
  `~106.001?` in the editor's BPM column (the bundle's own row carries an
  explicit 106, which was left untouched).

## Negative controls

Both controls ran against the delivered ZIP after the positive passes; the
original ZIP hash was checked before and after and was unchanged.

- **Silent audio** (`scripts/negative_control_windows.py`, evidence
  `dist/windows-negative-control/`): a copy of the ZIP with only
  `demo/demo-100.wav` replaced by same-format silence made
  `verify_windows.py` fail on `AssertionError: Windows output capture is
  silent` — an assertion failure, not an import or setup error.
- **MIDI discriminator** (`verify_windows_features.py --negative midi`,
  evidence `dist/windows-features-negative/`): the MIDI loopback assertion
  run against the silent no-`midi:` setlist failed on
  `MIDI capture is silent`, proving the capture discriminates GS Wavetable
  output from nothing.

## Scope

This verifies the extracted release on the build machine with its installed
drivers, not a fresh Windows account or another audio interface. Audio is
verified at the Windows loopback endpoint. Opening the software MIDI synth
verifies RT-MIDI availability, not clock jitter (task 67) or external
hardware sync. The executable is unsigned (code signing is task 58); David
will see SmartScreen. Native file dialogs and a full performance-length set
are not part of this smoke test.
