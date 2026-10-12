"""Encode the reviewed 24fps draft and make a labeled beat contact sheet."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw
p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True);p.add_argument('--final',action='store_true')
a=p.parse_args();d=a.directory.resolve();frames=d/('final_frames' if a.final else 'preview_frames');stills=d/'final_stills'
def run(args):return subprocess.run([str(x) for x in args],check=True,capture_output=True,text=True).stdout
paths=[frames/f'frame_{i:04}.png' for i in range(1,109)]
for path in paths:
    with Image.open(path) as im:assert im.size==((1920,1080) if a.final else (960,540)),(path,im.size)
video=d/('beetle_arrival_final.mp4' if a.final else 'beetle_arrival_preview.mp4')
run(['ffmpeg','-hide_banner','-loglevel','error','-y','-framerate','24','-start_number','1','-i',frames/'frame_%04d.png','-frames:v','108','-c:v','libx264','-crf','16' if a.final else '18','-preset','slow','-pix_fmt','yuv420p','-movflags','+faststart',video])
probe=json.loads(run(['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=width,height,r_frame_rate,nb_read_frames,duration','-of','json',video]))['streams'][0]
assert probe['r_frame_rate']=='24/1' and int(probe['nb_read_frames'])==108,probe
assert abs(float(probe['duration'])-4.5)<.001,probe
run(['ffmpeg','-v','error','-i',video,'-f','null','-'])
beats=[(1,'01  VALLEY ESTABLISHING / WIDE'),(40,'40  BEETLE AIRBORNE'),(52,'52  FIRST CONTACT'),(58,'58  DUST + FAST ZOOM'),(63,'63  ZOOM END'),(86,'86  FIGHTING POSE')]
sheet=Image.new('RGB',(1280,3*392),(20,22,24));draw=ImageDraw.Draw(sheet)
for i,(f,label) in enumerate(beats):
    path=(frames if a.final else stills)/f'frame_{f:04}.png'
    if a.final:
        import shutil
        stills.mkdir(exist_ok=True)
        shutil.copy2(path,stills/path.name)
    if not path.exists():path=frames/f'frame_{f:04}.png'
    with Image.open(path) as im:tile=im.resize((640,360))
    x=(i%2)*640;y=(i//2)*392
    sheet.paste(tile,(x,y));draw.text((x+12,y+369),label,fill=(230,225,215))
sheet.save(d/'key_beats.jpg',quality=94)
source=d.parent/'kaiju_beetle_307';original=json.loads((source/'review_manifest.json').read_text())
source_checks={name:hashlib.sha256((source/name).read_bytes()).hexdigest()==entry['sha256'] for name,entry in original['artifacts'].items()}
assert all(source_checks.values()),'T307 source artifact changed'
report={'video':probe,'video_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'all_T307_artifact_hashes_unchanged':source_checks,'outputs':{'preview':str(video),'contact_sheet':str(d/'key_beats.jpg'),'scene':str(d/('beetle_arrival_final.blend' if a.final else 'beetle_arrival.blend')),'stills':str(stills)},'grade':json.loads((frames/'grade.json').read_text()),'status':'PASS'}
(d/('final_media_verification.json' if a.final else 'media_verification.json')).write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
