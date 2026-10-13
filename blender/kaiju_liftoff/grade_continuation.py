"""Grade sparse T316 previews or the 48 new final frames with the pinned T309 chain."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from apply_grade_sequence import (BLENDER_411, PROFILE, PROFILE_SHA256, PYTHON_DEPS,
                                  run, stage_inverse, stage_trim)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    assert a.input.resolve() != a.output.resolve()
    assert not a.output.exists(), 'Use a fresh graded output directory'
    assert hashlib.sha256(PROFILE.read_bytes()).hexdigest() == PROFILE_SHA256
    sources = sorted(a.input.glob('frame_*.png'))
    assert sources
    work = a.output.parent / (a.output.name + '_work')
    assert not work.exists(), 'Use a fresh intermediate directory'
    exr, graded = work/'exr', work/'graded'
    numbers = [int(path.stem.split('_')[1]) for path in sources]
    reports = []
    for n in numbers:
        reports.append(stage_inverse(a.input, exr, n, n, a.original/PYTHON_DEPS))
    output = run([BLENDER_411, '-b', '--factory-startup', '--python-exit-code', '1',
                  '--python', Path(__file__).with_name('apply_grade_sequence.py'), '--',
                  '--blender-batch', '--exr-dir', exr, '--out-dir', graded, '--profile', PROFILE])
    for n in numbers:
        stage_trim(graded, a.output, n, n)
    report = dict(frames=numbers, profile_sha256=PROFILE_SHA256, inverse=reports,
                  compositor=json.loads(output.split('GRADE_BATCH_DONE', 1)[1].strip().splitlines()[0]))
    (a.output/'grade_report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
