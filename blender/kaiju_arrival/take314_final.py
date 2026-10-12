"""Render the approved trimmed T314 shot, with resumable EXRs and pinned grade."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

BLENDER = '/home/devin/bin/blender-5.1.2-linux-x64/blender'
GRADE = '/home/devin/bin/blender-4.1.1-linux-x64/blender'
PYTHON = '/home/devin/src/2026/videdit/venv/bin/python'
SCRIPTS = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, logfile):
    with logfile.open('w') as log:
        subprocess.run([str(arg) for arg in command], stdout=log, stderr=subprocess.STDOUT, check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--move', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--hold-only', action='store_true', help='Render approved settled frames 63–108, deferring packaging')
    a = p.parse_args()
    assert 1 <= a.workers <= 2
    root, move = a.output.resolve(), a.move.resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = move / 'arrival_move.blend'
    verification = json.loads((move / 'move_verification.json').read_text())
    assert digest(source) == verification['blend_sha256']
    assert digest(Path(verification['source'])) == verification['source_sha256']
    scene = root / 'beetle_arrival_final.blend'
    plan = {'source': str(source), 'scene_sha256': digest(source), 'source_frames': [27, 108],
            'samples': 64, 'resolution_percent': 100, 'fps': 24, 'first_visible_frame': 31,
            'empty_lead_frames': 4, 'approval': 'Devin approved endpoint, check frames, trim and final render via pm-midi-1'}
    planpath = root / 'render_plan.json'
    if planpath.exists():
        assert json.loads(planpath.read_text()) == plan, 'Cannot resume a changed render plan'
        assert digest(scene) == plan['scene_sha256']
    else:
        assert not scene.exists(), 'Use fresh output directory'
        shutil.copy2(source, scene)
        planpath.write_text(json.dumps(plan, indent=2) + '\n')
    exrs = root / 'final_exr'
    exrs.mkdir(exist_ok=True)
    # Reuse native renders for exactly identical poses/state at these frame numbers.
    reuse = {52: move / 'check_exr/frame_0052.exr',
             86: Path(verification['source']).parent / 'hold_exr/frame_0086.exr'}
    for frame, existing in reuse.items():
        dest = exrs / f'frame_{frame:04}.exr'
        if not dest.exists():
            shutil.copy2(existing, dest)
        assert digest(dest) == digest(existing)
    expected = {f'frame_{frame:04}.exr' for frame in range(27, 109)}
    assert {path.name for path in exrs.glob('frame_*.exr')} <= expected
    pending = [frame for frame in range(27, 109) if not (exrs / f'frame_{frame:04}.exr').exists()]
    if a.hold_only:
        pending = [frame for frame in pending if frame >= 63]

    def render(worker):
        frames = pending[worker::a.workers]
        if not frames:
            return
        run([BLENDER, '-t', '6', '-b', scene, '--python-exit-code', '1', '--python', SCRIPTS / 'render.py',
             '--', '--output', exrs, '--frames', ','.join(map(str, frames)), '--samples', '64',
             '--percent', '100', '--device', '3060'], root / f'render_worker_{worker}.log')
        print('RENDER_WORKER_COMPLETE', worker, len(frames), flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for result in pool.map(render, range(a.workers)):
            pass
    if a.hold_only:
        print('T314_HOLD_RENDERED', flush=True)
        return
    assert {path.name for path in exrs.glob('frame_*.exr')} == expected
    assert digest(source) == digest(scene) == plan['scene_sha256']
    (root / 'native_frame_hashes.json').write_text(json.dumps({path.name: digest(path) for path in sorted(exrs.glob('frame_*.exr'))}, indent=2) + '\n')
    run([GRADE, '-t', '6', '-b', '--python-exit-code', '1', '--python', SCRIPTS / 'grade.py', '--',
         '--input', exrs, '--output', root / 'final_frames'], root / 'grade.log')
    grade = json.loads((root / 'final_frames/grade.json').read_text())
    assert grade['frames'] == 82
    run([PYTHON, SCRIPTS / 'package.py', '--directory', root, '--final', '--start-frame', '27',
         '--end-frame', '108', '--source-directory', '/home/devin/src/2026/videdit/work/kaiju_beetle_307'], root / 'package.log')
    assert digest(source) == digest(scene) == plan['scene_sha256']
    print('T314_FINAL_ENCODED', root / 'beetle_arrival_final.mp4', flush=True)


if __name__ == '__main__':
    main()
