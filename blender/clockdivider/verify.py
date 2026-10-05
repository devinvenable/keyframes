"""Artifact QA: Python + Pillow, ffprobe and ffmpeg; run after render_all.py.
Checks actual frame data and decoded movie alpha, then creates review contact sheets.
"""
import argparse
import json
from pathlib import Path
import subprocess
from PIL import Image, ImageChops, ImageDraw, ImageStat

p=argparse.ArgumentParser()
p.add_argument('--output',type=Path,default=Path('generated/clockdivider'))
a=p.parse_args()
report=[]
sheet=Image.new('RGB',(960,6*205),(12,17,22))
draw=ImageDraw.Draw(sheet)
for row,(treatment,aspect) in enumerate((t,a) for t in ['laser','fly','orbit'] for a in ['wide','square']):
    name=f'{treatment}-{aspect}'; folder=a.output/name
    frames=sorted((folder/'png').glob('frame_*.png'))
    assert [f.name for f in frames]==[f'frame_{i:04d}.png' for i in range(1,181)],name
    size=(1920 if aspect=='wide' else 1080,1080)
    cover=[]
    for f in frames:
        with Image.open(f) as im:
            assert im.mode=='RGBA' and im.size==size,(f,im.mode,im.size)
            alpha=im.getchannel('A'); hist=alpha.histogram()
            cover.append(sum(hist[1:]))
    assert max(cover)>1000, name+' empty render'
    if treatment=='laser':
        assert cover[0]==0 and cover[59]>0 and cover[119]>cover[29], (name,cover)
    if treatment=='fly':
        assert cover[-1]==0 and cover[89]>cover[0], (name,cover)
    media=[]
    for suffix in ['alpha.mov','preview.mp4']:
        path=folder/f'{name}-{suffix}'
        probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0',
             '-show_entries','stream=codec_name,pix_fmt,width,height,r_frame_rate,nb_read_frames,duration',
             '-of','json',str(path)]))['streams'][0]
        assert (probe['width'],probe['height'])==size and probe['r_frame_rate']=='30/1' and int(probe['nb_read_frames'])==180,probe
        assert probe['pix_fmt'].startswith('yuva') if suffix=='alpha.mov' else probe['pix_fmt']=='yuv420p',probe
        media.append(probe)
    decoded=folder/'decoded-alpha-0060.png'
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(folder/f'{name}-alpha.mov'),
                    '-vf',"select=eq(n\\,59)",'-frames:v','1',str(decoded)],check=True)
    original=Image.open(frames[59]).getchannel('A')
    movie_alpha=Image.open(decoded).getchannel('A')
    assert movie_alpha.getextrema()==(0,255),(name,movie_alpha.getextrema())
    mae=ImageStat.Stat(ImageChops.difference(original,movie_alpha)).mean[0]
    assert mae<1,(name,mae)
    report.append(dict(name=name,frame_count=len(frames),size=size,alpha_pixels_first=cover[0],
                       alpha_pixels_last=cover[-1],movie_alpha_mean_error=mae,media=media))
    draw.text((12,row*205+8),name+' / 1s · 3s · 4s',fill=(180,220,205))
    for col,frame in enumerate([30,90,120]):
        im=Image.open(frames[frame-1])
        bg=Image.new('RGBA',im.size,(0,0,0,255)); bg.alpha_composite(im)
        bg.thumbnail((310,174),Image.Resampling.LANCZOS)
        sheet.paste(bg.convert('RGB'),(col*320+(310-bg.width)//2,row*205+28))
# Transparency review, over two non-black backgrounds at full resolution.
source=Image.open(a.output/'laser-wide/png/frame_0120.png')
checker=Image.new('RGBA',source.size)
d=ImageDraw.Draw(checker)
for y in range(0,source.height,64):
    for x in range(0,source.width,64):
        color=(43,48,64,255) if (x//64+y//64)%2 else (93,70,97,255)
        d.rectangle((x,y,x+63,y+63),fill=color)
checker.alpha_composite(source)
checker.convert('RGB').save(a.output/'alpha-checkerboard.png')
sheet.save(a.output/'contact-sheet.jpg',quality=95)
(a.output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
