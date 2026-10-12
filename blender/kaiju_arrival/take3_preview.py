"""Render/grade draft T313 takes in detached workers; never render a final.

Each take uses a single render subprocess per sequence for persistent scene
data. Run this orchestrator detached so a terminal timeout cannot kill a batch.
Two takes can render concurrently; these scenes fit together on the 12GB 3060.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess


BLENDER = '/home/devin/bin/blender-5.1.2-linux-x64/blender'
GRADE = '/home/devin/bin/blender-4.1.1-linux-x64/blender'
SCRIPTS = Path(__file__).resolve().parent
BEATS = [1, 40, 52, 58, 63, 86]


def run(command, logfile):
    with logfile.open('w') as log:
        subprocess.run([str(arg) for arg in command], stdout=log,
                       stderr=subprocess.STDOUT, check=True, timeout=7200)


def render_take(root, take):
    directory = root / take
    scene = directory / f'take_{take}.blend'
    source_hash = hashlib.sha256(scene.read_bytes()).hexdigest()
    for name, frames, samples, percent in [
            ('preview', BEATS, 16, 50), ('clip', range(40, 87), 4, 25)]:
        output = directory / f'{name}_exr'
        run([BLENDER, '-t', '8', '-b', scene, '--python-exit-code', '1',
             '--python-expr', 'import bpy; bpy.context.scene.cycles.denoising_use_gpu=True',
             '--python', SCRIPTS / 'render.py', '--', '--output', output,
             '--frames', ','.join(map(str, frames)), '--samples', samples,
             '--percent', percent, '--device', '3060'], directory / f'{name}_render.log')
        graded = directory / ('stills' if name == 'preview' else 'clip_frames')
        run([GRADE, '-t', '8', '-b', '--python-exit-code', '1',
             '--python', SCRIPTS / 'grade.py', '--', '--input', output,
             '--output', graded], directory / f'{name}_grade.log')
        print(f'{take}: {name} rendered and graded', flush=True)
    assert hashlib.sha256(scene.read_bytes()).hexdigest() == source_hash, 'Scene changed during render'
    video = directory / f'take_{take}_frames_40-86.mp4'
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-framerate', '24',
         '-start_number', '40', '-i', directory / 'clip_frames/frame_%04d.png',
         '-frames:v', '47', '-c:v', 'libx264', '-crf', '18', '-preset', 'slow',
         '-pix_fmt', 'yuv420p', '-movflags', '+faststart', video], directory / 'encode.log')
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,r_frame_rate,nb_read_frames,duration',
        '-of', 'json', str(video)], text=True))['streams'][0]
    assert (probe['width'], probe['height']) == (480, 270), probe
    assert probe['r_frame_rate'] == '24/1' and int(probe['nb_read_frames']) == 47, probe
    assert abs(float(probe['duration']) - 47 / 24) < .001, probe
    run(['ffmpeg', '-v', 'error', '-i', video, '-f', 'null', '-'], directory / 'decode.log')
    (directory / 'media_verification.json').write_text(json.dumps({
        'status': 'PASS', 'scene_sha256': source_hash,
        'video_sha256': hashlib.sha256(video.read_bytes()).hexdigest(), 'video': probe,
        'stills': {'frames': BEATS, 'samples': 16, 'resolution': [960, 540]},
        'clip': {'source_frames': [40, 86], 'samples': 4, 'resolution': [480, 270],
                 'all_47_frames_rendered': True},
        'stage': 'Draft preview only; final-quality render awaits Devin pick',
    }, indent=2))
    print(f'{take}: preview complete and decoded', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--takes', nargs='+', choices=['A', 'B'], default=['A', 'B'])
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(render_take, args.directory.resolve(), take) for take in args.takes]
        for future in futures:
            future.result()


if __name__ == '__main__':
    main()
