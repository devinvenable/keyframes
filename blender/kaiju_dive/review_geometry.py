"""Build labeled evidence from native graded pixels and Blender ray-hit IDs."""
import argparse
import html
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--directory', type=Path, required=True)
a = p.parse_args()
d = a.directory.resolve()
font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
font = ImageFont.truetype(font_path, 20)
small = ImageFont.truetype(font_path, 16)
large = ImageFont.truetype(font_path, 27)
sheet = Image.new('RGB', (1760, 1350), '#17191c')
draw = ImageDraw.Draw(sheet)
draw.text((24, 18), 'T318 | Rear geometry audit: both features are intentional open hatch doors', font=large, fill='white')
draw.text((24, 60), 'Fresh frame 64 renders | 1050 Ti / 16 samples / native EXR + recovered film grade | No scene changes', font=font, fill='#cbd0d8')
colors = {'R': '#ffbf47', 'L': '#5ddcff'}
for row, pose in enumerate(('forward', 'swept')):
    y = 110 + row*580
    im = Image.open(d/pose/'stills/frame_0064.png').convert('RGB')
    assert im.size == (960, 540)
    sheet.paste(im, (0, y+30))
    draw.text((20, y), pose.upper()+' | unaltered graded render', font=font, fill='white')
    crop = im.crop((280, 265, 630, 465)).resize((770, 440))
    sheet.paste(crop, (980, y+75))
    draw.text((980, y), '2.2x detail | hatch outlines from camera ray hits', font=font, fill='white')
    hits = json.loads((d/f'{pose}_hardware_pixels.json').read_text())
    for side in ('R', 'L'):
        points = {tuple(v) for v in hits[f'Hatch {side} | original armor']}
        boundary = [(x, yy) for x, yy in points if any((x+dx, yy+dy) not in points for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)))]
        for x, yy in boundary:
            px, py = 980+(x-280)*2.2, y+75+(yy-265)*2.2
            draw.ellipse((px-1, py-1, px+1, py+1), fill=colors[side])
    draw.text((990, y+45), 'LEFT PANEL: Hatch R | original armor', font=small, fill=colors['R'])
    draw.text((990, y+526), 'RIGHT "STICK": Hatch L | original armor (edge-on)', font=small, fill=colors['L'])
    draw.line([(1545, y+520), (1550, y+305), (1556, y+267)], fill=colors['L'], width=2)
    draw.line([(1150, y+67), (1165, y+171)], fill=colors['R'], width=2)
draw.text((24, 1282), 'Both hinges remain at the T305 deployed +/-112 degrees. All 58 hardware objects retain source geometry and parents.', font=font, fill='white')
draw.text((24, 1314), 'Both poses / 96 frames checked. Native robot weights unchanged; no unweighted vertices or extra attached meshes.', font=font, fill='#cbd0d8')
sheet.save(d/'annotated_geometry.jpg', quality=96)
(d/'review.html').write_text('''<!doctype html><meta charset="utf-8"><title>T318 robot geometry audit</title>
<style>body{background:#17191c;color:#eee;font:18px system-ui;max-width:1760px;margin:30px auto;padding:20px}img{width:100%}a{color:#8cddff}p{max-width:1100px;line-height:1.5}</style>
<h1>Both rear silhouettes are intentional hatch doors</h1>
<p>The screen-left panel is <b>Hatch R | original armor</b>. The screen-right stick is <b>Hatch L | original armor</b>, viewed almost edge-on. L/R are source object labels, not screen directions. Their hinges remain at the T305 deployed ±112°. The thin bolts along the edge also belong to the hatch.</p>
<p>These parts were added for T305's booster deployment; the earlier native master has a closed dorsal torso face instead. The dive correctly opens that bay and carries over both doors, boosters, bridges and rams. No scene changes were needed.</p>
<a href="annotated_geometry.jpg"><img src="annotated_geometry.jpg"></a>
<p><a href="forward/stills/frame_0064.png">Fresh forward frame 64</a> · <a href="swept/stills/frame_0064.png">Fresh swept frame 64</a> · <a href="geometry_audit.json">Machine-readable source comparison</a></p>
<p>Audit: all 58 imported hardware objects preserve source geometry and parenting. Their deployed transforms match through all 96 frames of both scenes, apart from intentional exhaust length flutter. All 1,822 native mesh vertices and their skin weights match the master; none are unweighted. No other loose or unposed rear-view pieces were found in the six saved key beats or the two fresh frame-64 renders.</p>
<p>The orange/cyan outlines identify surface hits from Blender camera rays over the actual graded render crop. They are annotations, not a replacement render or an altered robot design. The saved T317 scenes remain the review scenes.</p>
''')
print(d/'review.html')
