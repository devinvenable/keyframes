"""Render one review still on an explicitly selected CUDA device."""
import argparse
import sys
from pathlib import Path
import bpy
from mathutils import Vector

p=argparse.ArgumentParser()
p.add_argument('--output',type=Path,required=True)
p.add_argument('--percent',type=int,default=100)
p.add_argument('--samples',type=int,default=48)
p.add_argument('--device',default='1050')
p.add_argument('--view',choices=['saved','rear'],default='saved')
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
s=bpy.context.scene
if a.view=='rear':
    assert s.get('asset_collection'),'Rear view is for the standalone model'
    s.camera.location=(128,210,100)
    s.camera.rotation_quaternion=(Vector((0,0,51))-s.camera.location).to_track_quat('-Z','Y')
s.render.engine='CYCLES';s.render.resolution_percentage=a.percent
s.cycles.samples=a.samples;s.cycles.use_denoising=True
s.cycles.use_adaptive_sampling=True;s.cycles.adaptive_threshold=.08
prefs=bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type='CUDA';prefs.get_devices()
for d in prefs.devices:d.use=d.type=='CUDA' and a.device in d.name
assert any(d.use for d in prefs.devices),f'CUDA device {a.device} unavailable'
s.cycles.device='GPU'
s.cycles.volume_step_rate=2;s.cycles.volume_max_steps=128
s.cycles.volume_bounces=1
a.output.parent.mkdir(parents=True,exist_ok=True)
s.render.filepath=str(a.output)
bpy.ops.render.render(write_still=True)
print('BEETLE_RENDER_COMPLETE',a.output)
