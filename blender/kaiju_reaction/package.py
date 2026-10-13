"""Contact sheet and media evidence for the T322 review gate."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def compare_pixels(decoded, source):
    error=float(np.abs(decoded.astype(np.float32)-source.astype(np.float32)).mean())
    assert error < 10, f'Encoded picture differs from graded frame: {error:.3f}'
    return error


def main(directory):
    labels = {1:'First contact / same pose as dive endpoint',22:'Mid-stagger / second backward step',
              43:'Rock collision / fragments and falling powder',84:'Settle / upright, both feet planted'}
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',22)
    sheet=Image.new('RGB',(1920,1160),'#17191c'); draw=ImageDraw.Draw(sheet)
    for i,(f,label) in enumerate(labels.items()):
        x,y=(i%2)*960,(i//2)*580
        im=Image.open(directory/'stills'/f'frame_{f:04}.png'); assert im.size==(960,540)
        sheet.paste(im,(x,y+40)); draw.text((x+12,y+8),f'{f:02}  {label}',font=font,fill='white')
    sheet.save(directory/'staging_beats.jpg',quality=95)
    video=directory/'reaction_draft.mp4'
    if video.exists():
        probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0',
              '-show_entries','stream=width,height,nb_read_frames,r_frame_rate,duration','-of','json',str(video)]))['streams'][0]
        assert int(probe['nb_read_frames'])==84, 'Draft frame count differs'
        assert probe['r_frame_rate']=='24/1', 'Draft frame rate differs'
        assert (probe['width'],probe['height'])==(960,540), 'Draft resolution differs'
        subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(video),'-f','null','-'],check=True)
        pixels=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),
              '-f','rawvideo','-pix_fmt','rgb24','-'])
        decoded=np.frombuffer(pixels,dtype=np.uint8).reshape(84,540,960,3)
        errors=[]
        for i,picture in enumerate(decoded):
            source=np.array(Image.open(directory/'draft_frames'/f'frame_{i+1:04}.png').convert('RGB'))
            errors.append(compare_pixels(picture,source))
        beats=directory/'decoded_beats'; beats.mkdir(exist_ok=True)
        for f in (1,8,14,22,30,39,43,52,64,84):
            Image.fromarray(decoded[f-1]).save(beats/f'frame_{f:04}.png')
        (directory/'media_qa.json').write_text(json.dumps({'status':'PASS','probe':probe,
            'video_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'full_decode':'PASS',
            'all_frames_pixel_compared':True,'encoded_pixel_mae':errors,
            'grade':json.loads((directory/'draft_frames/grade.json').read_text())},indent=2)+'\n')
    motion='<video controls loop src="reaction_draft.mp4" style="width:100%"></video>' if video.exists() else ''
    camera=json.loads((directory/'manifest.json').read_text()).get('camera_mode','low')
    camera_label='Ground-level 32 mm camera' if camera=='low' else 'Dive-continuation 26 mm camera'
    (directory/'review.html').write_text('''<!doctype html><meta charset="utf-8"><title>Beetle reaction draft</title>
<style>body{background:#17191c;color:#eee;font:18px system-ui;max-width:1400px;margin:30px auto;padding:20px}img{width:100%}a{color:#9bdcff}</style>
<h1>Beetle reaction — staging and timing review</h1>
<p>Chest contact → glancing forward pass and powered climb → two backward steps → rock collision → upright settle.</p>
'''+f'<p>{camera_label}, rigid hinged armor, falling powder and bouncing stone fragments. Timing draft.</p>\n'+motion+'<a href="staging_beats.jpg"><img src="staging_beats.jpg"></a>\n'+
        '<p>'+' · '.join(f'<a href="stills/frame_{f:04}.png">{label}</a>' for f,label in labels.items())+'</p>')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True)
    main(p.parse_args().directory)
