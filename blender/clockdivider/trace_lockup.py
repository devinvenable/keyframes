"""Extract exact orthogonal outlines from the original artist-owned bitmap.
Run with Python + Pillow; build.py only needs the resulting outlines.json.
"""
from pathlib import Path
from PIL import Image
import json
import argparse

base = Path(__file__).resolve().parent
p=argparse.ArgumentParser()
p.add_argument('--tall',action='store_true')
args=p.parse_args()
im = Image.open(base / ('reference-tall.png' if args.tall else 'reference-lockup.png')).convert('L')
px = im.load()
solid = {(x,y) for y in range(im.height) for x in range(im.width) if px[x,y] > 127}
edges = {}
for x,y in solid:
    for neighbor,a,b in [((x,y-1),(x,y),(x+1,y)), ((x+1,y),(x+1,y),(x+1,y+1)),
                          ((x,y+1),(x+1,y+1),(x,y+1)), ((x-1,y),(x,y+1),(x,y))]:
        if neighbor not in solid:
            edges[a] = b
loops = []
while edges:
    start = min(edges)
    p = start
    loop = []
    while True:
        loop.append(p)
        p = edges.pop(p)
        if p == start:
            break
    corners = []
    for i,p in enumerate(loop):
        prev,nxt = loop[i-1],loop[(i+1)%len(loop)]
        if (p[0]-prev[0],p[1]-prev[1]) != (nxt[0]-p[0],nxt[1]-p[1]):
            corners.append(p)
    loops.append(corners)
loops.sort(key=lambda loop:(min(p[0] for p in loop),min(p[1] for p in loop)))
(base/('outlines-tall.json' if args.tall else 'outlines.json')).write_text(json.dumps(loops,indent=2)+'\n')
print(len(loops), 'closed contours,',sum(map(len,loops)), 'corners')
