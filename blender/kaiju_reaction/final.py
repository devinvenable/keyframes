"""Resume approved reaction finals using the T320 grade and streaming decode QA."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import sys

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS.parent/'kaiju_dive'))
from final_pipeline import BLENDER, GRADE, digest, run, package


def main(source, root, approval):
    assert approval.strip(), 'Record final render approval'
    source = source.resolve(); root = root.resolve(); root.mkdir(parents=True, exist_ok=True)
    scene = source/'reaction.blend'
    plan = {'scene': str(scene), 'scene_sha256': digest(scene), 'frames': [1,84],
            'fps':24, 'resolution':[1920,1080], 'samples':64, 'crf':16,
            'devices':{'3060':[1,64], '1050':[65,84]},
            'render_blender':BLENDER, 'grade_blender':GRADE, 'approval':approval}
    plan_path = root/'final_render_plan.json'
    if plan_path.exists():
        assert json.loads(plan_path.read_text()) == plan, 'Changed render plan'
    else:
        plan_path.write_text(json.dumps(plan, indent=2)+'\n')
    draft = json.loads((source/'media_qa.json').read_text())
    assert draft['status']=='PASS' and draft['all_frames_pixel_compared']
    assert draft['video_sha256']==digest(source/'reaction_draft.mp4'), 'Draft changed after QA'
    draft_plan = json.loads((source/'draft_plan.json').read_text())
    assert draft_plan['scene_sha256']==plan['scene_sha256'], 'Final differs from draft scene'
    # Verifiers write evidence to the output directory; the source blend is read-only.
    shutil.copy2(source/'manifest.json', root/'manifest.json')
    run([BLENDER,'-t','4','-b',scene,'--python-exit-code','1','--python',
         SCRIPTS/'verify.py','--','--directory',root,'--negative-checks'],root/'scene_qa.log')
    run([BLENDER,'-t','4','-b',scene,'--python-exit-code','1','--python',
         SCRIPTS/'pixel_contract.py','--','--directory',root],root/'pixel_contract.log')
    exrs = root/'final_exr'; exrs.mkdir(exist_ok=True)
    expected = {f'frame_{f:04}.exr' for f in range(1,85)}
    assert {p.name for p in exrs.glob('frame_*.exr')} <= expected
    def worker(device, start, end):
        pending = [f for f in range(start,end+1) if not (exrs/f'frame_{f:04}.exr').exists()]
        if pending:
            run([BLENDER,'-t','4','-b',scene,'--python-exit-code','1','--python',
                 SCRIPTS.parent/'kaiju_arrival/render.py','--','--output',exrs,
                 '--frames',','.join(map(str,pending)),'--samples','64','--percent','100',
                 '--device',device],root/f'render_{device}.log')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker,device,*span) for device,span in plan['devices'].items()]
        for future in futures: future.result()
    assert {p.name for p in exrs.glob('frame_*.exr')} == expected
    hashes = {p.name:digest(p) for p in sorted(exrs.glob('frame_*.exr'))}
    (root/'native_frame_hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
    run([GRADE,'-t','6','-b','--python-exit-code','1','--python',
         SCRIPTS.parent/'kaiju_arrival/grade.py','--','--input',exrs,
         '--output',root/'final_frames'],root/'final_grade.log')
    grade = json.loads((root/'final_frames/grade.json').read_text())
    assert grade['frames']==84 and grade['blender']=='4.1.1'
    report = package(root,84,'reaction_final.mp4',beats=[1,4,8,12,16,22,30,39,43,52,64,84])
    assert digest(scene)==plan['scene_sha256'], 'Approved scene changed during render'
    report.update(plan=plan,grade=grade,native_frame_sha256=hashes,
                  scene_qa=json.loads((root/'scene_qa.json').read_text()),
                  pixel_counts=json.loads((root/'pixel_counts.json').read_text()))
    (root/'final_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print('FINAL_VERIFIED',report['video'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--approval-note',required=True)
    a=p.parse_args(); main(a.source,a.directory,a.approval_note)
