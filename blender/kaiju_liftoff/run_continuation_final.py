"""Detached, resumable T316 final render; invoke only after preview approval.

Copy this and sibling scripts into the output directory's job/ before launching.
An explicit approval note is recorded in job_status.json with the candidate hash.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import traceback


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--approval-note', required=True)
    p.add_argument('--blender', default='/home/devin/bin/blender-5.1.2-linux-x64/blender')
    a = p.parse_args()
    assert a.approval_note.strip()
    d = a.directory.resolve()
    scripts = Path(__file__).resolve().parent
    lock = (d/'final_job.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    candidate = d/'kaiju_liftoff_continued.blend'
    last = json.loads(candidate.with_suffix('.json').read_text())['new_frames'][1]
    state = dict(approval=a.approval_note, candidate_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest())

    def update(phase, **extra):
        state.update(phase=phase, updated=datetime.now(timezone.utc).isoformat(), **extra)
        (d/'job_status.json').write_text(json.dumps(state, indent=2))
        print('JOB', phase, flush=True)

    def run(args):
        subprocess.run([str(x) for x in args], check=True)

    try:
        assert json.loads((d/'preview_verification.json').read_text())['status'] == 'PASS'
        update('RENDERING')
        run([a.blender, '-b', '--python-exit-code', '1', '--python', scripts/'render_final.py', '--',
             '--source', a.source, '--candidate', candidate, '--output', d/'final_exr',
             '--start', 218, '--end', last, '--native-exr'])
        update('GRADING')
        if not (d/'final_graded'/'grade_report.json').exists():
            run([sys.executable, scripts/'grade_continuation.py', '--original', a.original,
                 '--input', d/'final_exr', '--output', d/'final_graded', '--native-exr', '--trim-code-values', '3'])
        update('PACKAGING')
        if not (d/'final_verification.json').exists():
            run([sys.executable, scripts/'package_continuation.py', '--original', a.original,
                 '--directory', d, '--reference', a.reference])
        audit = json.loads((d/'final_verification.json').read_text())
        assert audit['status'] == 'PASS'
        assert hashlib.sha256(candidate.read_bytes()).hexdigest() == state['candidate_sha256']
        update('COMPLETE', output=str(d/'kaiju_liftoff_final_graded_continued.mp4'))
    except Exception as error:
        update('FAILED', error=str(error))
        traceback.print_exc()
        raise


if __name__ == '__main__':
    main()
