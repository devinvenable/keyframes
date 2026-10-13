"""Resumable impact-gate render from the one complete scene. No final mode."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BLENDER='/home/devin/bin/blender-5.1.2-linux-x64/blender'
GRADE='/home/devin/bin/blender-4.1.1-linux-x64/blender'
SCRIPTS=Path(__file__).resolve().parent
START,STOP=100,180
BEATS={100:'Approach',106:'First chest contact',112:'Launched off both feet',123:'Airborne into cliff',124:'Rock smash / debris birth',130:'After impact',148:'Sliding down',180:'Slumped settle'}


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def run(cmd,log):
    with log.open('w') as stream:
        subprocess.run(list(map(str,cmd)),stdout=stream,stderr=subprocess.STDOUT,check=True)


def compare(decoded,source):
    error=float(np.abs(decoded.astype(np.float32)-source.astype(np.float32)).mean())
    assert error<10, f'Encoded picture differs from graded frame: {error:.3f}'
    return error


def package(directory):
    video=directory/'impact_draft.mp4'; count=STOP-START+1
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=width,height,nb_read_frames,r_frame_rate,duration','-of','json',str(video)]))['streams'][0]
    assert int(probe['nb_read_frames'])==count, 'Draft frame count differs'
    assert probe['r_frame_rate']=='24/1', 'Draft frame rate differs'
    assert (probe['width'],probe['height'])==(960,540), 'Draft resolution differs'
    pixels=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-f','rawvideo','-pix_fmt','rgb24','-'])
    decoded=np.frombuffer(pixels,dtype=np.uint8).reshape(count,540,960,3)
    errors=[compare(picture,np.array(Image.open(directory/'draft_frames'/f'frame_{f:04}.png').convert('RGB'))) for f,picture in enumerate(decoded,START)]
    beats=directory/'decoded_beats'; beats.mkdir(exist_ok=True)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',22)
    sheet=Image.new('RGB',(1920,580*4),'#17191c'); draw=ImageDraw.Draw(sheet)
    for i,(f,label) in enumerate(BEATS.items()):
        im=Image.fromarray(decoded[f-START]); im.save(beats/f'frame_{f:04}.png')
        x,y=(i%2)*960,(i//2)*580; sheet.paste(im,(x,y+40))
        draw.text((x+12,y+8),f'{f}  {label}',font=font,fill='white')
    sheet.save(directory/'impact_beats.jpg',quality=94)
    hashes={str(p.relative_to(directory)):digest(p) for sub,ext in [('draft_exr','exr'),('draft_frames','png')] for p in sorted((directory/sub).glob(f'frame_*.{ext}'))}
    (directory/'media_qa.json').write_text(json.dumps({'status':'PASS','probe':probe,'video_sha256':digest(video),'full_decode':'PASS','encoded_pixel_mae':errors,'frame_sha256':hashes,'grade':json.loads((directory/'draft_frames/grade.json').read_text())},indent=2)+'\n')
    (directory/'review.html').write_text('''<!doctype html><meta charset="utf-8"><title>Unified impact — draft gate</title>
<style>body{background:#17191c;color:#eee;font:18px system-ui;max-width:1400px;margin:30px auto;padding:20px}img,video{width:100%}a{color:#9bdcff}</style>
<h1>Unified flight / impact — choreography review</h1>
<p>Accelerating contact → airborne wire-yank → sandstone smash → downward slide and slump.</p>
<p>This 3.375-second excerpt is rendered from frames 100–180 of the complete eight-second scene. The collision cliff exists from frame 1. The chase camera holds its impact station and pans with the beetle.</p>
<video controls loop src="impact_draft.mp4"></video>
<p>540p timing draft. Full 1080p render is pending impact approval.</p>
<a href="impact_beats.jpg"><img src="impact_beats.jpg"></a><p>'''+
        ' · '.join(f'<a href="decoded_beats/frame_{f:04}.png">{f}: {label}</a>' for f,label in BEATS.items())+'</p>')


def main(directory):
    scene=directory/'unified.blend'
    plan={'scene':str(scene),'scene_sha256':digest(scene),'range':[START,STOP],'fps':24,'resolution':[960,540],'samples':8,'render_blender':BLENDER,'grade_blender':GRADE,'draft_only':True,'devices':{'3060':[START,164],'1050':[165,STOP]}}
    path=directory/'draft_plan.json'
    if path.exists(): assert json.loads(path.read_text())==plan,'Draft plan changed'
    else: path.write_text(json.dumps(plan,indent=2)+'\n')
    exrs=directory/'draft_exr'; exrs.mkdir(exist_ok=True)
    def worker(device,first,last):
        pending=[f for f in range(first,last+1) if not (exrs/f'frame_{f:04}.exr').exists()]
        if pending: run([BLENDER,'-t','4','-b',scene,'--python-exit-code','1','--python',SCRIPTS.parent/'kaiju_arrival/render.py','--','--output',exrs,'--frames',','.join(map(str,pending)),'--samples','8','--percent','50','--device',device],directory/f'draft_render_{device}.log')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker,device,*span) for device,span in plan['devices'].items()]
        for future in futures: future.result()
    assert len(list(exrs.glob('frame_*.exr')))==STOP-START+1, 'Native frame count differs'
    run([GRADE,'-t','6','-b','--python-exit-code','1','--python',SCRIPTS.parent/'kaiju_arrival/grade.py','--','--input',exrs,'--output',directory/'draft_frames'],directory/'grade.log')
    run(['ffmpeg','-v','error','-y','-framerate','24','-start_number',str(START),'-i',directory/'draft_frames/frame_%04d.png','-frames:v',str(STOP-START+1),'-c:v','libx264','-crf','18','-preset','slow','-pix_fmt','yuv420p','-movflags','+faststart',directory/'impact_draft.mp4'],directory/'encode.log')
    assert digest(scene)==plan['scene_sha256'],'Scene changed during rendering'
    package(directory); print('DRAFT_READY',directory/'review.html',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--directory',type=Path,required=True); p.add_argument('--package-only',action='store_true')
    a=p.parse_args(); (package if a.package_only else main)(a.directory.resolve())
