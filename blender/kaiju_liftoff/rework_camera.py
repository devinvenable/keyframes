"""Apply only camera animation to the approved packed T305 scene.

blender -b APPROVED --python-exit-code 1 --python rework_camera.py -- --output NEW
"""
import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from camera_motion import animate_camera

p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, required=True)
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
assert a.output.resolve() != Path(bpy.data.filepath).resolve(), 'Preserve the approved input'
scene = bpy.context.scene
camera = scene.camera
fit = json.loads(Path(__file__).with_name('camera_match.json').read_text())
animate_camera(camera, Vector(fit['location']))
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(a.output.resolve()), compress=True)
