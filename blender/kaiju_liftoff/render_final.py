"""Render native 1080p24 with the original source's Cycles quality settings.

Unlike render_preview.py, this does not reduce volume quality or sample limits.
"""
import argparse
import json
from pathlib import Path
import sys
import time

import bpy

p = argparse.ArgumentParser()
p.add_argument('--source', type=Path, required=True)
p.add_argument('--candidate', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--start', type=int, default=2)
p.add_argument('--end', type=int, default=217)
p.add_argument('--device', default='3060')
p.add_argument('--backend', choices=['CUDA', 'OPTIX'], default='OPTIX')
a = p.parse_args(sys.argv[sys.argv.index('--')+1:])

bpy.ops.wm.open_mainfile(filepath=str(a.source), load_ui=False, use_scripts=False)
source = bpy.context.scene
quality = {p.identifier: getattr(source.cycles, p.identifier)
           for p in source.cycles.bl_rna.properties
           if not p.is_readonly and p.type in {'BOOLEAN', 'INT', 'FLOAT', 'STRING', 'ENUM'}
           and not p.identifier.startswith(('preview_', 'debug_'))}
color = {k: getattr(source.view_settings, k)
         for k in ['view_transform', 'look', 'exposure', 'gamma']}
bpy.ops.wm.open_mainfile(filepath=str(a.candidate), load_ui=False, use_scripts=False)
s = bpy.context.scene
for key, value in quality.items():
    setattr(s.cycles, key, value)
for key, value in color.items():
    setattr(s.view_settings, key, value)
s.render.engine = 'CYCLES'
s.render.resolution_x, s.render.resolution_y = 1920, 1080
s.render.resolution_percentage = 100
s.render.fps = 24
s.render.image_settings.file_format = 'PNG'
s.render.image_settings.color_mode = 'RGB'
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = a.backend
prefs.get_devices()
for device in prefs.devices:
    device.use = device.type == a.backend and a.device in device.name
assert any(d.use for d in prefs.devices), 'Requested GPU unavailable'
s.cycles.device = 'GPU'
s.render.use_persistent_data = True
a.output.mkdir(parents=True, exist_ok=True)
manifest = {'source': str(a.source), 'candidate': str(a.candidate),
            'quality': quality, 'color': color, 'resolution': [1920, 1080],
            'fps': 24, 'frames': [a.start, a.end], 'backend': a.backend,
            'devices': [d.name for d in prefs.devices if d.use]}
(a.output/'render_settings.json').write_text(json.dumps(manifest, indent=2))
for frame in range(a.start, a.end+1):
    path = a.output/f'frame_{frame:04}.png'
    if path.exists():
        continue
    start = time.monotonic()
    s.frame_set(frame)
    s.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    print('FINAL_FRAME', frame, 'SECONDS', round(time.monotonic()-start, 2), flush=True)
