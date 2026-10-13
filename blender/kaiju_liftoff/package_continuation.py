"""Package T316 from untouched approved PNGs plus exactly 48 new graded frames."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from apply_grade_sequence import probe, run, yavg
from verify_continuation_pixels import check


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    a = p.parse_args()
    d = a.directory.resolve()
    original = a.original/'cinematic_final_frames_graded'
    new = d/'final_graded'
    report = check(original, new)
    sequence = d/'combined_graded_frames'
    assert not sequence.exists(), 'Use fresh packaging paths'
    sequence.mkdir()
    hashes = {}
    for frame in range(2, 266):
        source = (original if frame <= 217 else new)/f'frame_{frame:04}.png'
        target = sequence/source.name
        shutil.copy2(source, target)
        assert sha(source) == sha(target)
        if frame <= 217:
            hashes[source.name] = sha(source)
    extension = d/'kaiju_liftoff_final_graded_continued.mp4'
    joined = d/'teaser2_with_liftoff_final_graded_continued.mp4'
    run(['ffmpeg', '-v', 'error', '-n', '-framerate', '24', '-start_number', '2',
         '-i', sequence/'frame_%04d.png', '-frames:v', '264', '-c:v', 'libx264',
         '-preset', 'slow', '-crf', '16', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', extension])
    reference_info = probe(a.reference)
    assert int(reference_info['nb_read_frames']) == 436 and reference_info['r_frame_rate'] == '24/1'
    filters = (
        '[0:v]scale=1920:1080:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[v0];'
        '[1:v]setsar=1,setpts=PTS-STARTPTS[v1];'
        '[v0][v1]concat=n=2:v=1:a=0,fps=24:eof_action=pass,'
        'tpad=stop_mode=clone:stop=1,trim=end_frame=700[v];'
        '[0:a]atrim=duration=18.166666667,asetpts=PTS-STARTPTS,'
        'afade=t=out:st=17.916666667:d=0.25,apad=whole_dur=29.166666667[a]')
    run(['ffmpeg', '-v', 'error', '-n', '-i', a.reference, '-i', extension,
         '-filter_complex', filters, '-map', '[v]', '-map', '[a]', '-fps_mode', 'cfr',
         '-c:v', 'libx264', '-crf', '16', '-preset', 'slow', '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', joined])
    report['media'] = {}
    for path, count in [(extension, 264), (joined, 700)]:
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
