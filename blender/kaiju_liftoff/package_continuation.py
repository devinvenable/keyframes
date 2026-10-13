"""Package T316 from untouched approved PNGs plus the approved continuation."""
import argparse
import hashlib
import json
import os
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2
import numpy as np
from pathlib import Path
import shutil

from apply_grade_sequence import probe, run, yavg
from verify_continuation_pixels import check


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_native_frame(image):
    assert image is not None and image.shape == (1080, 1920, 3), 'Invalid native frame dimensions'
    assert image.dtype == np.float32 and np.isfinite(image).all() and image.max() > 1, \
        'Native float32 HDR required; display-encoded PNG is not a native render'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    a = p.parse_args()
    d = a.directory.resolve()
    original = a.original/'cinematic_final_frames_graded'
    new = d/'final_graded'
    manifest = json.loads((d/'kaiju_liftoff_continued.json').read_text())
    last = manifest['new_frames'][1]
    count, joined_count = last-1, last-1+436
    report = check(original, new, manifest)
    settings = json.loads((d/'final_exr/render_settings.json').read_text())
    quality = settings['quality']
    assert quality['samples'] == 4096 and abs(quality['adaptive_threshold']-.01) < 1e-6
    assert quality['volume_step_rate'] == 1 and quality['volume_max_steps'] == 1024
    assert settings['output_format'] == 'scene-linear RGB float32 OpenEXR ZIP'
    assert settings['candidate_sha256'] == sha(d/'kaiju_liftoff_continued.blend')
    assert settings['source_sha256'] == sha(Path(settings['source']))
    report['native_exr'] = {}
    for frame in range(218, last+1):
        path = d/'final_exr'/f'frame_{frame:04}.exr'
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        check_native_frame(image)
        report['native_exr'][path.name] = dict(sha256=sha(path), max_linear=float(image.max()))
    report['render_settings'] = settings
    report['grade'] = json.loads((new/'grade_report.json').read_text())
    assert report['grade']['input_kind'] == 'native linear EXR'
    assert report['grade']['continuity_trim_code_values'] == 3
    assert report['grade']['frames'] == list(range(218, last+1))
    sequence = d/'combined_graded_frames'
    assert not sequence.exists(), 'Use fresh packaging paths'
    sequence.mkdir()
    hashes = {}
    for frame in range(2, last+1):
        source = (original if frame <= 217 else new)/f'frame_{frame:04}.png'
        target = sequence/source.name
        shutil.copy2(source, target)
        assert sha(source) == sha(target)
        if frame <= 217:
            hashes[source.name] = sha(source)
    extension = d/'kaiju_liftoff_final_graded_continued.mp4'
    joined = d/'teaser2_with_liftoff_final_graded_continued.mp4'
    run(['ffmpeg', '-v', 'error', '-n', '-framerate', '24', '-start_number', '2',
         '-i', sequence/'frame_%04d.png', '-frames:v', str(count), '-c:v', 'libx264',
         '-preset', 'slow', '-crf', '16', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', extension])
    reference_info = probe(a.reference)
    assert int(reference_info['nb_read_frames']) == 436 and reference_info['r_frame_rate'] == '24/1'
    filters = (
        '[0:v]scale=1920:1080:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[v0];'
        '[1:v]setsar=1,setpts=PTS-STARTPTS[v1];'
        '[v0][v1]concat=n=2:v=1:a=0,fps=24:eof_action=pass,'
        f'tpad=stop_mode=clone:stop=1,trim=end_frame={joined_count}[v];'
        '[0:a]atrim=duration=18.166666667,asetpts=PTS-STARTPTS,'
        f'afade=t=out:st=17.916666667:d=0.25,apad=whole_dur={joined_count/24:.9f}[a]')
    run(['ffmpeg', '-v', 'error', '-n', '-i', a.reference, '-i', extension,
         '-filter_complex', filters, '-map', '[v]', '-map', '[a]', '-fps_mode', 'cfr',
         '-c:v', 'libx264', '-crf', '16', '-preset', 'slow', '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', joined])
    report['media'] = {}
    for path, count in [(extension, count), (joined, joined_count)]:
        info = probe(path)
        assert (info['width'], info['height']) == (1920, 1080)
        assert info['r_frame_rate'] == '24/1' and int(info['nb_read_frames']) == count
        assert abs(float(info['duration']) - count/24) < .001
        run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'null', '-'])
        info['sha256'] = sha(path)
        report['media'][path.name] = info
    report['continuation_seam_yavg'] = yavg(extension, select='eq(n,215)+eq(n,216)')
    assert abs(report['continuation_seam_yavg'][0]-report['continuation_seam_yavg'][1]) < 2
    assert all(sha(original/name) == digest for name, digest in hashes.items())
    report['approved_frames_reused_identically'] = hashes
    (d/'final_verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
