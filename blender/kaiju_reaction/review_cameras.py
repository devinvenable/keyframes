"""A/B staging gate, with full-resolution early-frame sheets for the impact arc."""
import argparse
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from package import main as package


def main(root):
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',22)
    sections=[]
    for mode,label in [('low','A — Ground-level 32 mm'),('continuation','B — Dive camera continuation, 26 mm')]:
        directory=root/mode; package(directory)
        sheet=Image.new('RGB',(1920,1740),'#17191c'); draw=ImageDraw.Draw(sheet)
        for i,f in enumerate((1,4,8,12,16,20)):
            x,y=(i%2)*960,(i//2)*580
            picture=Image.open(directory/'stills'/f'frame_{f:04}.png'); assert picture.size==(960,540)
            sheet.paste(picture,(x,y+40))
            draw.text((x+12,y+8),f'{label}  |  frame {f:02} / {(f-1)/24:.3f}s',font=font,fill='white')
        sheet.save(directory/'early_frames.jpg',quality=96)
        links=' · '.join(f'<a href="{mode}/stills/frame_{f:04}.png">f{f}</a>' for f in (1,4,8,12,16,20,22,43,84))
        sections.append(f'<section><h2>{label}</h2><p>Full-size stills: {links}</p>'
            f'<h3>Contact → glancing pass → powered climb</h3><a href="{mode}/early_frames.jpg"><img src="{mode}/early_frames.jpg"></a>'
            f'<h3>Four staging beats</h3><a href="{mode}/staging_beats.jpg"><img src="{mode}/staging_beats.jpg"></a></section>')
    (root/'review.html').write_text('''<!doctype html><meta charset="utf-8"><title>Beetle reaction — revised camera gate</title>
<style>body{background:#17191c;color:#eee;font:18px system-ui;max-width:1600px;margin:30px auto;padding:20px}img{width:100%}a{color:#9bdcff}section{margin-top:50px}p{line-height:1.5}</style>
<h1>Beetle reaction — revised staging and camera choice</h1>
<p>The collision stack is an instance of the original sandstone asset, with its original geometry, textures and scale.
The robot carries forward momentum into the stagger, glances past the shoulder, then climbs with visibly increased rocket thrust.</p>
<p>A keeps the ground camera. B starts at the exact dive endpoint camera position, orientation and lens, then tracks the beetle's retreat.
Both use identical creature motion and rock placement.</p>
<p>Early frames are shown at 960×540 per panel; click any sheet or individual frame to inspect it closely.
Motion rendering is parked pending this staging/camera review. Final rendering also remains gated.</p>
'''+''.join(sections))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True)
    main(p.parse_args().directory)
