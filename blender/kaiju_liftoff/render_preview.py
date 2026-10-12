"""Render inexpensive review PNGs, keeping final settings in the saved scene.
Use --frames 1,62,94,120,168,217 for contact frames, or --animation.
"""
import argparse,sys
from pathlib import Path
import bpy
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--frames',default='1,62,94,120,168,217');p.add_argument('--animation',action='store_true');p.add_argument('--step',type=int,default=1);p.add_argument('--percent',type=int,default=33);p.add_argument('--samples',type=int,default=12);p.add_argument('--device',default='3060');p.add_argument('--backend',choices=['CUDA','OPTIX'],default='CUDA');p.add_argument('--start',type=int,default=2);p.add_argument('--end',type=int,default=217)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.output.mkdir(parents=True,exist_ok=True)
s=bpy.context.scene;s.render.engine='CYCLES';s.render.resolution_percentage=a.percent;s.cycles.samples=a.samples;s.cycles.use_denoising=True;s.cycles.use_adaptive_sampling=True;s.cycles.adaptive_threshold=.15
prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type=a.backend;prefs.get_devices()
for d in prefs.devices:d.use=d.type==a.backend and a.device in d.name
assert any(d.use for d in prefs.devices),f'{a.backend} device {a.device} not available'
s.cycles.device='GPU';s.render.use_persistent_data=True
s.cycles.denoising_use_gpu=True
s.cycles.volume_step_rate=4;s.cycles.volume_max_steps=128;s.cycles.volume_bounces=1
s.render.image_settings.file_format='PNG';s.render.image_settings.color_mode='RGB'
frames=range(a.start,a.end+1,a.step) if a.animation else [int(x) for x in a.frames.split(',')]
for f in frames:
 path=a.output/f'frame_{f:04}.png'
 if path.exists():continue
 s.frame_set(f);s.render.filepath=str(path);bpy.ops.render.render(write_still=True);print('REVIEW_FRAME',f,flush=True)
