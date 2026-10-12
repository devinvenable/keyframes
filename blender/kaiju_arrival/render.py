"""Render native scene-linear EXRs, selected beats or the entire baked shot."""
import argparse
import sys
from pathlib import Path
import bpy
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
p.add_argument('--frames',default='1,40,52,58,86');p.add_argument('--samples',type=int,default=16)
p.add_argument('--percent',type=int,default=75);p.add_argument('--device',default='3060')
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.output.mkdir(parents=True,exist_ok=True)
s=bpy.context.scene;s.cycles.samples=a.samples;s.render.resolution_percentage=a.percent
prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='CUDA';prefs.get_devices()
for d in prefs.devices:d.use=d.type=='CUDA' and a.device in d.name
assert any(d.use for d in prefs.devices),'Requested CUDA device unavailable'
s.cycles.device='GPU';s.render.use_compositing=False;s.render.image_settings.file_format='OPEN_EXR'
s.render.image_settings.color_depth='16'
s.render.use_persistent_data=True
frames=range(s.frame_start,s.frame_end+1) if a.frames=='all' else [int(f) for f in a.frames.split(',')]
for f in frames:
    s.frame_set(f);s.render.filepath=str(a.output/f'frame_{f:04}.exr');bpy.ops.render.render(write_still=True)
    print('ARRIVAL_RENDER',f,flush=True)
