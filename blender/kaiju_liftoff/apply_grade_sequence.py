"""Apply the recovered kaiju_1960s chain to the 216-frame liftoff extension.

Per-frame chain (T308, PROBE_APR25.md): inverse AgX of the rendered PNG using
the OCIO config of the Blender that wrote it (5.1.2) -> scene-linear EXR ->
recovered kaiju_1960s compositor in Blender 4.1.1 -> forward AgX encode ->
separately labeled reconstruction trim of -3 code values per RGB channel.
New files only; the ungraded finals are never modified.

Run under python3 to orchestrate everything:
    python3 apply_grade_sequence.py --directory /path/to/liftoff_305 \
        --reference /path/to/teaser2.mp4 [--first 2 --last 217] [--skip-encode]

The script re-invokes itself inside Blender 4.1.1 for the compositor stage.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BLENDER_411 = Path('/home/devin/bin/blender-4.1.1-linux-x64/blender')
OCIO_CONFIG = Path('/home/devin/bin/blender-5.1.2-linux-x64/5.1/datafiles/colormanagement/config.ocio')
PROFILE = Path('/home/devin/src/2026/voxel-shorts/scripts/post_process_profiles.py')
PROFILE_SHA256 = 'adf204f3cc23499a93616a5c8abc2ac73e9f106663fcf2b9c2d899f0a6952c38'
PYTHON_DEPS = 'probe_apr25/python_deps'  # PyOpenColorIO 2.6.0, relative to --directory
TRIM_CODE_VALUES = 3  # reconstructed from the T308 seam, not a historical constant
EXPECTED_SEAM_YAVG = 78.0371  # T308 trimmed extension frame 2
TEASER_FRAMES = 436


def run(args, **kw):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, **kw)
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {args[0]}\n{result.stderr[-4000:]}')
    return result.stdout


def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                           '-show_entries', 'stream=width,height,r_frame_rate,nb_read_frames,duration',
                           '-of', 'json', path]))['streams'][0]


def yavg(path, select=None):
    """ffmpeg signalstats YAVG values, the T308 measurement convention."""
    filters = 'signalstats,metadata=print' if select is None else \
        f"select='{select}',signalstats,metadata=print"
    result = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(path), '-vf', filters,
                             '-f', 'null', '-'], capture_output=True, text=True)
    values = [float(m) for m in re.findall(r'YAVG=([0-9.]+)', result.stderr)]
    assert values, f'No YAVG parsed for {path}:\n{result.stderr[-2000:]}'
    return values


def blender_batch(argv):
    """Compositor stage, running inside Blender 4.1.1 (one process, all frames)."""
    import importlib.util
    import bpy
    p = argparse.ArgumentParser()
    p.add_argument('--exr-dir', type=Path, required=True)
    p.add_argument('--out-dir', type=Path, required=True)
    p.add_argument('--profile', type=Path, required=True)
    a = p.parse_args(argv)
    assert bpy.app.version[:2] == (4, 1), f'Requires Blender 4.1, got {bpy.app.version_string}'
    bpy.ops.wm.read_factory_settings(use_empty=True)
    s = bpy.context.scene
    s.render.engine = 'CYCLES'
    s.render.resolution_x, s.render.resolution_y = 1920, 1080
    s.render.resolution_percentage = 100
    s.view_settings.view_transform = 'AgX'
    s.view_settings.look = 'None'
    spec = importlib.util.spec_from_file_location('historical_profile', a.profile)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._apply_kaiju_1960s(s, chromatic_aberration=.018, grain_intensity=.05,
                              vignette_strength=.25, glare_strength=.35)
    tree = s.node_tree
    old = next(n for n in tree.nodes if n.type == 'R_LAYERS')
    destinations = [l.to_socket for l in old.outputs['Image'].links]
    tree.nodes.remove(old)
    node = tree.nodes.new('CompositorNodeImage')
    for socket in destinations:
        tree.links.new(node.outputs['Image'], socket)
    s.render.image_settings.file_format = 'PNG'
    s.render.image_settings.color_mode = 'RGB'
    a.out_dir.mkdir(parents=True, exist_ok=True)
    sources = sorted(a.exr_dir.glob('frame_*.exr'))
    assert sources, f'No EXR frames in {a.exr_dir}'
    start = time.monotonic()
    for i, source in enumerate(sources, 1):
        image = bpy.data.images.load(str(source.resolve()))
        node.image = image
        s.render.filepath = str((a.out_dir / f'{source.stem}.png').resolve())
        bpy.ops.render.render(write_still=True)
        bpy.data.images.remove(image)
        if i % 24 == 0 or i == len(sources):
            print(f'GRADE_BATCH {i}/{len(sources)} {time.monotonic() - start:.1f}s', flush=True)
    print('GRADE_BATCH_DONE', json.dumps(dict(frames=len(sources),
          seconds=time.monotonic() - start, blender_version=bpy.app.version_string)))


def stage_inverse(frames_dir, exr_dir, first, last, deps):
    """Inverse AgX each PNG to a scene-linear EXR; one OCIO processor, reused."""
    sys.path.insert(0, str(deps))
    os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
    import cv2
    import numpy as np
    import PyOpenColorIO as ocio
    config = ocio.Config.CreateFromFile(str(OCIO_CONFIG))
    transform = ocio.DisplayViewTransform(src='Linear Rec.709', display='sRGB', view='AgX',
                                          direction=ocio.TRANSFORM_DIR_INVERSE)
    processor = config.getProcessor(transform).getDefaultCPUProcessor()
    exr_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    worst = 0.0
    for n in range(first, last + 1):
        source = frames_dir / f'frame_{n:04}.png'
        image = cv2.imread(str(source))
        assert image is not None, f'Cannot read {source}'
        assert image.shape[:2] == (1080, 1920), (source, image.shape)
        linear = np.ascontiguousarray(image[:, :, ::-1], dtype=np.float32) / 255
        processor.applyRGB(linear)
        assert cv2.imwrite(str(exr_dir / f'frame_{n:04}.exr'), linear[:, :, ::-1])
        worst = max(worst, float(np.mean(image == 255)))
        if (n - first + 1) % 24 == 0:
            print(f'INVERSE {n - first + 1}/{last - first + 1} {time.monotonic() - start:.1f}s', flush=True)
    return dict(seconds=time.monotonic() - start, ocio_version=ocio.__version__,
                config_sha256=hashlib.sha256(OCIO_CONFIG.read_bytes()).hexdigest(),
                worst_clipped_channel_fraction=worst)


def stage_trim(graded_dir, final_dir, first, last):
    """Saturating -3 per RGB channel in 8-bit code values (lutrgb equivalent)."""
    import cv2
    final_dir.mkdir(parents=True, exist_ok=True)
    for n in range(first, last + 1):
        image = cv2.imread(str(graded_dir / f'frame_{n:04}.png'))
        assert image is not None and image.dtype.name == 'uint8', n
        assert cv2.imwrite(str(final_dir / f'frame_{n:04}.png'),
                           cv2.subtract(image, TRIM_CODE_VALUES))


def encode_and_join(d, final_dir, reference, first, last):
    """T306 packaging (render_job_306/package_final.py) with graded inputs."""
    count = last - first + 1
    for n in range(first, last + 1):
        path = final_dir / f'frame_{n:04}.png'
        with path.open('rb') as handle:
            header = handle.read(24)
        assert header[:8] == b'\x89PNG\r\n\x1a\n', f'Invalid PNG: {path}'
        size = [int.from_bytes(header[i:i + 4], 'big') for i in (16, 20)]
        assert size == [1920, 1080], f'Wrong dimensions: {path}: {size}'
    info = probe(reference)
    assert info['r_frame_rate'] == '24/1' and int(info['nb_read_frames']) == TEASER_FRAMES, info
    extension = d / 'kaiju_liftoff_final_graded.mp4'
    joined = d / 'teaser2_with_liftoff_final_graded.mp4'
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-framerate', '24',
         '-start_number', str(first), '-i', str(final_dir / 'frame_%04d.png'),
         '-frames:v', str(count), '-c:v', 'libx264', '-preset', 'slow', '-crf', '16',
         '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(extension)])
    filters = (
        '[0:v]scale=1920:1080:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[v0];'
        '[1:v]setsar=1,setpts=PTS-STARTPTS[v1];'
        '[v0][v1]concat=n=2:v=1:a=0,fps=24:eof_action=pass,'
        'tpad=stop_mode=clone:stop=1,trim=end_frame=652[v];'
        '[0:a]atrim=duration=18.166666667,asetpts=PTS-STARTPTS,'
        'afade=t=out:st=17.916666667:d=0.25,apad=whole_dur=27.166666667[a]')
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(reference),
         '-i', str(extension), '-filter_complex', filters, '-map', '[v]', '-map', '[a]',
         '-fps_mode', 'cfr', '-c:v', 'libx264', '-crf', '16', '-preset', 'slow',
         '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
         '-movflags', '+faststart', str(joined)])
    audit = {}
    for path, frames in [(extension, count), (joined, TEASER_FRAMES + count)]:
        info = probe(path)
        assert (info['width'], info['height']) == (1920, 1080), (path, info)
        assert int(info['nb_read_frames']) == frames and info['r_frame_rate'] == '24/1', (path, info)
        assert abs(float(info['duration']) - frames / 24) < .001, (path, info)
        run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'])
        info['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        audit[path.name] = info
    seam = yavg(joined, select=f'eq(n,{TEASER_FRAMES - 1})+eq(n,{TEASER_FRAMES})')
    assert len(seam) == 2, seam
    audit['seam_yavg'] = dict(teaser_last=seam[0], extension_first=seam[1],
                              difference=abs(seam[0] - seam[1]))
    return audit


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--first', type=int, default=2)
    p.add_argument('--last', type=int, default=217)
    p.add_argument('--skip-encode', action='store_true')
    p.add_argument('--keep-exr', action='store_true')
    a = p.parse_args()
    d = a.directory.resolve()
    frames_dir = d / 'cinematic_final_frames'
    job = d / 'graded_job_309'
    exr_dir, graded_dir = job / 'exr', job / 'graded'
    final_dir = d / 'cinematic_final_frames_graded'
    assert hashlib.sha256(PROFILE.read_bytes()).hexdigest() == PROFILE_SHA256, \
        'post_process_profiles.py does not match the T308-verified revision'
    report = dict(chain='inverse AgX (5.1.2 OCIO) -> kaiju_1960s compositor (Blender 4.1.1) '
                        f'-> forward AgX -> RGB -{TRIM_CODE_VALUES} trim',
                  frames=[a.first, a.last], profile_sha256=PROFILE_SHA256)

    report['inverse'] = stage_inverse(frames_dir, exr_dir, a.first, a.last, d / PYTHON_DEPS)
    print('STAGE inverse done', flush=True)

    out = run([BLENDER_411, '--background', '--factory-startup', '--python', __file__, '--',
               '--blender-batch', '--exr-dir', exr_dir, '--out-dir', graded_dir,
               '--profile', PROFILE])
    report['compositor'] = json.loads(out.split('GRADE_BATCH_DONE', 1)[1].strip().splitlines()[0])
    print('STAGE compositor done', flush=True)

    stage_trim(graded_dir, final_dir, a.first, a.last)
    print('STAGE trim done', flush=True)

    first_frame = final_dir / f'frame_{a.first:04}.png'
    measured = yavg(first_frame)[0]
    report['first_frame_yavg'] = measured
    if a.first == 2:
        assert abs(measured - EXPECTED_SEAM_YAVG) < 0.2, \
            f'Frame 2 YAVG {measured} deviates from T308 validation {EXPECTED_SEAM_YAVG}'

    if not a.skip_encode:
        report['media'] = encode_and_join(d, final_dir, a.reference.resolve(), a.first, a.last)
    if not a.keep_exr:
        for path in exr_dir.glob('frame_*.exr'):
            path.unlink()
    report['status'] = 'PASS'
    (d / 'graded_media_verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    if '--blender-batch' in sys.argv:
        blender_batch([a for a in sys.argv[sys.argv.index('--') + 1:] if a != '--blender-batch'])
    else:
        main()
