r"""Exercise T112/T114/T115/T118+T120 features in the frozen Windows build.

Complements verify_windows.py (standard smoke). Run with the build venv's
native Windows Python in a logged-in desktop session:

  venv\Scripts\python.exe scripts\verify_windows_features.py ^
      dist\ShowSync_Windows.zip C:\path\to\demo_with_video.zip dist\windows-features

Checks, each leaving evidence files:
  import   -- --import-bundle extracts the show bundle ZIP; file inventory matches.
  video    -- the imported setlist's video song plays: audible loopback audio and
              the separate ShowSync Video window appears with playback running.
  midi     -- a generated .mid + silent WAV song produces loopback audio through
              the Microsoft GS Wavetable synth: audio can only come from MIDI
              events actually scheduled and sent. A control run of the same
              silent WAV without the midi key must stay silent.
  bpm      -- a copy of the video song's setlist row without bpm gets a partial
              (~N?) estimate in the editor's BPM column.
  trim     -- a song whose file is silent for 10s then a steady tone, with
              trim: 10, is audible immediately and reports ~10s less remaining
              than an untrimmed control run of the same file.

--negative midi runs the MIDI loopback assertion against the control setlist
(no midi key) and must fail on 'MIDI capture is silent'; used once per release
to prove the discriminator discriminates.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import time
import traceback
import zipfile


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def isolated_env(base):
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        env.pop(key, None)
    env['APPDATA'] = str(base / 'appdata')
    env['PATH'] = str(Path(env['SYSTEMROOT']) / 'System32')
    return env


def write_midi_fixture(directory):
    """Quarter notes covering 24 beats; audible on any GM synth."""
    import mido
    track = mido.MidiTrack()
    track.append(mido.Message('program_change', program=0, time=0))
    for beat in range(24):
        note = (60, 64, 67)[beat % 3]
        track.append(mido.Message('note_on', note=note, velocity=100, time=0))
        track.append(mido.Message('note_off', note=note, velocity=0, time=480))
    source = mido.MidiFile(ticks_per_beat=480)
    source.tracks.append(track)
    path = directory / 'notes.mid'
    source.save(path)
    return path


def write_silence_fixture(directory):
    import numpy as np
    import soundfile as sf
    path = directory / 'silence.wav'
    sf.write(path, np.zeros((48000 * 14, 2), dtype='float32'), 48000)
    return path


def write_trim_fixture(directory):
    """30s WAV: silence for 10s, then a steady 440 Hz tone."""
    import numpy as np
    import soundfile as sf
    path = directory / 'late-tone.wav'
    samples = np.zeros((48000 * 30, 2), dtype='float32')
    t = np.arange(48000 * 20) / 48000
    samples[48000 * 10:] = (0.4 * np.sin(2 * np.pi * 440 * t)).astype('float32')[:, None]
    sf.write(path, samples, 48000)
    return path


class Harness:
    def __init__(self, exe, base, evidence, report):
        import soundcard as sc
        self.exe, self.base, self.evidence, self.report = exe, base, evidence, report
        speaker = sc.default_speaker()
        self.loopback = sc.get_microphone(speaker.id, include_loopback=True)
        report['loopback_output'] = speaker.name

    def capture(self, name, seconds):
        import numpy as np
        import soundfile as sf
        samples = self.loopback.record(samplerate=48000,
                                       numframes=int(48000 * seconds), channels=2)
        sf.write(self.evidence / f'{name}.wav', samples, 48000)
        self.report[name] = {'rms': float(np.sqrt(np.mean(samples ** 2))),
                             'peak': float(np.max(np.abs(samples)))}
        return samples

    def open_editor(self, setlist, name):
        from pywinauto import Application
        print(f'Opening frozen executable: {name}', flush=True)
        log = (self.evidence / f'{name}-console.txt').open('w', encoding='utf-8')
        proc = subprocess.Popen([str(self.exe), str(setlist)], cwd=self.base,
                                env=isolated_env(self.base), stdout=log,
                                stderr=subprocess.STDOUT)
        app = Application(backend='uia').connect(process=proc.pid, timeout=40)
        window = app.window(title_re='.*showsync.*', control_type='Window')
        window.wait('visible', timeout=40)
        return proc, app, window

    def close(self, proc, window, graceful=True):
        try:
            if graceful:
                window.close()
                check(proc.wait(timeout=15) == 0, 'Frozen GUI exited with an error')
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)

    def play(self, window, name):
        play = window.child_window(title='Play Set', control_type='Button')
        play.wait('enabled', timeout=30)
        window.set_focus()
        time.sleep(.3)
        window.capture_as_image().save(self.evidence / f'{name}-editor.png')
        play.invoke()
        window.child_window(title='Playing', control_type='Text').wait('visible', timeout=40)

    def stop(self, window, name):
        window.child_window(title='Stop', control_type='Button').invoke()
        window.child_window(title='Play Set', control_type='Button').wait('visible', timeout=10)
        window.capture_as_image().save(self.evidence / f'{name}-returned-editor.png')


def check_import(harness, bundle, dest):
    result = subprocess.run([str(harness.exe), '--import-bundle', str(bundle), str(dest)],
                            cwd=harness.base, env=isolated_env(harness.base),
                            capture_output=True, text=True, timeout=300)
    (harness.evidence / 'import.txt').write_text(result.stdout + result.stderr,
                                                 encoding='utf-8')
    check(result.returncode == 0, 'Frozen --import-bundle failed')
    with zipfile.ZipFile(bundle) as archive:
        expected = {i.filename: i.file_size for i in archive.infolist() if i.file_size}
    extracted = {p.name: p.stat().st_size for p in Path(dest).rglob('*') if p.is_file()}
    harness.report['imported_files'] = extracted
    for name, size in expected.items():
        check(extracted.get(Path(name).name) == size,
              f'Imported bundle is missing or truncates {name}')
    setlists = [p for p in Path(dest).rglob('*.yaml')]
    check(len(setlists) == 1, f'Expected one imported setlist, found {setlists}')
    check('Extracted to' in result.stdout and setlists[0].name in result.stdout,
          'Import did not report the setlist path')
    return setlists[0]


def check_video(harness, setlist):
    proc, app, window = harness.open_editor(setlist, 'video')
    try:
        harness.play(window, 'video')
        # Qt surfaces the owned projector window nested under its owner in
        # UIA, not as a top-level window; search the whole element tree.
        video = app.window(title_re='ShowSync Video.*', control_type='Window',
                           top_level_only=False)
        video.wait('visible', timeout=30)
        # Let playback and the decoder settle before judging audio or frames.
        time.sleep(2)
        harness.capture('video-playing', 5)
        check(harness.report['video-playing']['peak'] > 0.001,
              'Video song produced no loopback audio')
        window.capture_as_image().save(harness.evidence / 'video-playing.png')
        video.capture_as_image().save(harness.evidence / 'video-window.png')
        texts = [item.window_text() for item in window.descendants(control_type='Text')]
        harness.report['video_playback_labels'] = texts
        harness.stop(window, 'video')
        hidden = not (video.exists() and video.is_visible())
        check(hidden, 'Video window did not hide after Stop')
        harness.close(proc, window)
    finally:
        harness.close(proc, window, graceful=False)


def play_capture(harness, setlist, name, *, require_midi=False):
    proc, app, window = harness.open_editor(setlist, name)
    try:
        harness.play(window, name)
        time.sleep(2)
        harness.capture(f'{name}-playing', 5)
        texts = [item.window_text() for item in window.descendants(control_type='Text')]
        harness.report[f'{name}_playback_labels'] = texts
        if require_midi:
            check(any(t.startswith('MIDI: ') and 'No output' not in t for t in texts),
                  'No MIDI output was opened during playback')
        harness.stop(window, name)
        harness.close(proc, window)
    finally:
        harness.close(proc, window, graceful=False)
    return harness.report[f'{name}-playing']


def remaining_seconds(harness, name):
    labels = harness.report[f'{name}_playback_labels']
    matches = [re.search(r'(\d+):(\d+) remaining', t) for t in labels]
    times = [int(m.group(1)) * 60 + int(m.group(2)) for m in matches if m]
    check(times, f'No remaining-time label during {name}; saw {labels}')
    return times[0]


def check_trim(harness, fixtures):
    tone = write_trim_fixture(fixtures)
    trimmed = fixtures / 'trimmed.yaml'
    trimmed.write_text('title: Trim smoke\naudio_root: .\nsongs:\n'
                       f'  - name: Late tone trimmed\n    file: {tone.name}\n'
                       '    bpm: 120\n    trim: 10\n', encoding='utf-8')
    untrimmed = fixtures / 'untrimmed.yaml'
    untrimmed.write_text('title: Trim control\naudio_root: .\nsongs:\n'
                         f'  - name: Late tone untrimmed\n    file: {tone.name}\n'
                         '    bpm: 120\n', encoding='utf-8')
    loud = play_capture(harness, trimmed, 'trim')
    check(loud['peak'] > 0.01,
          'Trimmed song was not audible at once; trim did not move the start')
    quiet = play_capture(harness, untrimmed, 'trim-control')
    check(quiet['peak'] < loud['peak'] * .05,
          'Untrimmed control was already audible; tone fixture proves nothing')
    shift = remaining_seconds(harness, 'trim-control') - remaining_seconds(harness, 'trim')
    harness.report['trim_remaining_shift_seconds'] = shift
    check(7 <= shift <= 13, f'Remaining time shifted by {shift}s, expected ~10s trim')


def check_midi(harness, fixtures, negative=False):
    midi = write_midi_fixture(fixtures)
    silence = write_silence_fixture(fixtures)
    with_midi = fixtures / 'midi-song.yaml'
    with_midi.write_text('title: MIDI file smoke\naudio_root: .\nsongs:\n'
                         f'  - name: GM notes\n    file: {silence.name}\n'
                         f'    midi: {midi.name}\n    bpm: 120\n', encoding='utf-8')
    control = fixtures / 'midi-control.yaml'
    control.write_text('title: MIDI control\naudio_root: .\nsongs:\n'
                       f'  - name: Silence only\n    file: {silence.name}\n'
                       '    bpm: 120\n', encoding='utf-8')
    if negative:
        # The .mid is absent: the same assertion must fail, proving the
        # loopback capture discriminates GS Wavetable output from nothing.
        levels = play_capture(harness, control, 'negative-midi', require_midi=True)
        try:
            check(levels['peak'] > 0.005, 'MIDI capture is silent')
        except AssertionError as exc:
            harness.report['negative_expected_failure'] = str(exc)
            return
        raise AssertionError('Negative control unexpectedly produced audio')
    levels = play_capture(harness, with_midi, 'midi', require_midi=True)
    check(levels['peak'] > 0.005, 'MIDI capture is silent')
    quiet = play_capture(harness, control, 'midi-control', require_midi=True)
    check(quiet['peak'] < levels['peak'] * .05,
          'Control without a midi key was not silent; audio evidence is ambiguous')


def check_bpm(harness, setlist, source):
    unknown = setlist.parent / 'bpm-check.yaml'
    unknown.write_text('title: Partial BPM check\naudio_root: .\nsongs:\n'
                       f'  - name: clock_divider unknown bpm\n    file: {source}\n',
                       encoding='utf-8')
    proc, app, window = harness.open_editor(unknown, 'bpm')
    try:
        deadline = time.monotonic() + 600
        cells = []
        while time.monotonic() < deadline:
            try:
                texts = [item.window_text() for item in window.descendants()]
            except Exception:
                texts = []
            cells = sorted({t for t in texts if re.fullmatch(r'~[\d.]+\??', t)})
            if cells and not any('Analyzing' in t or 'Queued' in t for t in texts):
                break
            time.sleep(10)
        harness.report['bpm_cells'] = cells
        window.capture_as_image().save(harness.evidence / 'bpm-editor.png')
        partial = [t for t in cells if t.endswith('?')]
        check(partial, f'No partial (~N?) BPM estimate appeared; saw {cells}')
        value = float(partial[0].strip('~?'))
        harness.report['bpm_partial_estimate'] = value
        check(90 <= value <= 125, f'Partial estimate {value} is implausible for ~106 BPM')
    finally:
        # Applied suggestions leave the document dirty; a graceful close would
        # block on the save prompt, so end the process after capturing evidence.
        harness.close(proc, window, graceful=False)


def verify(archive, bundle, evidence, report, negative):
    report.update(platform=platform.platform(),
                  zip_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                  bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest())
    with tempfile.TemporaryDirectory(prefix='ShowSync features ') as temp:
        base = Path(temp)
        with zipfile.ZipFile(archive) as release:
            release.extractall(base)
        package = base / 'ShowSync'
        report['build_commit'] = (package / 'build-commit.txt').read_text().strip()
        harness = Harness(package / 'ShowSync.exe', base, evidence, report)
        fixtures = base / 'fixtures'
        fixtures.mkdir()
        if negative == 'midi':
            check_midi(harness, fixtures, negative=True)
            report['passed'] = True
            return
        setlist = check_import(harness, bundle, base / 'imported show')
        check_video(harness, setlist)
        check_midi(harness, fixtures)
        check_trim(harness, fixtures)
        check((setlist.parent / 'clock_divider_missing_on_the_one.mp4').is_file(),
              'Imported bundle is missing the video song')
        check_bpm(harness, setlist, 'clock_divider_missing_on_the_one.mp4')
    report['passed'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--negative', choices=['midi'])
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    report = {'passed': False}
    try:
        verify(args.archive.resolve(), args.bundle.resolve(), args.evidence.resolve(),
               report, args.negative)
    except Exception:
        report['error'] = traceback.format_exc()
        raise
    finally:
        (args.evidence / 'report.json').write_text(json.dumps(report, indent=2),
                                                   encoding='utf-8')
    print('ShowSync frozen feature verification '
          + ('negative control behaved as designed' if args.negative else 'passed'),
          flush=True)


if __name__ == '__main__':
    main()
