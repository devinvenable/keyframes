# Native Windows build verification — task 107

Built and exercised on the physical Windows box `192.168.1.225` on
2026-09-21 (America/Chicago), using native x64 Python 3.11.9, PyInstaller
6.22.3 and PySide6 6.11.2. Windows reports build 26200. SSH lands in WSL;
PowerShell, pip, PyInstaller, the verifier and ShowSync.exe all run natively.

Delivered artifact: `/home/devin/src/2026/midi/dist/ShowSync_Windows.zip`
(89,942,768 bytes), also retained in this worktree's `showsync/dist/` and on
Windows at `C:\Users\devin\src\showsync-build\showsync\dist\ShowSync_Windows.zip`.
Source revision: `3c3f546223a8d58ed541c297fe5c753bdfeccdc3` (includes task 106).
SHA-256: `92ce3c2e2d0a85796ff43784b1097b35348db225e93dfd4260b09ae0483ee827`.
The final documentation/evidence commit follows that source build.

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

## Observed behavior

The verifier extracts the ZIP into a temporary directory containing spaces,
outside the checkout, clears Python/Qt search paths, restricts PATH to Windows
System32 and uses isolated application state. It drives the frozen executable
through Windows UI Automation, without importing ShowSync into the verifier.

- `ShowSync.exe --list-devices` listed eight PortAudio entries (MME,
  DirectSound, WASAPI and WDM-KS), and `Microsoft GS Wavetable Synth 0`.
- The frozen CLI exported a portable three-song show bundle; the verifier
  extracted it into another directory and opened that YAML in the editor.
- Play Set opened the MIDI output and played the generated 100 BPM WAV.
  WASAPI loopback recorded the default **Digital Output (2- High Definition
  Audio Device)** endpoint. Captured click intervals were 0.600 seconds.
- Pause changed the UI to Paused and the captured output became exactly silent.
  Stop returned to the editor; the application exited normally.
- A second set played the M4A fixture repeatedly. Nonzero loopback output
  demonstrated FFmpeg decoding as well as the WAV/libsndfile path.
- The DLL inventory includes Qt's Windows platform plugin, PortAudio,
  libsndfile and FFmpeg libraries. The frozen GUI and both decoder paths
  completed without missing-DLL crashes or console errors.

The [committed evidence](windows-verification/) includes the report with ZIP
SHA-256 and source revision, screenshots, device list, DLL inventory and build
log. Full WAV captures remain beside the ZIP in `dist/windows-verification/`.
The durable project-level copy is `dist/showsync-windows-verification/`.
The ZIP includes icons, relative-path demo media, dependency version inventory,
source commit, README and license texts; users do not need Python installed.

## Negative control

After committing the implementation, a separate copy of the ZIP had only
`ShowSync/demo/demo-100.wav` replaced by silent samples, preserving its format
and duration. The verifier opened the same UI and reached Play Set, then failed
at **`AssertionError: Windows output capture is silent`**. This was an assertion
failure, not an import, collection or setup error. The original ZIP's SHA-256
was checked before and after and was unchanged. The temporary mutated ZIP was
deleted. Evidence is in `windows-verification/negative-control.json` and
`windows-verification/negative-report.json`.

The local ShowSync suite after merging bundle export: **458 passed, 4 skipped**
(`QT_QPA_PLATFORM=offscreen`, shared project venv). The skipped tests require
devices; this Windows run independently exercises real output through the
frozen application. Shell syntax and Python compilation checks also passed.

## Scope

This verifies the extracted release on the build machine with its installed
drivers, not a fresh Windows account or a different audio interface. Audio is
verified at the Windows loopback endpoint, not with an external microphone.
Opening the software MIDI synth verifies RT-MIDI availability; it does not
measure clock jitter or validate external hardware synchronization. loopMIDI
timing work remains task 67. The executable is unsigned; code signing is out
of scope. Native file dialogs and a full performance-length set are not part
of this smoke test.
