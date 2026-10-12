"""Apply the recovered April compositor to one scene-linear EXR in Blender 4.1.

This is a probe, not authorization to process the extension sequence.
PNG inputs must first be inverse-transformed from their original AgX view.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

import bpy

p = argparse.ArgumentParser()
p.add_argument('--input', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--profile', type=Path, required=True)
p.add_argument('--bypass', action='store_true')
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
assert a.input.suffix == '.exr', 'Input must be reconstructed scene-linear EXR'
bpy.ops.wm.read_factory_settings(use_empty=True)
s = bpy.context.scene
s.render.engine = 'CYCLES'
s.render.resolution_x, s.render.resolution_y = 1920, 1080
s.render.resolution_percentage = 100
s.view_settings.view_transform = 'AgX'
s.view_settings.look = 'None'
spec = importlib.util.spec_from_file_location('historical_profile', a.profile)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module._apply_kaiju_1960s(s, chromatic_aberration=.018, grain_intensity=.05,
                        vignette_strength=.25, glare_strength=.35)
tree = s.node_tree
old = next(n for n in tree.nodes if n.type == 'R_LAYERS')
destinations = [l.to_socket for l in old.outputs['Image'].links]
tree.nodes.remove(old)
node = tree.nodes.new('CompositorNodeImage')
node.image = bpy.data.images.load(str(a.input.resolve()))
for socket in destinations:
    tree.links.new(node.outputs['Image'], socket)
if a.bypass:
    for output in [n for n in tree.nodes if n.type in {'COMPOSITE', 'VIEWER'}]:
        tree.links.new(node.outputs['Image'], output.inputs['Image'])
s.render.image_settings.file_format = 'PNG'
s.render.image_settings.color_mode = 'RGB'
s.render.filepath = str(a.output.resolve())
start = time.monotonic()
bpy.ops.render.render(write_still=True)
report = dict(input=str(a.input), output=str(a.output), profile=str(a.profile),
              bypass=a.bypass, seconds=time.monotonic() - start,
              blender_version=bpy.app.version_string)
a.output.with_suffix('.json').write_text(json.dumps(report, indent=2))
print('GRADE_PROBE', report)
