"""Render one camera/pose-matched April 25 probe without changing its look.

blender -b kaiju_assembled.blend --python-exit-code 1 --python probe_apr25.py \
    -- --output /path/to/probe_apr25 [--draft]
The checked-in camera/pose fit is a seed; validate alignment against footage.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import bpy
from mathutils import Matrix, Quaternion

p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, required=True)
p.add_argument('--draft', action='store_true')
p.add_argument('--camera', type=Path, default=Path(__file__).with_name('camera_match.json'))
p.add_argument('--historical-profile', type=Path,
               help='April-era post_process_profiles.py (run this option in Blender 4.1.1)')
p.add_argument('--historical-samples', type=int, default=64,
               help='Historical batch used 64 samples (engram:chunk:777738)')
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
a.output.mkdir(parents=True, exist_ok=True)
s = bpy.context.scene
source = Path(bpy.data.filepath)
assert source.name == 'kaiju_assembled.blend', 'This probe requires the April 25 original'
source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
quality = {prop.identifier: getattr(s.cycles, prop.identifier)
           for prop in s.cycles.bl_rna.properties
           if not prop.is_readonly and prop.type in {'BOOLEAN', 'INT', 'FLOAT', 'STRING', 'ENUM'}
           and not prop.identifier.startswith(('preview_', 'debug_'))}
color = {key: getattr(s.view_settings, key)
         for key in ['view_transform', 'look', 'exposure', 'gamma']}
s.frame_set(496)
rig = bpy.data.objects['actor_kaiju_robot']
pose = {bone.name: bone.matrix_basis.copy() for bone in rig.pose.bones}
rig.animation_data_clear()
for name, matrix in pose.items():
    rig.pose.bones[name].matrix_basis = matrix
fit = json.loads(Path(__file__).with_name('pose_match.json').read_text())
dx, dz = fit['body_offset_xz']
rig.location = (dx, 80, -2 + dz)
rig.scale = (1.3 * fit['body_scale_ratio'],) * 3
bpy.context.view_layer.update()
arm = rig.pose.bones['arm_L']
pivot = arm.head.copy()
delta = Quaternion(fit['arm_quaternion_wxyz']).to_matrix().to_4x4()
arm.matrix = Matrix.Translation(pivot) @ delta @ Matrix.Translation(-pivot) @ arm.matrix
# As in the T305 endpoint: retain ring lighting/reflections, hide camera rays.
for obj in s.objects:
    if obj.name.startswith('actor_plasma_ring'):
        obj.visible_camera = False
camera = json.loads(a.camera.read_text())
c = s.camera
c.animation_data_clear()
c.constraints.clear()
c.matrix_world = Matrix(camera['matrix'])
c.data.lens = camera['lens']
s.render.resolution_x, s.render.resolution_y = 1920, 1080
s.render.resolution_percentage = 50 if a.draft else 100
s.render.image_settings.file_format = 'PNG'
s.render.image_settings.color_mode = 'RGB'
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'
prefs.get_devices()
for device in prefs.devices:
    device.use = device.type == 'OPTIX' and '3060' in device.name
assert any(device.use for device in prefs.devices), 'RTX 3060 OptiX unavailable'
s.cycles.device = 'GPU'
if a.draft:
    s.cycles.samples = 32
    s.cycles.adaptive_threshold = .1
stem = 'draft' if a.draft else 'matched_source_quality'
if a.historical_profile:
    import importlib.util
    spec = importlib.util.spec_from_file_location('historical_profile', a.historical_profile)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._apply_kaiju_1960s(s, chromatic_aberration=.018, grain_intensity=.05,
                            vignette_strength=.25, glare_strength=.35)
    s.cycles.samples = a.historical_samples
    stem = 'historical_profile' + ('_draft' if a.draft else '')
s.render.filepath = str(a.output / (stem + '.png'))
report = dict(source=str(source), source_sha256=source_hash, frame=496,
              blender_version=bpy.app.version_string,
              historical_profile=str(a.historical_profile) if a.historical_profile else None,
              camera=camera, pose=fit, source_quality=quality, color=color,
              draft=a.draft, devices=[d.name for d in prefs.devices if d.use],
              render_resolution=[s.render.resolution_x * s.render.resolution_percentage // 100,
                                 s.render.resolution_y * s.render.resolution_percentage // 100],
              effective_samples=s.cycles.samples,
              effective_adaptive_threshold=s.cycles.adaptive_threshold,
              camera_dof=dict(enabled=c.data.dof.use_dof,
                              distance=c.data.dof.focus_distance,
                              fstop=c.data.dof.aperture_fstop))
if not a.draft:
    for image in bpy.data.images:
        if image.filepath:
            image.filepath = bpy.path.abspath(image.filepath)
    bpy.ops.file.pack_all()
    blend_name = 'historical_profile.blend' if a.historical_profile else 'matched_apr25.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(a.output / blend_name), compress=True)
start = time.monotonic()
bpy.ops.render.render(write_still=True)
report['render_seconds'] = time.monotonic() - start
assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
report['source_unchanged'] = True
(a.output / (stem + '.json')).write_text(json.dumps(report, indent=2))
print('APR25_PROBE', json.dumps(report), flush=True)
