"""Recover approximate scene-linear pixels from one AgX PNG for grade QA.

Requires numpy, OpenCV (EXR enabled), and PyOpenColorIO. Use the OCIO config
of the Blender version that wrote the PNG. Eight-bit quantization, clipping,
and denoising cannot be undone; this is not an original HDR render pass.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
import cv2
import numpy as np
import PyOpenColorIO as ocio

p = argparse.ArgumentParser()
p.add_argument('--input', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--config', type=Path, required=True)
a = p.parse_args()
assert a.output.suffix == '.exr' and a.output.resolve() != a.input.resolve()
start = time.monotonic()
image = cv2.imread(str(a.input))
assert image is not None, f'Cannot read {a.input}'
rgb = np.ascontiguousarray(image[:, :, ::-1], dtype=np.float32) / 255
config = ocio.Config.CreateFromFile(str(a.config))
transform = ocio.DisplayViewTransform(src='Linear Rec.709', display='sRGB', view='AgX',
                                      direction=ocio.TRANSFORM_DIR_INVERSE)
linear = rgb.copy()
config.getProcessor(transform).getDefaultCPUProcessor().applyRGB(linear)
assert cv2.imwrite(str(a.output), linear[:, :, ::-1])
transform.setDirection(ocio.TRANSFORM_DIR_FORWARD)
roundtrip = linear.copy()
config.getProcessor(transform).getDefaultCPUProcessor().applyRGB(roundtrip)
error = np.abs(roundtrip - rgb) * 255
report = dict(input=str(a.input), output=str(a.output), config=str(a.config),
              input_sha256=hashlib.sha256(a.input.read_bytes()).hexdigest(),
              config_sha256=hashlib.sha256(a.config.read_bytes()).hexdigest(),
              ocio_version=ocio.__version__, roundtrip_mae=float(error.mean()),
              roundtrip_max=float(error.max()), seconds=time.monotonic() - start,
              clipped_channel_fraction=float(np.mean(image == 255)),
              caveat='Inverse view of quantized PNG; not original scene-linear radiance')
a.output.with_suffix('.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
