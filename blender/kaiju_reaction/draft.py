"""Resumable draft-only pipeline. Run detached to avoid render harness timeouts."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor

from package import main as package

BLENDER='/home/devin/bin/blender-5.1.2-linux-x64/blender'
GRADE='/home/devin/bin/blender-4.1.1-linux-x64/blender'
SCRIPTS=Path(__file__).resolve().parent


def run(cmd,log):
    with log.open('w') as stream:
        subprocess.run(list(map(str,cmd)),stdout=stream,stderr=subprocess.STDOUT,check=True)


def main(directory):
    scene=directory/'reaction.blend'
    digest=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    plan={'scene':str(scene),'scene_sha256':digest(scene),'frames':84,'fps':24,
          'resolution':[960,540],'samples':8,'grade_blender':GRADE,'render_blender':BLENDER,
          'devices':{'3060':[1,52],'1050':[53,84]},'draft_only':True}
    path=directory/'draft_plan.json'
    if path.exists(): assert json.loads(path.read_text())==plan,'Draft plan changed'
    else: path.write_text(json.dumps(plan,indent=2)+'\n')
    exrs=directory/'draft_exr'; exrs.mkdir(exist_ok=True)
    def worker(device,start,end):
        pending=[f for f in range(start,end+1) if not (exrs/f'frame_{f:04}.exr').exists()]
        if pending:
            run([BLENDER,'-t','4','-b',scene,'--python-exit-code','1','--python',SCRIPTS.parent/'kaiju_arrival/render.py',
                 '--','--output',exrs,'--frames',','.join(map(str,pending)),'--samples','8','--percent','50','--device',device],
                directory/f'draft_render_{device}.log')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker,device,*span) for device,span in plan['devices'].items()]
        for future in futures: future.result()
    assert len(list(exrs.glob('frame_*.exr')))==84,'Missing native frames'
    run([GRADE,'-t','6','-b','--python-exit-code','1','--python',SCRIPTS.parent/'kaiju_arrival/grade.py',
         '--','--input',exrs,'--output',directory/'draft_frames'],directory/'draft_grade.log')
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-framerate','24','-start_number','1',
         '-i',directory/'draft_frames/frame_%04d.png','-frames:v','84','-c:v','libx264','-crf','18',
         '-preset','slow','-pix_fmt','yuv420p','-movflags','+faststart',directory/'reaction_draft.mp4'],directory/'encode.log')
    assert digest(scene)==plan['scene_sha256'],'Scene changed during render'
    package(directory)
    print('DRAFT_READY',directory/'review.html',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--directory',type=Path,required=True)
    main(p.parse_args().directory.resolve())
