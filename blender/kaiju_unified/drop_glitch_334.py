"""Remove only scene f164 from hash-verified T333 graded sources; retain v1."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kaiju_dive'))
from final_pipeline import digest, package, pixel_check, probe_video

MAPPING = [f for f in range(1, 193) if f != 164]


def rgb(path):
    with Image.open(path) as im:
        return np.array(im.convert('RGB'))


def check_splice(video, sources):
    raw = subprocess.check_output([
        'ffmpeg', '-v', 'error', '-xerror', '-i', str(video),
        '-vf', 'select=eq(n\\,162)+eq(n\\,163)', '-fps_mode', 'passthrough',
        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
    pair = np.frombuffer(raw, np.uint8).reshape(2, 1080, 1920, 3)
    errors = [pixel_check(pair[i], rgb(sources / f'frame_{f:04}.png'))
              for i, f in enumerate((163, 165))]
    return pair, errors


def main(root):
    root = root.resolve()
    baseline = json.loads((root / 'final_verification.json').read_text())
    v1 = root / 'unified_flight_impact_final.mp4'
    assert digest(v1) == baseline['sha256']
    scene_sha = digest(root / 'unified.blend')
    sources = root / 'final_frames'
    for row in baseline['frames']:
        assert digest(sources / f"frame_{row['frame']:04}.png") == row['graded_sha256']
    assert len(baseline['frames']) == 192
    stage = root / 'v2_qa'
    frames = stage / 'final_frames'
    frames.mkdir(parents=True, exist_ok=True)
    for output, source in enumerate(MAPPING, 1):
        link = frames / f'frame_{output:04}.png'
        target = sources / f'frame_{source:04}.png'
        if link.is_symlink():
            assert link.resolve() == target
        else:
            link.symlink_to(target)
    name = 'unified_flight_impact_final_v2.mp4'
    report = package(stage, 191, name, beats=[162, 163, 164, 165, 191])
    video = root / name
    (stage / name).replace(video)
    report['video'] = str(video)
    for row, source in zip(report['frames'], MAPPING):
        row['scene_frame'] = source
        assert row['graded_sha256'] == baseline['frames'][source - 1]['graded_sha256']
    pair, errors = check_splice(video, sources)
    source_pair = [rgb(sources / f'frame_{f:04}.png') for f in (163, 165)]
    source_delta = source_pair[1].astype(float) - source_pair[0].astype(float)
    decoded_delta = pair[1].astype(float) - pair[0].astype(float)
    delta_error = float(np.abs(decoded_delta - source_delta).mean())
    assert delta_error < 3, f'Splice pixel-difference mismatch: {delta_error}'
    sheet = Image.new('RGB', (1920, 540))
    for i in range(2):
        sheet.paste(Image.fromarray(pair[i]).resize((960, 540)), (960*i, 0))
    sheet.save(root / 'v2_splice.jpg', quality=95)
    negatives = {}
    for name, check in [('v1_frame_count', lambda: probe_video(v1, 191)),
                        ('v1_uncut_splice', lambda: check_splice(v1, sources))]:
        try:
            check()
        except AssertionError as error:
            expected = 'Decoded frame count' if name == 'v1_frame_count' else 'Encoded pixels differ'
            assert str(error).startswith(expected), str(error)
            negatives[name] = str(error)
        else:
            raise AssertionError('Negative control passed: ' + name)
    assert digest(v1) == baseline['sha256']
    assert digest(root / 'unified.blend') == scene_sha
    report.update(removed_scene_frame=164, removed_v1_index=163,
                  source_mapping=MAPPING, original_sha256=baseline['sha256'],
                  scene_sha256=scene_sha, negative_controls=negatives,
                  splice={'scene_frames': [163, 165], 'output_frames': [163, 164],
                          'encoded_mae': errors, 'delta_mae': delta_error,
                          'source_pair_mae': float(np.abs(source_delta).mean()),
                          'decoded_pair_mae': float(np.abs(decoded_delta).mean())},
                  full_decode='PASS', all_192_graded_hashes='PASS')
    (root / 'final_v2_verification.json').write_text(json.dumps(report, indent=2) + '\n')
    (root / 'SHA256SUMS_v2').write_text(report['sha256'] + '  ' + video.name + '\n')
    (root / 'review_v2.html').write_text('''<!doctype html><meta charset="utf-8">
<title>Unified flight and impact — final v2</title>
<style>body{background:#17191c;color:#eee;font:18px system-ui;max-width:1400px;margin:30px auto;padding:20px}img,video{width:100%}a{color:#9bdcff}</style>
<h1>Unified flight and impact — final v2</h1>
<p>Removed only scene frame 164, where a large debris rock covered the face. Scene frame 163 now cuts directly to 165. All other graded frames retained in order.</p>
<video controls loop src="unified_flight_impact_final_v2.mp4"></video>
<p>1920 × 1080 · 24 fps · 191 frames · 7.958 seconds · H.264 CRF16, slow · original kaiju_1960s grade.</p>
<p><a href="unified_flight_impact_final_v2.mp4">Download v2</a> · <a href="SHA256SUMS_v2">SHA256</a> · <a href="final_v2_verification.json">Verification</a> · <a href="review.html">Original v1 (preserved)</a></p>
<p>Decoded splice: scene 163 (left), scene 165 (right).</p><img src="v2_splice.jpg">
''')
    print(json.dumps({k: report[k] for k in ('video', 'sha256', 'probe', 'splice', 'negative_controls')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    main(parser.parse_args().directory)
