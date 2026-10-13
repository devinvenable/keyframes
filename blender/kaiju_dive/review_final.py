"""Package the T320 endpoint gate and the complete terrain inspection sweep."""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw

p = argparse.ArgumentParser(); p.add_argument('--directory', type=Path, required=True)
a = p.parse_args(); root = a.directory.resolve()
groups = {'contact_gate': [96, 101, 106], 'horizon_sweep': [1, 16, 20, 24, 28, 32, 40, 48, 64, 80, 96, 106]}
html = ['<!doctype html><meta charset="utf-8"><title>Dive contact review</title>',
        '<style>body{background:#17191c;color:#eee;font:18px system-ui;margin:32px}img{width:100%;height:auto}figure{margin:20px 0}a{color:#bce}</style>',
        '<h1>Dive: approach to first contact</h1><p>Frames 96, 101, 106. Frame 106 is the first contact instant; no recoil or aftermath. The chase camera, swept arms and deployed hatches are retained.</p>']
for name, frames in groups.items():
    sheet = Image.new('RGB', (1440, 300*((len(frames)+2)//3)), '#17191c')
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(frames):
        path = root/'check_frames'/f'frame_{frame:04}.png'
        with Image.open(path) as im:
            sheet.paste(im.resize((480, 270)), (480*(index%3), 300*(index//3)+30))
        draw.text((480*(index%3)+12, 300*(index//3)+8), f'Frame {frame}', fill='white')
    sheet.save(root/f'{name}.jpg', quality=95)
    html.append(f'<h2>{name.replace("_", " ")}</h2><img src="{name}.jpg">')
    html.append('<p>'+ ' · '.join(f'<a href="check_frames/frame_{f:04}.png">Frame {f}</a>' for f in frames)+'</p>')
(root/'review.html').write_text('\n'.join(html))
print(root/'review.html')
