"""Render native 1080p24 with the original source's Cycles quality settings.

Unlike render_preview.py, this does not reduce volume quality or sample limits.
"""
import argparse
import hashlib
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
p.add_argument('--save-scene', type=Path)
p.add_argument('--native-exr', action='store_true', help='Write scene-linear float EXRs for direct grading')
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
if a.native_exr:
    s.render.image_settings.file_format = 'OPEN_EXR'
    s.render.image_settings.color_depth = '32'
    s.render.image_settings.exr_codec = 'ZIP'
suffix = 'exr' if a.native_exr else 'png'
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
            'source_sha256': hashlib.sha256(a.source.read_bytes()).hexdigest(),
            'candidate_sha256': hashlib.sha256(a.candidate.read_bytes()).hexdigest(),
            'quality': quality, 'color': color, 'resolution': [1920, 1080],
            'fps': 24, 'frames': [a.start, a.end], 'backend': a.backend,
            'devices': [d.name for d in prefs.devices if d.use]}
if a.native_exr:
    manifest['output_format'] = 'scene-linear RGB float32 OpenEXR ZIP'
settings_path = a.output/'render_settings.json'
if settings_path.exists():
    previous = json.loads(settings_path.read_text())
    assert all(previous.get(k) == v for k, v in manifest.items() if k != 'frames'), \
        'Render inputs/settings changed: use a fresh output directory'
settings_path.write_text(json.dumps(manifest, indent=2))
if a.save_scene:
    assert a.save_scene.resolve() not in {a.source.resolve(), a.candidate.resolve()}
    s.frame_set(1)
    s.render.filepath = str(a.output/'frame_')
    s['liftoff_note'] = 'Cinematic camera T306. Final render pre-approved by Devin, relayed by PM 2026-10-11. Source Cycles quality restored.'
    bpy.ops.wm.save_as_mainfile(filepath=str(a.save_scene.resolve()), compress=True)
for frame in range(a.start, a.end+1):
    path = a.output/f'frame_{frame:04}.{suffix}'
    if path.exists():
        continue
    start = time.monotonic()
    s.frame_set(frame)
    temporary = a.output/f'pending_{frame:04}.{suffix}'
    s.render.filepath = str(temporary)
    bpy.ops.render.render(write_still=True)
    temporary.replace(path)
    print('FINAL_FRAME', frame, 'SECONDS', round(time.monotonic()-start, 2), flush=True)
