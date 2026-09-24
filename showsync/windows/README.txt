SHOWSYNC FOR WINDOWS
====================

PREBUILT RELEASE

Extract ShowSync_Windows.zip to a writable folder and keep the entire ShowSync
folder together, including _internal. Python is not needed to run this build.
In PowerShell, from the extracted ShowSync folder:

  .\ShowSync.exe --list-devices
  .\ShowSync.exe .\demo\setlist.yaml

Press Play Set for the supplied 100 BPM / tempo ramp / 140 BPM click tracks.
The demo uses relative audio paths and can be moved with its WAV files.
The console remains visible for device/decode errors. The executable is unsigned.

To move your own show between machines, use File > Export Show Bundle /
File > Import Show Bundle, or:

  .\ShowSync.exe C:\Shows\setlist.yaml --export-bundle C:\Shows\my-show.zip
  .\ShowSync.exe --import-bundle C:\Shows\my-show.zip C:\Shows\my-show

Import unpacks the bundle (default: a folder named after the zip, beside it)
and prints the setlist to open. Choose audio/MIDI devices for the destination
machine; machine preferences are not in the bundle. Songs whose file is MP4,
M4V, MPG, MPEG, or MOV open the separate ShowSync Video projector window
during playback (double-click or F11 for fullscreen). A song may also carry
midi: (a GM .mid scheduled on the beat grid) and trim: (playback and the
MIDI clock start that many seconds into the file, non-destructively).

RUNNING FROM SOURCE

Use native 64-bit Python 3.11 or newer (not WSL Python).
From the showsync folder in PowerShell:

  py -3.11 -m venv venv
  .\venv\Scripts\python.exe -m pip install -r requirements.txt
  .\venv\Scripts\python.exe main.py --list-devices
  .\venv\Scripts\python.exe main.py C:\Shows\setlist.yaml --audio-device 4 --midi-port "Your MIDI output"

Use the actual device indexes/names from --list-devices. WASAPI is a useful
starting point; verify the chosen output and latency on your performance rig.
Use Play Set in the editor, then Pause, Skip, Restart, and Return to Editor.
Keyboard shortcuts are listed in the menus; F11 toggles fullscreen.
Resume sends MIDI Start, so external patterns restart (v1 has no SPP/Continue).
Keep setlists and backing tracks in editable folders outside the application.

PACKAGING (same one-folder distribution approach as Keyframes)

Build on Windows using native Windows Python, never PyInstaller under WSL.
The repeatable build creates a dedicated showsync\venv, installs dependencies,
freezes the app, generates demo audio, and verifies the extracted ZIP:

  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows.ps1

Pass -Revision <source-commit> if native Windows Git is not installed (the Linux
driver supplies this automatically). Use -SkipDeps to reuse installed dependencies,
or -Clean to remove prior build
outputs. Native Python 3.11 is selected with py -3.11 when creating the venv.
The result is dist\ShowSync_Windows.zip. dist\windows-verification contains
device enumeration, DLL inventory, screenshots, loopback WAV recordings and
report.json with the source commit, ZIP SHA-256 and playback assertions.

From Linux, with a clean committed branch and SSH access to the Windows box:

  showsync/scripts/build-windows.sh [--skip-deps] [--clean]

This pushes the branch and checks out the exact commit in a dedicated remote
clone. WSL is only the SSH/file transport; native PowerShell and Windows Python
build and verify. Defaults: devin@192.168.1.225 and
/mnt/c/Users/devin/src/showsync-build. Override SHOWSYNC_WINDOWS_HOST,
SHOWSYNC_WINDOWS_REPO and SHOWSYNC_WINDOWS_POWERSHELL when needed. The ZIP and
verification evidence are copied back to showsync/dist only after success.

The underlying freeze command (from showsync/) is:

  $icons = Join-Path (Get-Location) 'showsync\icons'
  python -m PyInstaller --noconfirm --clean --onedir --console --name ShowSync --specpath build --collect-all av --collect-all sounddevice --collect-all soundfile --collect-all rtmidi --hidden-import mido.backends.rtmidi --add-data "${icons}:showsync/icons" --icon "$icons\showsync.ico" main.py

Keep the entire dist\ShowSync folder together; distribute it as a zip, with
this README and an example setlist. Run ShowSync.exe from a terminal or a
shortcut whose arguments contain the setlist path. Retaining the console
makes device/decode errors visible. Setlists/audio are never embedded.
The verifier runs the extracted executable outside the source tree with Python
and Qt search paths cleared. It checks audio/MIDI enumeration, exports and
reopens a show bundle, invokes Play Set using Windows UI Automation, records
100 BPM clicks through WASAPI loopback, checks Pause silences them, returns to
the editor, and plays M4A to exercise FFmpeg decoding. This needs a logged-in,
unlocked Windows desktop, an audible default stereo output, and a MIDI output
(the Windows software synth is enough to check opening RT-MIDI, not timing).
Keep other audio quiet during verification. Build-host verification packages
are listed in windows/requirements-verify.txt; they are not bundled in the app.
To repeat verification without rebuilding:

  .\venv\Scripts\python.exe scripts\verify_windows.py dist\ShowSync_Windows.zip dist\windows-verification

Two further scripts exercise the delivered ZIP beyond the standard smoke:
scripts\verify_windows_features.py drives bundle import, video playback with
the projector window, per-song GM MIDI (heard through the GS Wavetable synth
over loopback), per-song trim, and the partial BPM estimate against a real
show-bundle zip; scripts\negative_control_windows.py proves the standard
verifier fails on a silenced copy of the release. See
docs/windows-build-verification.md for the recorded runs.

This is a playback/packaging smoke test, not MIDI jitter or clean-account
certification. Check native file dialogs, hardware MIDI and your chosen audio
interface on the performance machine. See docs/windows-build-verification.md
for the actual Windows run and evidence.

Use a dedicated build environment containing only the PySide6 Qt binding.
PyInstaller hooks collect Qt libraries and platform plugins from PySide6.
Keep those plugin directories and the bundled Qt license files in the
one-folder distribution. Tkinter and pygame are not ShowSync dependencies.
The same build command can be used on Linux/macOS on the target OS; test
the xcb/cocoa plugin, native dialogs, audio codecs, and MIDI on a clean machine.
Qt increases the package footprint compared with the original Pygame GUI.

For a jitter measurement, Windows needs a real MIDI loopback cable or an
installed loopMIDI route. WinMM cannot create virtual ports itself. Do not
use Microsoft GS Wavetable Synth as a clock loopback; it has no MIDI input.
See docs/verification.md for actual machine results and limitations.
