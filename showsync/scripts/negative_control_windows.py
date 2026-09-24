r"""Silent-audio negative control for verify_windows.py.

Copies the release ZIP, replaces only ShowSync/demo/demo-100.wav with silent
samples of identical format and duration, and re-runs the standard verifier
on the mutated copy. The verifier must fail on the assertion
'Windows output capture is silent' — not on an import, collection or setup
error — proving the loopback capture would have caught a silent build.
The original ZIP is hashed before and after and must be unchanged.

  venv\Scripts\python.exe scripts\negative_control_windows.py ^
      dist\ShowSync_Windows.zip dist\windows-negative-control
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import wave
import zipfile

# Compress-Archive writes backslash-separated entry names.
TARGET = 'ShowSync\\demo\\demo-100.wav'
EXPECTED = 'Windows output capture is silent'


def silence_like(payload):
    with wave.open(Path(payload).open('rb')) as source:
        params = source.getparams()
    silent = Path(payload).with_suffix('.silent.wav')
    with wave.open(silent.open('wb')) as out:
        out.setparams(params)
        out.writeframes(b'\0' * params.nframes * params.nchannels * params.sampwidth)
    return silent.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    archive = args.archive.resolve()
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    before = hashlib.sha256(archive.read_bytes()).hexdigest()
    verifier = Path(__file__).with_name('verify_windows.py')
    with tempfile.TemporaryDirectory(prefix='ShowSync negative ') as temp:
        base = Path(temp)
        extracted = base / 'demo-100.wav'
        with zipfile.ZipFile(archive) as source:
            extracted.write_bytes(source.read(TARGET))
            entries = [i for i in source.infolist() if i.filename != TARGET]
            mutated = base / 'ShowSync_Windows_silent.zip'
            with zipfile.ZipFile(mutated, 'w', zipfile.ZIP_DEFLATED) as out:
                for info in entries:
                    out.writestr(info, source.read(info))
                out.writestr(TARGET, silence_like(extracted))
        result = subprocess.run([sys.executable, str(verifier), str(mutated),
                                 str(evidence)], capture_output=True, text=True)
    report = json.loads((evidence / 'report.json').read_text(encoding='utf-8'))
    after = hashlib.sha256(archive.read_bytes()).hexdigest()
    control = {'expected_failure': EXPECTED,
               'source_zip_sha256': before,
               'original_unchanged': before == after,
               'verifier_exit_code': result.returncode,
               'failed_on_expected_assertion':
                   result.returncode != 0 and EXPECTED in report.get('error', ''),
               'mutation': 'Replaced only demo-100.wav samples with silence, '
                           'preserving its duration and format.'}
    (evidence / 'negative-control.json').write_text(json.dumps(control, indent=2),
                                                    encoding='utf-8')
    assert control['original_unchanged'], 'Original ZIP changed during the control'
    assert result.returncode != 0, 'Verifier PASSED a silent build; it proves nothing'
    error = report.get('error', '')
    assert EXPECTED in error and 'AssertionError' in error, (
        f'Verifier failed for the wrong reason:\n{error}\n{result.stdout}{result.stderr}')
    print('Negative control behaved as designed: '
          f'verifier failed on {EXPECTED!r} and the original ZIP is unchanged')


if __name__ == '__main__':
    main()
