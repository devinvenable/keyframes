"""Approved T320 native render, pinned grade, encode and per-frame decode QA.

Run in a persistent terminal session. --prepare-only records the approved plan
before rendering; subsequent runs resume that exact scene and plan.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image, ImageDraw

BLENDER = '/home/devin/bin/blender-5.1.2-linux-x64/blender'
GRADE = '/home/devin/bin/blender-4.1.1-linux-x64/blender'
SCRIPTS = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT, check=True)


def probe_video(path, count):
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,r_frame_rate,nb_read_frames,duration,pix_fmt,codec_name',
        '-of', 'json', str(path)]))['streams'][0]
    assert int(probe['nb_read_frames']) == count, 'Decoded frame count differs from approved shot'
    assert (probe['width'], probe['height']) == (1920, 1080), probe
    assert probe['r_frame_rate'] == '24/1' and probe['codec_name'] == 'h264', probe
    assert probe['pix_fmt'] == 'yuv420p', probe
    assert abs(float(probe['duration'])-count/24) < .001, probe
    return probe


def pixel_check(decoded, reference):
    assert decoded.std() > 12 and 15 < decoded.mean() < 210, 'Blank or invalid decoded picture'
    mae = float(np.abs(decoded.astype(np.float32)-reference.astype(np.float32)).mean())
    assert mae < 6, f'Encoded pixels differ from graded source: {mae}'
    return mae


def package(root, count):
    frames = root/'final_frames'
    paths = [frames/f'frame_{f:04}.png' for f in range(1, count+1)]
    assert {p.name for p in frames.glob('frame_*.png')} == {p.name for p in paths}
    video = root/'dive_swept_final.mp4'
    run(['ffmpeg', '-v', 'error', '-y', '-framerate', '24', '-start_number', '1',
         '-i', frames/'frame_%04d.png', '-frames:v', count, '-c:v', 'libx264',
         '-crf', '16', '-preset', 'slow', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', video], root/'encode.log')
    probe = probe_video(video, count)
    report = {'video': str(video), 'sha256': digest(video), 'probe': probe, 'frames': []}
    beats = [1, 16, 20, 24, 28, 32, 40, 48, 64, 80, 96, 101, count]
    decoded_dir = root/'decoded_beats'; decoded_dir.mkdir(exist_ok=True)
    sheet = Image.new('RGB', (1440, 300*((len(beats)+2)//3)), '#17191c')
    draw = ImageDraw.Draw(sheet)
    with (root/'decode.log').open('w') as err:
        proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-xerror', '-i', str(video),
                                 '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE, stderr=err)
        try:
            for f, path in enumerate(paths, 1):
                raw = proc.stdout.read(1920*1080*3)
                assert len(raw) == 1920*1080*3, f'Incomplete decoded frame {f}'
                decoded = np.frombuffer(raw, np.uint8).reshape(1080, 1920, 3)
                with Image.open(path) as im:
                    im.load(); assert im.size == (1920, 1080), path
                    reference = np.array(im.convert('RGB'))
                mae = pixel_check(decoded, reference)
                report['frames'].append({'frame': f, 'graded_sha256': digest(path),
                                         'decoded_rgb_sha256': hashlib.sha256(raw).hexdigest(),
                                         'encoded_mae': mae, 'mean': float(decoded.mean()), 'std': float(decoded.std())})
                if f in beats:
                    image = Image.fromarray(decoded); image.save(decoded_dir/f'frame_{f:04}.png')
                    i = beats.index(f); sheet.paste(image.resize((480, 270)), (480*(i%3), 300*(i//3)+30))
                    draw.text((480*(i%3)+12, 300*(i//3)+8), f'Frame {f}', fill='white')
            assert proc.stdout.read(1) == b'', 'Unexpected extra decoded frame'
            assert proc.wait() == 0, 'FFmpeg decode failed'
        finally:
            proc.stdout.close()
            if proc.poll() is None: proc.kill(); proc.wait()
    sheet.save(root/'final_decoded_contact.jpg', quality=95)
    report['status'] = 'PASS'
    report['max_encoded_mae'] = max(f['encoded_mae'] for f in report['frames'])
    return report


def main():
    p = argparse.ArgumentParser(); p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--approval-note', required=True); p.add_argument('--prepare-only', action='store_true')
    a = p.parse_args(); root = a.directory.resolve(); scene = root/'dive_contact.blend'
    manifest = json.loads((root/'scene_manifest.json').read_text())
    count = manifest['continuation']['end_frame']
    assert digest(scene) == manifest['scene_sha256']
    plan = {'scene': str(scene), 'scene_sha256': digest(scene), 'frames': [1, count], 'fps': 24,
            'resolution': [1920, 1080], 'samples': 64, 'device': '3060', 'crf': 16,
            'render_blender': BLENDER, 'grade_blender': GRADE, 'approval': a.approval_note}
    plan_path = root/'final_render_plan.json'
    if plan_path.exists(): assert json.loads(plan_path.read_text()) == plan, 'Changed render plan'
    else: plan_path.write_text(json.dumps(plan, indent=2)+'\n')
    if a.prepare_only: return
    run([BLENDER, '-t', '6', '-b', scene, '--python-exit-code', '1', '--python',
         SCRIPTS/'verify_final_scene.py', '--', '--output', root/'scene_qa.json', '--negative-checks'], root/'scene_qa.log')
    exrs = root/'final_exr'; exrs.mkdir(exist_ok=True)
    expected = {f'frame_{f:04}.exr' for f in range(1, count+1)}
    assert {p.name for p in exrs.glob('frame_*.exr')} <= expected
    pending = [f for f in range(1, count+1) if not (exrs/f'frame_{f:04}.exr').exists()]
    if pending:
        run([BLENDER, '-t', '6', '-b', scene, '--python-exit-code', '1', '--python',
             SCRIPTS.parent/'kaiju_arrival/render.py', '--', '--output', exrs,
             '--frames', ','.join(map(str, pending)), '--samples', '64', '--percent', '100', '--device', '3060'], root/'resume_render.log')
    assert {p.name for p in exrs.glob('frame_*.exr')} == expected
    hashes = {p.name: digest(p) for p in sorted(exrs.glob('frame_*.exr'))}
    (root/'native_frame_hashes.json').write_text(json.dumps(hashes, indent=2)+'\n')
    print('NATIVE_RENDER_COMPLETE', flush=True)
    run([GRADE, '-t', '6', '-b', '--python-exit-code', '1', '--python',
         SCRIPTS.parent/'kaiju_arrival/grade.py', '--', '--input', exrs, '--output', root/'final_frames'], root/'final_grade.log')
    grade = json.loads((root/'final_frames/grade.json').read_text())
    assert grade['frames'] == count and grade['blender'] == '4.1.1'
    print('GRADE_COMPLETE', flush=True)
    report = package(root, count)
    report.update(plan=plan, grade=grade, native_frame_sha256=hashes)
    assert digest(scene) == plan['scene_sha256']
    assert digest(Path(manifest['source'])) == manifest['source_sha256']
    (root/'final_verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print('FINAL_VERIFIED', report['video'], flush=True)


if __name__ == '__main__': main()
