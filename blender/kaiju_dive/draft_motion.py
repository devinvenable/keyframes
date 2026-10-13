"""Render both unchanged T317 poses, grade, encode and decode-check draft clips.

Run detached: python draft_motion.py --source ROUND_03 --output ROUND_04.
Existing completed frames are resumable only with the identical render plan.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

BLENDER = '/home/devin/bin/blender-5.1.2-linux-x64/blender'
GRADE = '/home/devin/bin/blender-4.1.1-linux-x64/blender'
SCRIPTS = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def package(root, pose, scene_hash):
    from PIL import Image
    directory = root / pose
    frames = directory / 'frames'
    paths = [frames / f'frame_{f:04}.png' for f in range(1, 97)]
    for path in paths:
        with Image.open(path) as image:
            image.load()
            assert image.size == (960, 540), (path, image.size)
    video = root / f'dive_{pose}_draft.mp4'
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-framerate', '24',
         '-start_number', '1', '-i', frames / 'frame_%04d.png', '-frames:v', '96',
         '-c:v', 'libx264', '-crf', '18', '-preset', 'slow', '-pix_fmt', 'yuv420p',
         '-movflags', '+faststart', video], directory / 'encode.log')
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,r_frame_rate,nb_read_frames,duration',
        '-of', 'json', str(video)]))['streams'][0]
    assert (probe['width'], probe['height']) == (960, 540), probe
    assert probe['r_frame_rate'] == '24/1', probe
    assert int(probe['nb_read_frames']) == 96, probe
    assert abs(float(probe['duration']) - 4.0) < .001, probe
    run(['ffmpeg', '-v', 'error', '-xerror', '-i', video, '-f', 'null', '-'],
        directory / 'decode.log')
    grade = json.loads((frames / 'grade.json').read_text())
    assert grade['frames'] == 96 and grade['blender'] == '4.1.1', grade
    return {'video': str(video), 'probe': probe, 'sha256': digest(video),
            'source_scene_sha256': scene_hash, 'grade': grade,
            'decode': 'PASS', 'frame_sha256': {p.name: digest(p) for p in paths}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    root, source = a.output.resolve(), a.source.resolve()
    assert source != root
    root.mkdir(parents=True, exist_ok=True)
    scenes = {pose: source / pose / f'dive_{pose}.blend' for pose in ('forward', 'swept')}
    plan = {'sources': {pose: {'path': str(scene), 'sha256': digest(scene)}
                        for pose, scene in scenes.items()},
            'frames': [1, 96], 'fps': 24, 'resolution': [960, 540], 'samples': 16,
            'device': '1050', 'render_blender': BLENDER, 'grade_blender': GRADE,
            'review_only': True, 'scene_edits': False}
    plan_path = root / 'render_plan.json'
    if plan_path.exists():
        assert json.loads(plan_path.read_text()) == plan, 'Render plan changed'
    else:
        assert not any(root.iterdir()), 'New plan requires an empty output directory'
        plan_path.write_text(json.dumps(plan, indent=2) + '\n')
    reports = {}
    for pose, scene in scenes.items():
        directory = root / pose
        exrs = directory / 'exr'
        exrs.mkdir(parents=True, exist_ok=True)
        run([BLENDER, '-t', '6', '-b', scene, '--python-exit-code', '1', '--python',
             SCRIPTS / 'verify.py', '--', '--output', directory / 'choreography.json'],
            directory / 'verify.log')
        expected = {f'frame_{f:04}.exr' for f in range(1, 97)}
        assert {p.name for p in exrs.glob('frame_*.exr')} <= expected
        pending = [f for f in range(1, 97) if not (exrs / f'frame_{f:04}.exr').exists()]
        if pending:
            run([BLENDER, '-t', '6', '-b', scene, '--python-exit-code', '1', '--python',
                 SCRIPTS.parent / 'kaiju_arrival/render.py', '--', '--output', exrs,
                 '--frames', ','.join(map(str, pending)), '--samples', '16',
                 '--percent', '50', '--device', '1050'], directory / 'render.log')
        assert {p.name for p in exrs.glob('frame_*.exr')} == expected
        print('RENDER_COMPLETE', pose, flush=True)
        run([GRADE, '-t', '6', '-b', '--python-exit-code', '1', '--python',
             SCRIPTS.parent / 'kaiju_arrival/grade.py', '--', '--input', exrs,
             '--output', directory / 'frames'], directory / 'grade.log')
        assert digest(scene) == plan['sources'][pose]['sha256'], 'Source scene changed'
        reports[pose] = package(root, pose, plan['sources'][pose]['sha256'])
        (directory / 'media_verification.json').write_text(json.dumps(reports[pose], indent=2) + '\n')
        print('DRAFT_COMPLETE', pose, flush=True)
    for pose, scene in scenes.items():
        assert digest(scene) == plan['sources'][pose]['sha256']
    (root / 'media_verification.json').write_text(json.dumps(reports, indent=2) + '\n')
    (root / 'review.html').write_text('''<!doctype html><meta charset="utf-8">
<title>Dive round 4 — motion pose review</title>
<style>body{background:#17191c;color:#eee;font:18px sans-serif;margin:32px}
main{display:flex;gap:24px;flex-wrap:wrap}section{flex:1;min-width:400px}video{width:100%}</style>
<h1>Dive round 4 — draft motion</h1><p>96 frames · 24 fps · 960×540 · pinned kaiju_1960s grade</p>
<main><section><h2>A — Forward arms</h2><video controls loop src="dive_forward_draft.mp4"></video></section>
<section><h2>B — Swept arms</h2><video controls loop src="dive_swept_draft.mp4"></video></section></main>
<p>For review: arm pose A/B, hatches open/closed in flight, endpoint framing, one/both plumes.
These drafts retain the audited deployed hatches, current camera and dominant plume. Final render awaits selection.</p>
''')
    print('BOTH_DRAFTS_VERIFIED', flush=True)


if __name__ == '__main__':
    main()
