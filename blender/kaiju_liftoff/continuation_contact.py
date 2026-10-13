"""Create the four labeled review stills for the T316 preview gate."""
import argparse
from pathlib import Path
import cv2
import numpy as np

p = argparse.ArgumentParser()
p.add_argument('--original', type=Path, required=True)
p.add_argument('--candidate', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--frames', default='217,233,249,265')
a = p.parse_args()
frames = [int(f) for f in a.frames.split(',')]
plate = np.full((((len(frames)+1)//2)*580, 1920, 3), 25, dtype=np.uint8)
for i, frame in enumerate(frames):
    folder = a.original if frame == 217 else a.candidate
    im = cv2.imread(str(folder/f'frame_{frame:04}.png'))
    assert im is not None
    im = cv2.resize(im, (960, 540), interpolation=cv2.INTER_AREA)
    x, y = (i % 2)*960, (i // 2)*580
    plate[y+40:y+580, x:x+960] = im
    label = 'APPROVED END | frame 217' if i == 0 else f'CONTINUATION | +{(frame-217)/24:.2f}s | frame {frame}'
    cv2.putText(plate, label, (x+20, y+27), cv2.FONT_HERSHEY_SIMPLEX, .6, (255,255,255), 1, cv2.LINE_AA)
a.output.parent.mkdir(parents=True, exist_ok=True)
assert cv2.imwrite(str(a.output), plate, [cv2.IMWRITE_JPEG_QUALITY, 95])
