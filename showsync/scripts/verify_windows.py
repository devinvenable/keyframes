"""Exercise the delivered ZIP with Windows UI Automation and WASAPI loopback.

Run with native Windows Python in a logged-in desktop session. Dependencies
are in windows/requirements-verify.txt and are not part of the frozen app.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time
import traceback
import zipfile


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def verify(archive, evidence, report):
    import numpy as np
    from pywinauto import Application
    import soundcard as sc
    import soundfile as sf

    report.update(platform=platform.platform(), zip_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    speaker = sc.default_speaker()
    loopback = sc.get_microphone(speaker.id, include_loopback=True)
    report['loopback_output'] = speaker.name
    with tempfile.TemporaryDirectory(prefix='ShowSync smoke ') as temp:
        base = Path(temp)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(base)
        package = base / 'ShowSync'
        exe = package / 'ShowSync.exe'
        report['build_commit'] = (package / 'build-commit.txt').read_text().strip()
        report['extracted_path'] = str(package)
        env = os.environ.copy()
        # Do not inherit Python/Qt paths or the user's remembered device choices.
        for key in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
            env.pop(key, None)
        env['APPDATA'] = str(base / 'appdata')
        env['PATH'] = str(Path(env['SystemRoot']) / 'System32')
        devices = subprocess.run([str(exe), '--list-devices'], cwd=base, env=env,
                                 capture_output=True, text=True, timeout=45)
        (evidence / 'devices.txt').write_text(devices.stdout + devices.stderr, encoding='utf-8')
        check(devices.returncode == 0, 'Frozen --list-devices failed')
        check('MIDI outputs:' in devices.stdout and 'out)' in devices.stdout,
              'Frozen executable did not enumerate audio and MIDI')
        report['devices'] = devices.stdout
        dlls = [str(p.relative_to(package)) for p in package.rglob('*.dll')]
        (evidence / 'dlls.json').write_text(json.dumps(dlls, indent=2))
        for fragment in ('qwindows.dll', 'sndfile', 'portaudio', 'avcodec', 'avformat'):
            check(any(fragment in p.lower() for p in dlls), f'Missing bundled {fragment}')

        def capture(name, seconds):
            samples = loopback.record(samplerate=48000, numframes=int(48000 * seconds), channels=2)
            sf.write(evidence / f'{name}.wav', samples, 48000)
            report[name] = {'rms': float(np.sqrt(np.mean(samples ** 2))),
                            'peak': float(np.max(np.abs(samples)))}
            return samples

        def run_set(setlist, name, demo=False):
            print(f'Opening frozen executable: {name}', flush=True)
            with (evidence / f'{name}-console.txt').open('w', encoding='utf-8') as log:
                proc = subprocess.Popen([str(exe), str(setlist)], cwd=base, env=env,
                                        stdout=log, stderr=subprocess.STDOUT)
                try:
                    app = Application(backend='uia').connect(process=proc.pid, timeout=40)
                    window = app.window(title_re='.*showsync.*', control_type='Window')
                    window.wait('visible', timeout=40)
                    play = window.child_window(title='Play Set', control_type='Button')
                    play.wait('enabled', timeout=30)
                    window.capture_as_image().save(evidence / f'{name}-editor.png')
                    play.invoke()
                    window.child_window(title='Playing', control_type='Text').wait('visible', timeout=30)
                    samples = capture(f'{name}-playing', 5 if demo else 0.5)
                    check(report[f'{name}-playing']['peak'] > 0.001, 'Windows output capture is silent')
                    window.capture_as_image().save(evidence / f'{name}-playing.png')
                    if demo:
                        # Known 100 BPM clicks discriminate ShowSync from unrelated
                        # system sound; Pause must then silence the same endpoint.
                        envelope = np.max(np.abs(samples[:len(samples) // 480 * 480]).reshape(-1, 480, 2), axis=(1, 2))
                        active = envelope > envelope.max() * 0.2
                        onsets = np.flatnonzero(active & ~np.r_[False, active[:-1]])
                        intervals = np.diff(onsets) * .01
                        report['click_intervals_seconds'] = intervals.tolist()
                        check(len(intervals) >= 5 and np.all(np.abs(intervals - .6) < .06),
                              'Captured audio does not match the 100 BPM demo')
                        window.child_window(title='Pause', control_type='Button').invoke()
                        window.child_window(title='Paused', control_type='Text').wait('visible', timeout=10)
                        time.sleep(.3)
                        capture('paused', 1)
                        check(report['paused']['rms'] < report[f'{name}-playing']['rms'] * .05,
                              'Pause did not silence the captured output')
                        window.capture_as_image().save(evidence / 'paused.png')
                        texts = [item.window_text() for item in window.descendants(control_type='Text')]
                        report['playback_labels'] = texts
                        check(any(t.startswith('MIDI: ') and 'No output' not in t for t in texts),
                              'No MIDI output was opened during playback')
                    window.child_window(title='Stop', control_type='Button').invoke()
                    play.wait('visible', timeout=10)
                    window.capture_as_image().save(evidence / f'{name}-returned-editor.png')
                    window.close()
                    check(proc.wait(timeout=15) == 0, 'Frozen GUI exited with an error')
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                        proc.wait(timeout=10)

        exported = base / 'exported-show.zip'
        export = subprocess.run([str(exe), str(package / 'demo' / 'setlist.yaml'),
                                 '--export-bundle', str(exported)], cwd=base, env=env,
                                capture_output=True, text=True, timeout=45)
        (evidence / 'export.txt').write_text(export.stdout + export.stderr, encoding='utf-8')
        check(export.returncode == 0 and exported.is_file(), 'Frozen bundle export failed')
        imported = base / 'imported show'
        with zipfile.ZipFile(exported) as bundle:
            bundle.extractall(imported)
        run_set(imported / 'setlist.yaml', 'demo', demo=True)
        codec = package / 'demo' / 'codec-test.yaml'
        codec.write_text('title: FFmpeg smoke\naudio_root: .\nsongs:\n' +
                         '  - name: M4A decoder\n    file: codec-test.m4a\n    bpm: 120\n' * 10)
        run_set(codec, 'm4a')
    report['passed'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    report = {'passed': False}
    try:
        verify(args.archive.resolve(), args.evidence.resolve(), report)
    except Exception:
        report['error'] = traceback.format_exc()
        raise
    finally:
        (args.evidence / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('ShowSync frozen Windows verification passed', flush=True)


if __name__ == '__main__':
    main()
