"""Package graded pose/key-beat stills, without starting a motion/final render."""
import argparse
import html
import json
from pathlib import Path
from PIL import Image, ImageDraw

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--directory', type=Path, required=True)
a = p.parse_args()
d = a.directory.resolve()
beats = [(1, 'High sky / full thrust'), (64, 'Descent / beetle notices'), (96, 'Pre-impact / defensive brace')]
sheet = Image.new('RGB', (1440, 616), '#17191c')
draw = ImageDraw.Draw(sheet)
items = []
for row, (pose, label) in enumerate([('forward', 'A — arms extended forward'), ('swept', 'B — arms swept at sides')]):
    for col, (frame, beat) in enumerate(beats):
        path = d/pose/'stills'/f'frame_{frame:04}.png'
        image = Image.open(path).convert('RGB')
        assert image.size == (960, 540)
        sheet.paste(image.resize((480, 270)), (480*col, 308*row+36))
        draw.text((480*col+10, 308*row+8), f'{label} | {frame}: {beat}', fill='white')
        items.append({'pose': pose, 'frame': frame, 'path': str(path), 'beat': beat})
sheet.save(d/'pose_keybeats.jpg', quality=94)
rows = []
for pose, label in [('forward', 'A — arms extended forward'), ('swept', 'B — arms swept at sides')]:
    figures = ''.join(f'<figure><a href="{pose}/stills/frame_{f:04}.png"><img src="{pose}/stills/frame_{f:04}.png"></a><figcaption>{html.escape(beat)} · frame {f}</figcaption></figure>' for f, beat in beats)
    rows.append(f'<h2>{label}</h2><div class="beats">{figures}</div>')
(d/'review.html').write_text('''<!doctype html><meta charset="utf-8"><title>T317 flying robot — first picks</title>
<style>body{background:#15171b;color:#f5f2ea;font:17px system-ui;max-width:1700px;margin:40px auto;padding:0 28px}h1{font-size:32px}p{max-width:950px;line-height:1.5}.beats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}figure{margin:0}img{width:100%;display:block}figcaption{padding:8px 0;color:#c4c8d0}a{color:#b8d6ff}</style>
<h1>Robot dive · pose and endpoint review</h1>
<p>The camera rides behind the robot through a four-second descent. Both boosters fire throughout. The beetle looks up, turns its head and torso, shifts weight and raises its guard. This shot ends before impact.</p>
<p>Pick A or B, and review the endpoint framing first. These are 960 × 540 graded stills. Draft motion follows the still review; final rendering needs a separate approval.</p>
'''+''.join(rows))
(d/'review_manifest.json').write_text(json.dumps({'review_only': True, 'stills': items}, indent=2)+'\n')
print(d/'review.html')
