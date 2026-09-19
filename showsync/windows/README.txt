SHOWSYNC FOR WINDOWS
====================

Use native 64-bit Python 3.11 or newer (not WSL Python).
From the showsync folder in PowerShell:

  py -3.11 -m venv venv
  .\venv\Scripts\python.exe -m pip install -r requirements.txt
  .\venv\Scripts\python.exe main.py --list-devices
  .\venv\Scripts\python.exe main.py C:\Shows\setlist.yaml --audio-device 4 --midi-port "Your MIDI output"

Use the actual device indexes/names from --list-devices. WASAPI is a useful
starting point; verify the chosen output and latency on your performance rig.
Space pauses/resumes, N skips, Q quits. The buttons also accept mouse clicks.
Resume sends MIDI Start, so external patterns restart (v1 has no SPP/Continue).
Keep setlists and backing tracks in editable folders outside the application.

PACKAGING (same one-folder distribution approach as Keyframes)

Build on Windows using native Windows Python, never PyInstaller under WSL.
In a build venv, install requirements.txt plus PyInstaller, then run:

  python -m PyInstaller --noconfirm --clean --onedir --name ShowSync --collect-all av --collect-all sounddevice --collect-all soundfile --collect-all rtmidi main.py

Keep the entire dist\ShowSync folder together; distribute it as a zip, with
this README and an example setlist. Run ShowSync.exe from a terminal or a
shortcut whose arguments contain the setlist path. Retaining the console
makes device/decode errors visible. Setlists/audio are never embedded.
Validate av/FFmpeg DLLs, soundfile/libsndfile, PortAudio, pygame and RT-MIDI
on a clean Windows account before publishing an executable. No frozen
ShowSync distribution has been built or verified by task 65.

For a jitter measurement, Windows needs a real MIDI loopback cable or an
installed loopMIDI route. WinMM cannot create virtual ports itself. Do not
use Microsoft GS Wavetable Synth as a clock loopback; it has no MIDI input.
See docs/verification.md for actual machine results and limitations.
