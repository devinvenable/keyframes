"""Find first raster-visible beetle frame with full-resolution occlusion masks.

Frustum rejection skips guaranteed-empty frames; Workbench's depth buffer tests
remaining candidates against opaque scene geometry. Masks exclude film effects
and transparent dust, so the result describes the first visible solid silhouette.
"""
import argparse
from array import array
import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_take3 import empty_start

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
a.output.mkdir(parents=True, exist_ok=True)
s = bpy.context.scene
s.render.engine = 'BLENDER_WORKBENCH'
s.render.resolution_percentage = 100
s.render.image_settings.file_format = 'PNG'
s.render.film_transparent = False
s.render.use_compositing = False
s.render.use_sequencer = False
s.display.render_aa = 'OFF'
s.display.shading.light = 'FLAT'
s.display.shading.color_type = 'OBJECT'
s.display.shading.background_type = 'WORLD'
s.world.color = (0, 0, 0)
s.display.shading.show_shadows = False
s.display.shading.show_cavity = False
s.display.shading.show_object_outline = False
s.display.shading.show_specular_highlight = False
s.view_settings.view_transform = 'Standard'
s.view_settings.look = 'None'
s.view_settings.exposure = 0
s.view_settings.gamma = 1
for obj in s.objects:
    obj.color = (1, 1, 1, 1) if obj.name.startswith('BK |') else (0, 0, 0, 1)
    # Workbench would incorrectly treat volumetric dust domains as solid boxes.
    if obj.type == 'MESH' and any(mat and mat.use_nodes and any(node.type in {'VOLUME_PRINCIPLED', 'VOLUME_SCATTER', 'VOLUME_ABSORPTION'} for node in mat.node_tree.nodes) for mat in obj.data.materials):
        obj.hide_render = True
report = {'method': '1920x1080 un-antialiased white beetle / black opaque occluders depth mask; no film effects or volume domains', 'frames': []}
for frame in range(1, 53):
    s.frame_set(frame)
    try:
        empty_start(s)
    except AssertionError:
        path = a.output / f'mask_{frame:04}.png'
        s.render.filepath = str(path.resolve())
        bpy.ops.render.render(write_still=True)
        im = bpy.data.images.load(str(path.resolve()), check_existing=False)
        pixels = array('f', [0]) * len(im.pixels)
        im.pixels.foreach_get(pixels)
        count = sum(value > .5 for value in pixels[0::4])
        bpy.data.images.remove(im)
        report['frames'].append({'frame': frame, 'white_pixels': count, 'mask': str(path.resolve())})
        if count:
            report['first_visible_frame'] = frame
            break
    else:
        report['frames'].append({'frame': frame, 'white_pixels': 0, 'proof': 'All beetle bounds outside camera frustum'})
else:
    raise AssertionError('No visible beetle through contact')
(a.output / 'visibility.json').write_text(json.dumps(report, indent=2) + '\n')
print('FIRST_VISIBLE_BEETLE', report['first_visible_frame'], flush=True)
