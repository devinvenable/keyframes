"""T333: hash-locked round_07, dual-GPU native render, T320 grade and QA."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import sys

import numpy as np
from PIL import Image

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS.parent/'kaiju_dive'))
from final_pipeline import BLENDER, GRADE, digest, run, package, pixel_check

APPROVED = '2985346dbd6424a220b49640d74637c20e3c3974880676b7dd1e6b27a64f3770'
BEATS = [1, 32, 64, 96, 106, 112, 123, 124, 130, 148, 160, 180, 192]


def main(source, root, rebalance=False):
    source = source.resolve(); root = root.resolve(); root.mkdir(parents=True, exist_ok=True)
    assert digest(source/'unified.blend') == APPROVED, 'Approved round_07 source changed'
    assert json.loads((source/'draft_plan.json').read_text())['scene_sha256'] == APPROVED
    scene = root/'unified.blend'
    if not scene.exists():
        shutil.copy2(source/'unified.blend', scene)
    assert digest(scene) == APPROVED, 'Final scene differs from approved round_07'
    shutil.copy2(source/'manifest.json', root/'manifest.json')
    plan = {'scene': str(scene), 'scene_sha256': APPROVED, 'source': str(source/'unified.blend'),
            'frames': [1, 192], 'fps': 24, 'resolution': [1920, 1080], 'samples': 64,
            'crf': 16, 'devices': {'3060': [1, 144], '1050': [145, 192]},
            'render_blender': BLENDER, 'grade_blender': GRADE,
            'approval': 'Devin approved round_07 on 2026-10-14; T333 / midi:D23'}
    path = root/'final_render_plan.json'
    if path.exists():
        assert json.loads(path.read_text()) == plan, 'Render plan changed'
    else:
        path.write_text(json.dumps(plan, indent=2)+'\n')

    def verify(script, directory=root, blend=scene, extra=()):
        directory.mkdir(parents=True, exist_ok=True)
        run([BLENDER, '-t', '4', '-b', blend, '--python-exit-code', '1', '--python',
             SCRIPTS/script, '--', '--directory', directory, *extra], directory/(script+'.log'))

    run([BLENDER, '-t', '4', '-b', scene, '--python-exit-code', '1', '--python',
         SCRIPTS/'verify_final.py', '--', '--baseline', source/'unified.blend',
         '--output', root/'parity_qa.json'], root/'parity.log')
    print('ROUND07_PARITY_PASS', flush=True)
    verify('verify_331.py', extra=['--baseline', source.parent/'round_06/unified.blend', '--negative-checks'])
    verify('verify.py', extra=['--negative-checks'])
    verify('pixel_contract.py', extra=['--negative-checks'])
    verify('pixel_contract.py', root/'negative_round04', source.parent/'round_04/unified.blend',
           ['--slide-only', '--expect-slide-failure'])
    verify('pixel_contract.py', root/'negative_round05', source.parent/'round_05/unified.blend',
           ['--flanks-only', '--expect-flanks-failure'])
    print('PREFLIGHT_QA_PASS', flush=True)
    exrs = root/'final_exr'; exrs.mkdir(exist_ok=True)
    expected = {f'frame_{f:04}.exr' for f in range(1, 193)}
    assert {p.name for p in exrs.glob('frame_*.exr')} <= expected
    assignments = {device: list(range(first, last+1))
                   for device, (first, last) in plan['devices'].items()}
    allocation_path = root/'render_allocations.json'
    allocations = json.loads(allocation_path.read_text()) if allocation_path.exists() else [
        {'mode': 'initial', 'assignments': assignments}]
    if rebalance:
        pending = [f for f in range(1, 193) if not (exrs/f'frame_{f:04}.exr').exists()]
        split = round(len(pending) * .67)
        assignments = {'3060': pending[:split], '1050': pending[split:]}
        assert sorted(assignments['3060'] + assignments['1050']) == pending
        assert not set(assignments['3060']) & set(assignments['1050'])
        allocations.append({'mode': 'rebalance', 'completed_frames': 192-len(pending),
                            'assignments': assignments})
    allocation_path.write_text(json.dumps(allocations, indent=2)+'\n')

    def worker(device, assigned):
        pending = [f for f in assigned if not (exrs/f'frame_{f:04}.exr').exists()]
        if pending:
            log = root/f'render_{device}.log'
            if log.exists():
                history = root/'render_history'; history.mkdir(exist_ok=True)
                previous = history/f'{len(allocations):03}_{device}.log'
                assert not previous.exists(), 'Render log archive already exists'
                shutil.move(log, previous)
            run([BLENDER, '-t', '4', '-b', scene, '--python-exit-code', '1', '--python',
                 SCRIPTS.parent/'kaiju_arrival/render.py', '--', '--output', exrs,
                 '--frames', ','.join(map(str, pending)), '--samples', '64', '--percent', '100',
                 '--device', device], log)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, device, assigned) for device, assigned in assignments.items()]
        for future in futures:
            future.result()
    assert {p.name for p in exrs.glob('frame_*.exr')} == expected
    hashes = {p.name: digest(p) for p in sorted(exrs.glob('frame_*.exr'))}
    (root/'native_frame_hashes.json').write_text(json.dumps(hashes, indent=2)+'\n')
    print('NATIVE_RENDER_COMPLETE', flush=True)
    run([GRADE, '-t', '6', '-b', '--python-exit-code', '1', '--python',
         SCRIPTS.parent/'kaiju_arrival/grade.py', '--', '--input', exrs,
         '--output', root/'final_frames'], root/'final_grade.log')
    grade = json.loads((root/'final_frames/grade.json').read_text())
    assert grade['frames'] == 192 and grade['blender'] == '4.1.1'
    report = package(root, 192, 'unified_flight_impact_final.mp4', beats=BEATS)
    with Image.open(root/'decoded_beats/frame_0124.png') as im:
        impact = np.array(im.convert('RGB'))
    with Image.open(root/'final_frames/frame_0064.png') as im:
        wrong = np.array(im.convert('RGB'))
    try:
        pixel_check(impact, wrong)
    except AssertionError as error:
        assert str(error).startswith('Encoded pixels differ'), str(error)
        report['negative_wrong_source'] = str(error)
    else:
        raise AssertionError('Wrong source passed encoded pixel check')
    assert digest(scene) == digest(source/'unified.blend') == APPROVED
    report.update(plan=plan, grade=grade, native_frame_sha256=hashes,
                  render_allocations=allocations,
                  qa={name: json.loads((root/name).read_text()) for name in
                      ('parity_qa.json', 'scene_qa.json', 'revision_qa.json', 'pixel_qa.json',
                       'negative_round04/pixel_qa.json', 'negative_round05/pixel_qa.json')})
    (root/'final_verification.json').write_text(json.dumps(report, indent=2)+'\n')
    (root/'SHA256SUMS').write_text(report['sha256']+'  unified_flight_impact_final.mp4\n')
    (root/'review.html').write_text('''<!doctype html><meta charset="utf-8">
<title>Unified flight and impact — final</title>
<style>body{background:#17191c;color:#eee;font:18px system-ui;max-width:1400px;margin:30px auto;padding:20px}img,video{width:100%}a{color:#9bdcff}</style>
<h1>Unified flight and impact — final</h1>
<p>Approved round 07, unchanged. One continuous eight-second shot: dive, airborne launch, sandstone smash, slide and close settle.</p>
<video controls loop src="unified_flight_impact_final.mp4"></video>
<p>1920 × 1080 · 24 fps · 192 frames · 64 samples · kaiju_1960s grade · CRF16.</p>
<p><a href="unified_flight_impact_final.mp4">Download MP4</a> · <a href="SHA256SUMS">SHA256</a> · <a href="final_verification.json">Verification</a></p>
<a href="final_decoded_contact.jpg"><img src="final_decoded_contact.jpg"></a><p>'''+
        ' · '.join(f'<a href="decoded_beats/frame_{f:04}.png">Frame {f}</a>' for f in BEATS)+'</p>')
    print('FINAL_VERIFIED', report['video'], report['sha256'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--rebalance', action='store_true',
                        help='After stopping old workers, split missing frames between both GPUs')
    args = parser.parse_args()
    main(args.source, args.directory, args.rebalance)
