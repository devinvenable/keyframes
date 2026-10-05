"""Blender 5.x: deterministic native curve animation, no handlers/add-ons.
blender -b -t 4 --python blender/clockdivider/build.py -- --treatment laser --format wide
Add --render for all 180 frames, or --frame 120 for a proof.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy

p = argparse.ArgumentParser()
p.add_argument('--treatment', choices=['laser', 'fly', 'orbit'], default='laser')
p.add_argument('--format', choices=['wide','square'], default='wide')
p.add_argument('--render', action='store_true')
p.add_argument('--resume', action='store_true', help='Skip existing sequence frames')
p.add_argument('--frame', type=int)
p.add_argument('--output', type=Path, default=Path('generated/clockdivider'))
a = p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
base = Path(__file__).resolve().parent
out = a.output.resolve() / f'{a.treatment}-{a.format}'
(out/'png').mkdir(parents=True,exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
s = bpy.context.scene
s.render.engine = 'CYCLES'
s.cycles.samples = 64
s.cycles.use_denoising = False
prefs = bpy.context.preferences.addons['cycles'].preferences
try:
    prefs.compute_device_type = 'OPTIX'
    prefs.get_devices()
    devices=[d for d in prefs.devices if d.type=='OPTIX']
    chosen=next((d for d in devices if '3060' in d.name),devices[0] if devices else None)
    for d in prefs.devices:
        d.use = d == chosen
    s.cycles.device = 'GPU' if chosen else 'CPU'
except Exception:
    s.cycles.device = 'CPU'
s.render.resolution_x = 1920 if a.format == 'wide' else 1080
s.render.resolution_y = 1080
s.render.resolution_percentage = 100
s.render.fps = 30
s.render.use_overwrite = not a.resume
s.frame_start,s.frame_end = 1,180
s.render.film_transparent = True
s.render.image_settings.file_format = 'PNG'
s.render.image_settings.color_mode = 'RGBA'
s.render.image_settings.color_depth = '8'
s.render.image_settings.compression = 35
s.view_settings.view_transform = 'Standard'
s.world = bpy.data.worlds.new('Transparent world')
s.world.use_nodes = True
s.world.node_tree.nodes['Background'].inputs[0].default_value = (0,0,0,1)
# Glow alpha follows its light, so the halo survives compositing over footage.
comp = bpy.data.node_groups.new('Phosphor bloom with real alpha','CompositorNodeTree')
s.compositing_node_group = comp
comp.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
n=comp.nodes; links=comp.links
rl=n.new('CompositorNodeRLayers')
glow=n.new('CompositorNodeGlare'); glow.inputs['Type'].default_value='Fog Glow'; glow.inputs['Quality'].default_value='High'
glow.inputs['Threshold'].default_value=.25
glow.inputs['Strength'].default_value=.25
glow.inputs['Size'].default_value=.2
links.new(rl.outputs['Image'],glow.inputs['Image'])
sep=n.new('CompositorNodeSeparateColor'); links.new(glow.outputs['Image'],sep.inputs['Image'])
maximum=n.new('ShaderNodeMath'); maximum.operation='MAXIMUM'
links.new(rl.outputs['Alpha'],maximum.inputs[0]); links.new(sep.outputs['Green'],maximum.inputs[1])
alpha=n.new('CompositorNodeSetAlpha'); alpha.inputs['Type'].default_value='Replace Alpha'
links.new(glow.outputs['Image'],alpha.inputs['Image']); links.new(maximum.outputs[0],alpha.inputs['Alpha'])
output=n.new('NodeGroupOutput'); links.new(alpha.outputs[0],output.inputs['Image'])
rig = bpy.data.objects.new('TITLE • animated transform',None)
s.collection.objects.link(rig)

def material(name,color):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color,1)
    m.use_nodes = True
    n=m.node_tree.nodes
    n.clear()
    em=n.new('ShaderNodeEmission')
    em.inputs[0].default_value=(*color,1)
    em.inputs[1].default_value=1
    o=n.new('ShaderNodeOutputMaterial')
    m.node_tree.links.new(em.outputs[0],o.inputs['Surface'])
    return m
front = material('Phosphor green • #00FF66',(0,1,.133))
back = material('Depth • dim green',(0,.32,.035))

# Native POLY curves: only visible outline edges, no triangulation diagonals.
strokes=[]
def stroke(name,coords,mat,radius=.012):
    c=bpy.data.curves.new(name,'CURVE'); c.dimensions='3D'
    c.resolution_u=1; c.bevel_depth=radius; c.bevel_resolution=1
    sp=c.splines.new('POLY'); sp.points.add(len(coords)-1)
    for pt,co in zip(sp.points,coords): pt.co=(*co,1)
    o=bpy.data.objects.new(name,c); s.collection.objects.link(o); o.parent=rig
    c.materials.append(mat)
    strokes.append(c)
    return c
loops=json.loads((base/('outlines-tall.json' if a.format=='square' else 'outlines.json')).read_text())
xs=[x for loop in loops for x,y in loop]; ys=[y for loop in loops for x,y in loop]
cx=(min(xs)+max(xs))/2; cy=(min(ys)+max(ys))/2
unit=(max(xs)-min(xs))/11.72
for i,loop in enumerate(loops):
    # Each format retains the exact proportions of its own original bitmap.
    xy=[((x-cx)/unit,(cy-y)/unit) for x,y in loop]
    for z,mat,label in [(0.16,front,'front'),(-.16,back,'rear')]:
        coords=[(x,y,z) for x,y in xy]
        stroke(f'{i:02d} {label} outline',coords+[coords[0]],mat)
    for j,(x,y) in enumerate(xy):
        stroke(f'{i:02d} depth {j:02d}',[(x,y,-.16),(x,y,.16)],back,.006)

# Arc-length write, contour by contour, including actual depth strokes.
if a.treatment=='laser':
    lengths=[]
    for c in strokes:
        points=c.splines[0].points
        lengths.append(sum((points[i].co.xyz-points[i-1].co.xyz).length for i in range(1,len(points))))
    cursor=1
    for c,length in zip(strokes,lengths):
        end=cursor+104*length/sum(lengths)
        c.bevel_factor_end=0; c.keyframe_insert('bevel_factor_end',frame=1)
        c.keyframe_insert('bevel_factor_end',frame=cursor)
        c.bevel_factor_end=1; c.keyframe_insert('bevel_factor_end',frame=end)
        cursor=end
    poses=[(1,(0,0,0),(.12,-.24,-.025)),(110,(0,0,0),(-.08,.12,.012)),(180,(0,0,0),(.12,.38,.025))]
elif a.treatment=='fly':
    poses=[(1,(0,0,-12),(.2,-.6,-.08)),(60,(0,0,-2),(0,0,0)),
           (105,(0,0,1.5),(.12,.3,.05)),(145,(0,0,12),(.5,1.15,.15)),
           (180,(0,0,29),(.8,2.4,.3))]
else:
    # Exact six-second periodic turntable, with frame 181 matching frame 1.
    poses=[(1,(0,0,0),(.13,0,0)),(181,(0,0,0),(.13,math.tau,0))]
for f,loc,rot in poses:
    rig.location=loc; rig.rotation_euler=rot
    rig.keyframe_insert('location',frame=f); rig.keyframe_insert('rotation_euler',frame=f)
# Blender 5 layered action channel bags.
for action in bpy.data.actions:
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    for k in fc.keyframe_points:
                        k.interpolation='LINEAR'
cam_data=bpy.data.cameras.new('Perspective 50mm')
cam=bpy.data.objects.new('Camera',cam_data); s.collection.objects.link(cam)
cam.location=(0,0,21 if a.format=='square' else 20)
cam_data.lens=50
cam_data.clip_start=.05
s.camera=cam
s['description']='Exact bitmap-derived CLOC.KDIVIDER contours, extruded 0.32 units. RGBA transparent.'
s['source']='~/src/blender/laser/clockdivider-long.png (artist-owned 2021 lockup)'
s.frame_set(120)
s.render.filepath=bpy.path.relpath(str(out/'png'/ 'frame_'),start=str(base))
bpy.ops.wm.save_as_mainfile(filepath=str(base/f'{a.treatment}-{a.format}.blend'),compress=True)
if a.frame:
    s.frame_set(a.frame); s.render.filepath=str(out/f'proof-{a.frame:04d}.png')
    bpy.ops.render.render(write_still=True)
elif a.render:
    bpy.ops.render.render(animation=True)
