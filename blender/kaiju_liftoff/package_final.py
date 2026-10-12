"""Encode 216 native 1080p24 frames and audit the 652-frame teaser continuation."""
import argparse
import hashlib
import json
from pathlib import Path

from package_preview import probe, run


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    a = p.parse_args()
    d = a.directory.resolve()
    frames = d/'cinematic_final_frames'
    expected = [frames/f'frame_{i:04}.png' for i in range(2, 218)]
    missing = [str(path) for path in expected if not path.is_file()]
    assert not missing, f'Missing final frames: {missing}'
    for path in expected:
        # PNG IHDR stores width/height in network order. Fail before encoding
        # if a resumed sequence accidentally contains a cheap draft frame.
        with path.open('rb') as handle:
            header = handle.read(24)
        assert header[:8] == b'\x89PNG\r\n\x1a\n', f'Invalid PNG: {path}'
        size = [int.from_bytes(header[i:i+4], 'big') for i in (16, 20)]
        assert size == [1920, 1080], f'Wrong final dimensions: {path}: {size}'
    reference = probe(a.reference)
    assert reference['r_frame_rate'] == '24/1' and int(reference['nb_read_frames']) == 436, reference
    preview = d/'kaiju_liftoff_final.mp4'
    joined = d/'teaser2_with_liftoff_final.mp4'
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-framerate', '24',
         '-start_number', '2', '-i', str(frames/'frame_%04d.png'), '-frames:v', '216',
         '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-pix_fmt', 'yuv420p',
         '-movflags', '+faststart', str(preview)])
    filters = (
        '[0:v]scale=1920:1080:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[v0];'
        '[1:v]setsar=1,setpts=PTS-STARTPTS[v1];'
        '[v0][v1]concat=n=2:v=1:a=0,fps=24:eof_action=pass,'
        'tpad=stop_mode=clone:stop=1,trim=end_frame=652[v];'
        '[0:a]atrim=duration=18.166666667,asetpts=PTS-STARTPTS,'
        'afade=t=out:st=17.916666667:d=0.25,apad=whole_dur=27.166666667[a]')
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(a.reference),
         '-i', str(preview), '-filter_complex', filters, '-map', '[v]', '-map', '[a]',
         '-fps_mode', 'cfr', '-c:v', 'libx264', '-crf', '16', '-preset', 'slow',
         '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
         '-movflags', '+faststart', str(joined)])
    audit = {}
    for path, count in [(preview, 216), (joined, 652)]:
        info = probe(path)
        assert (info['width'], info['height']) == (1920, 1080), (path, info)
        assert int(info['nb_read_frames']) == count and info['r_frame_rate'] == '24/1', (path, info)
        assert abs(float(info['duration']) - count/24) < .001, (path, info)
        run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'])
        info['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        audit[path.name] = info
    audit.update(status='PASS', extension_scene_frames=[2, 217],
                 source_frames=436, extension_frames=216, joined_frames=652,
                 audio='Original teaser audio fades over final 0.25 s; extension silent.',
                 render_settings=json.loads((frames/'render_settings.json').read_text()))
    (d/'final_media_verification.json').write_text(json.dumps(audit, indent=2))
    print(json.dumps(audit, indent=2))


if __name__ == '__main__':
    main()
