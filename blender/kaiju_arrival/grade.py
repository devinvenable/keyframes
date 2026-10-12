"""Native linear EXRs -> recovered film compositor in Blender 4.1.1 -> AgX PNG.

The -3-code-value T309 salvage trim is deliberately not part of a native render.
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
import bpy
p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
p.add_argument('--profile',type=Path,default=Path('/home/devin/src/2026/voxel-shorts/scripts/post_process_profiles.py'))
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.output.mkdir(parents=True,exist_ok=True)
assert bpy.app.version[:2]==(4,1),'Use the recovered Blender 4.1 compositor'
assert hashlib.sha256(a.profile.read_bytes()).hexdigest()=='adf204f3cc23499a93616a5c8abc2ac73e9f106663fcf2b9c2d899f0a6952c38'
bpy.ops.wm.read_factory_settings(use_empty=True);s=bpy.context.scene
s.render.engine='CYCLES';s.view_settings.view_transform='AgX';s.view_settings.look='None';s.view_settings.exposure=-.8
spec=importlib.util.spec_from_file_location('film_profile',a.profile);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
mod._apply_kaiju_1960s(s,chromatic_aberration=.018,grain_intensity=.05,vignette_strength=.25,glare_strength=.35)
n=s.node_tree.nodes;l=s.node_tree.links;old=next(o for o in n if o.type=='R_LAYERS')
sockets=[link.to_socket for link in old.outputs['Image'].links];n.remove(old);node=n.new('CompositorNodeImage')
for socket in sockets:l.new(node.outputs['Image'],socket)
s.render.image_settings.file_format='PNG';s.render.image_settings.color_mode='RGB'
files=sorted(a.input.glob('frame_*.exr'));assert files,'No native EXRs'
for path in files:
    im=bpy.data.images.load(str(path.resolve()));node.image=im
    s.render.resolution_x,s.render.resolution_y=im.size;s.render.resolution_percentage=100
    s.frame_set(int(path.stem.split('_')[-1]));s.render.filepath=str(a.output/f'{path.stem}.png')
    bpy.ops.render.render(write_still=True);bpy.data.images.remove(im)
    print('ARRIVAL_GRADE',path.stem,flush=True)
(a.output/'grade.json').write_text(json.dumps({'blender':bpy.app.version_string,'frames':len(files),'profile_sha256':hashlib.sha256(a.profile.read_bytes()).hexdigest(),'exposure':-.8,'chain':'native scene-linear EXR -> recovered kaiju_1960s -> AgX; no inverse transform or salvage trim'},indent=2))
