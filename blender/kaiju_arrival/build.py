"""Bake a rigid suit-monster arrival shot from the approved T307 scene (Blender 5.1)."""
import argparse
import json
import math
import random
import sys
from pathlib import Path
import bpy
from mathutils import Vector

p=argparse.ArgumentParser()
p.add_argument('--source',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
assert a.source.resolve().parent != a.output.resolve(), 'Use a new output directory'
a.output.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(a.source.resolve()))
s=bpy.context.scene
s.frame_set(1)
for im in bpy.data.images:
    if im.filepath: im.filepath=bpy.path.abspath(im.filepath)
for o in s.objects: o.animation_data_clear()
# Remove unrelated village from THIS derivative, including detached imported pieces.
keep={'GroundPlane','FogVolume','actor_kaiju_robot','kaiju_robot_mesh','SceneCamera','CameraTarget',
      'prop_mountain_left','prop_mountain_right','model.011_Default OBJ.016_0','model.011_Default OBJ.016_0.001'}
for o in list(s.objects):
    if o.name not in keep and not o.name.startswith(('BK |','BK shot |','scatter_pebble_')):
        bpy.data.objects.remove(o,do_unlink=True)
# Photograph another arrangement of the same miniature sandstone kit.
bpy.data.objects['prop_mountain_left'].location=(-200,235,-5)
bpy.data.objects['prop_mountain_left'].rotation_euler.z=math.radians(35)
bpy.data.objects['prop_mountain_right'].location=(185,260,-5)
bpy.data.objects['prop_mountain_right'].rotation_euler.z=math.radians(-65)
# Distant kit extensions break the empty horizon while retaining painted-set scale.
for i,(loc,scale,angle) in enumerate([((-490,520,-12),1.9,110),((-75,640,-18),2.3,160),((390,580,-10),1.8,240)]):
    src=bpy.data.objects['model.011_Default OBJ.016_0']
    o=src.copy();o.data=src.data;o.parent=None;s.collection.objects.link(o)
    o.name=f'Arrival | distant sandstone {i}';o.location=loc;o.scale=(12*scale,)*3
    o.rotation_euler=(0,0,math.radians(angle))
scatter_rng=random.Random(1311)
for i in range(140):
    src=bpy.data.objects[f'scatter_pebble_{i%100}'];o=src.copy();o.data=src.data
    s.collection.objects.link(o);o.name=f'Arrival | ground grit {i}'
    o.location=(scatter_rng.uniform(-250,250),scatter_rng.uniform(-180,240),0)
    o.scale*=scatter_rng.uniform(.7,2.4)
rig=bpy.data.objects['actor_kaiju_robot'];rig.location=(80,180,.15)
rig.rotation_euler=(0,0,math.radians(-40))
bpy.data.objects['BK shot | charged plasma blue'].location=(95,125,40)
bpy.data.objects['BK shot | charged plasma blue'].data.energy=13000
# Lower the ambient blanket so the foot contacts and thrown grit can be judged.
fog=bpy.data.materials['FogMaterial'].node_tree.nodes['Math.001']
fog.inputs[1].default_value=.0015
root=bpy.data.objects['BK | ROOT | placement']
controls={o.name[5:]:o for o in s.objects if o.name.startswith('BK |') and o.type=='EMPTY'}
for name,o in controls.items():
    if name not in {'drill spindle','ROOT | placement'}:o.rotation_euler=(0,0,0)
cam=s.camera;cam.constraints.clear();cam.animation_data_clear();cam.data.animation_data_clear()
cam.location=(130,-340,26);cam.rotation_mode='QUATERNION';cam.data.dof.use_dof=False
cam.data.clip_end=5000

def interp(f,keys):
    if f<=keys[0][0]:return keys[0][1]
    for (f0,v0),(f1,v1) in zip(keys,keys[1:]):
        if f<=f1:
            t=(f-f0)/(f1-f0)
            return v0+(v1-v0)*t
    return keys[-1][1]

def joint(name,xyz):controls[name].rotation_euler=tuple(math.radians(v) for v in xyz)
def key(o,paths,f):
    for path in paths:o.keyframe_insert(data_path=path,frame=f)

# Bake every frame: no sim cache, external drivers, or organic deformation.
for f in range(1,109):
    x=interp(f,[(1,-380),(23,-320),(29,-215),(40,-105),(52,-45),(108,-45)])
    z=interp(f,[(1,0),(23,0),(29,26),(35,40),(40,42),(44,35),(48,21),(51,5),(52,0),(108,0)])
    crouch=interp(f,[(1,12),(25,12),(29,26),(35,30),(40,35),(48,14),(51,7),(54,32),(60,25),(73,15),(108,15)])
    lean=interp(f,[(1,4),(29,13),(40,-7),(48,5),(54,19),(65,8),(80,4),(108,4)])
    root.location=(x,75,z);root.rotation_euler.z=math.radians(50)
    joint('waist',(lean,0,-8));joint('neck',(-lean*.5,0,22))
    for side,sign in [('L',-1),('R',1)]:
        controls['hip '+side].location.x=sign*13
        joint('hip '+side,(-crouch,0,0));joint('knee '+side,(2*crouch,0,0));joint('ankle '+side,(-crouch,0,0))
        shoulder=interp(f,[(1,-15),(29,20),(40,-45),(48,-65),(54,-25),(72,-40 if side=='L' else -15),(108,-40 if side=='L' else -15)])
        joint('shoulder '+side,(shoulder,sign*18,sign*12))
        joint('elbow '+side,(-45 if side=='L' else -75,0,0))
        joint('wrist '+side,(30,0,0))
        for k in range(1,4):joint(f'claw {side}{k}',(-10,0,0))
    bpy.context.view_layer.update()
    soles=[bpy.data.objects['BK | sole '+side] for side in ['L','R']]
    floor=min((o.matrix_world@Vector(c)).z for o in soles for c in o.bound_box)
    root.location.z+=z-floor
    for o in controls.values():key(o,['location','rotation_euler'],f)
    lens=interp(f,[(1,32),(45,32),(48,36),(53,53),(59,70),(63,72),(108,72)])
    track=interp(f,[(1,0),(44,0),(60,1),(108,1)])
    target=Vector((0,108,48)).lerp(Vector((-45,75,46)),track)
    # A short mechanical tripod recoil, not a continuous handheld camera.
    if 52<=f<=61:target.z+=math.sin((f-52)*2.1)*1.3*math.exp(-(f-52)/3)
    cam.rotation_quaternion=(target-cam.location).to_track_quat('-Z','Y')
    cam.data.lens=lens
    key(cam,['rotation_quaternion'],f);key(cam.data,['lens'],f)

rng=random.Random(311)
def dust_material():
    m=bpy.data.materials.new('Arrival | dry earth powder');m.use_nodes=True
    n,l=m.node_tree.nodes,m.node_tree.links;n.clear()
    out=n.new('ShaderNodeOutputMaterial');vol=n.new('ShaderNodeVolumeScatter')
    vol.inputs['Color'].default_value=(.46,.35,.23,1);vol.inputs['Anisotropy'].default_value=.12
    coord=n.new('ShaderNodeTexCoord');dist=n.new('ShaderNodeVectorMath');dist.operation='DISTANCE';dist.inputs[1].default_value=(.5,.5,.5)
    l.new(coord.outputs['Generated'],dist.inputs[0])
    edge=n.new('ShaderNodeMapRange');edge.clamp=True
    edge.inputs['From Min'].default_value=.18;edge.inputs['From Max'].default_value=.5
    edge.inputs['To Min'].default_value=1;edge.inputs['To Max'].default_value=0;l.new(dist.outputs['Value'],edge.inputs[0])
    noise=n.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=7;noise.inputs['Detail'].default_value=2
    l.new(coord.outputs['Generated'],noise.inputs['Vector'])
    mul=n.new('ShaderNodeMath');mul.operation='MULTIPLY';l.new(edge.outputs[0],mul.inputs[0]);l.new(noise.outputs['Fac'],mul.inputs[1])
    den=n.new('ShaderNodeMath');den.operation='MULTIPLY';den.inputs[1].default_value=.24
    l.new(mul.outputs[0],den.inputs[0]);l.new(den.outputs[0],vol.inputs['Density']);l.new(vol.outputs[0],out.inputs['Volume'])
    return m
mat=dust_material()
# Uneven, low powder jets followed by slow spreading puffs.
for i in range(22):
    angle=math.tau*i/22+rng.uniform(-.16,.16);direction=Vector((math.cos(angle),math.sin(angle),0))
    radius=rng.uniform(12,19);speed=rng.uniform(15,35);size=rng.uniform(7,12)
    origin=Vector((-45,75,1))+direction*radius
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1)
    o=bpy.context.object;o.name=f'Arrival | powder {i:02}';o.data.materials.append(mat)
    for f in [1,51,52,55,60,70,86,108]:
        t=max(0,(f-52)/24)
        o.location=origin+direction*(speed*(1-math.exp(-t*1.8)))
        o.location.z=1+min(t*13,9)+i%3
        grow=0.001 if f<52 else interp(f,[(52,.09),(55,.55),(62,1),(86,1.6),(108,1.9)])
        o.scale=(size*grow,size*grow*.9,size*grow*.65)
        key(o,['location','scale'],f)
# Real rigid chunks on ballistic paths, with no luminous explosion.
dirt=bpy.data.materials.new('Arrival | rough flying grit');dirt.diffuse_color=(.13,.085,.045,1);dirt.use_nodes=True
dirt.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=dirt.diffuse_color
dirt.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.95
for i in range(70):
    angle=rng.uniform(0,math.tau);speed=rng.uniform(13,53);vz=rng.uniform(15,42)
    origin=Vector((-45+rng.uniform(-15,15),75+rng.uniform(-13,13),.3))
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,radius=rng.uniform(.25,1.1))
    o=bpy.context.object;o.name=f'Arrival | thrown grit {i:02}';o.data.materials.append(dirt)
    for f in range(1,109):
        t=max(0,(f-52)/24);landing=2*vz/70;u=min(t,landing)
        o.location=origin+Vector((math.cos(angle)*speed*u,math.sin(angle)*speed*u,max(0,vz*u-35*u*u)))
        o.rotation_euler=(u*(i%5),u*3,u*4)
        o.scale=(.001,)*3 if f<52 else (1,.7,.65)
        key(o,['location','rotation_euler','scale'],f)
# Linear baked channels make the impact frame exact and avoid Bezier overshoot.
for action in bpy.data.actions:
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for k in curve.keyframe_points:k.interpolation='LINEAR'
s.frame_start=1;s.frame_end=108;s.render.fps=24
s.render.resolution_x=1280;s.render.resolution_y=720;s.render.resolution_percentage=100
s.render.engine='CYCLES';s.cycles.samples=24;s.cycles.use_denoising=True
s.cycles.use_adaptive_sampling=True;s.cycles.adaptive_threshold=.1
s.cycles.volume_step_rate=2;s.cycles.volume_max_steps=128;s.cycles.volume_bounces=1
s.render.use_compositing=False;s.render.image_settings.file_format='OPEN_EXR'
s.render.image_settings.color_depth='16';s.render.image_settings.color_mode='RGBA'
s.view_settings.view_transform='AgX';s.view_settings.look='None';s.view_settings.exposure=-.8
for name,f in [('Robot establishing',1),('Beetle airborne',40),('Slam contact',52),('Dust burst',58),('Zoom ends',63),('Fighting pose',86)]:s.timeline_markers.new(name,frame=f)
s['source_scene']=str(a.source.resolve());s['shot']='Beetle arrival T311'
s['look']='Render linear EXR then kaiju_1960s compositor in Blender 4.1.1, exposure -0.8'
s.frame_set(86)
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(a.output/'beetle_arrival.blend'))
(a.output/'shot_manifest.json').write_text(json.dumps({'source':str(a.source.resolve()),'fps':24,'frames':108,'impact':52,'zoom':[46,63],'lens_mm':[32,72],'stills':{'robot_establishing':1,'beetle_airborne':40,'slam_contact':52,'dust_burst':58,'fighting_pose':86},'assets':'Existing T307 sandstone, robot, beetle, ground and HDRI; newly authored powder/grit. No downloaded assets.'},indent=2))
print('ARRIVAL_BUILD_COMPLETE',flush=True)
