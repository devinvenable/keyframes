"""T322 draft only: contact, two backward steps, sandstone collision and settle."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys

import bpy
from mathutils import Vector, Quaternion, Matrix, noise
from mathutils.bvhtree import BVHTree

SOURCE = Path('/home/devin/src/2026/videdit/work/kaiju_dive_320_final/dive_contact.blend')
END = 84
HIT = 39


def key(o, path, value, f):
    setattr(o, path, value)
    o.keyframe_insert(data_path=path, frame=f)


def ramp(f, a, b):
    t = min(1, max(0, (f-a)/(b-a)))
    return t*t*(3-2*t)


def curve(f, pairs):
    for (a, x), (b, y) in zip(pairs, pairs[1:]):
        if f <= b:
            return x+(y-x)*ramp(f, a, b)
    return pairs[-1][1]


def actor_state():
    return {o.name: [round(v, 5) for row in o.matrix_world for v in row]
            for o in bpy.context.scene.objects
            if o.name.startswith(('BK |', 'Hatch ', 'Booster '))
            or o.name in ('actor_kaiju_robot', 'kaiju_robot_mesh')}


def stone(name, pos, size, material, rng, subdivisions=2):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subdivisions, radius=1, location=pos)
    o = bpy.context.object; o.name = name
    for v in o.data.vertices:
        v.co *= rng.uniform(.88, 1.10)
    o.scale = size; o.data.materials.append(material)
    return o


def dust_material():
    m = bpy.data.materials.new('Reaction | practical falling powder'); m.use_nodes = True
    n, l = m.node_tree.nodes, m.node_tree.links; n.clear()
    out = n.new('ShaderNodeOutputMaterial'); vol = n.new('ShaderNodeVolumeScatter')
    vol.inputs['Color'].default_value = (.58, .43, .27, 1)
    vol.inputs['Anisotropy'].default_value = .15
    co = n.new('ShaderNodeTexCoord'); tex = n.new('ShaderNodeTexNoise')
    tex.inputs['Scale'].default_value = 8; tex.inputs['Detail'].default_value = 4
    l.new(co.outputs['Generated'], tex.inputs[0])
    fade = n.new('ShaderNodeValToRGB'); fade.color_ramp.elements[0].position = .43
    fade.color_ramp.elements[1].position = .70
    l.new(tex.outputs['Fac'], fade.inputs[0])
    distance = n.new('ShaderNodeVectorMath'); distance.operation = 'DISTANCE'
    distance.inputs[1].default_value = (.5, .5, .5); l.new(co.outputs['Generated'], distance.inputs[0])
    edge = n.new('ShaderNodeMapRange'); edge.inputs['From Min'].default_value = .18
    edge.inputs['From Max'].default_value = .5; edge.inputs['To Min'].default_value = 1
    edge.inputs['To Max'].default_value = 0; l.new(distance.outputs['Value'], edge.inputs[0])
    mult = n.new('ShaderNodeMath'); mult.operation = 'MULTIPLY'
    l.new(edge.outputs[0], mult.inputs[0]); l.new(fade.outputs[0], mult.inputs[1])
    density = n.new('ShaderNodeMath'); density.operation = 'MULTIPLY'
    l.new(mult.outputs[0], density.inputs[0])
    for f, val in [(1, 1.8), (HIT, 1.8), (HIT+8, 1.1), (HIT+22, .2), (END, .015)]:
        density.inputs[1].default_value = val
        density.inputs[1].keyframe_insert(data_path='default_value', frame=f)
    l.new(density.outputs[0], vol.inputs['Density']); l.new(vol.outputs[0], out.inputs['Volume'])
    return m


def effects(world, rng):
    s = bpy.context.scene; s.frame_set(HIT)
    source = bpy.data.objects['model.011_Default OBJ.016_0.001']
    o = source.copy(); o.data = source.data; o.animation_data_clear()
    o.name = 'Reaction | stack | original sandstone instance'; s.collection.objects.link(o)
    o.parent = None; o.matrix_parent_inverse = Matrix.Identity(4)
    # Exact original geometry, UVs, packed PBR material and world scale (9).
    # Only placement/heading change to put the original rock face behind the hit.
    o.matrix_world = Matrix.Translation(world((35,250,-5))) @ Matrix.Rotation(math.radians(50),4,'Z') @ Matrix.Diagonal((9,9,9,1))
    bpy.context.view_layer.update()
    shell = bpy.data.objects['BK | elytron R course 4']
    back = (world((0,1,0))-world((0,0,0))).normalized()
    inverse = o.matrix_world.inverted(); candidates=[]
    for vertex in shell.data.vertices:
        point = shell.matrix_world @ vertex.co
        hit,location,normal,index = o.ray_cast(inverse @ point, inverse.to_3x3() @ back)
        if hit:
            distance = (o.matrix_world @ location-point).dot(back)
            if distance > 0: candidates.append(distance)
    assert candidates, 'No original sandstone surface behind the shoulder'
    o.location -= back*(min(candidates)+.6)
    bpy.context.view_layer.update()
    # Refine against the whole rigid rear shell, not one sampled shoulder ray.
    # The cliff's uneven lower ledges must not bury several shell courses.
    rock_tree=BVHTree.FromPolygons([v.co for v in o.data.vertices],[tuple(p.vertices) for p in o.data.polygons])
    deps=bpy.context.evaluated_depsgraph_get(); shells=[]
    for part in s.objects:
        if part.type=='MESH' and part.name.startswith('BK | elytron'):
            evaluated=part.evaluated_get(deps); mesh=evaluated.to_mesh()
            shells.append(([evaluated.matrix_world @ v.co for v in mesh.vertices],[tuple(p.vertices) for p in mesh.polygons]))
            evaluated.to_mesh_clear()
    base=o.location.copy()
    def overlaps(offset):
        o.location=base+back*offset; bpy.context.view_layer.update()
        inverse=o.matrix_world.inverted()
        return any(rock_tree.overlap(BVHTree.FromPolygons([inverse @ v for v in verts],faces)) for verts,faces in shells)
    assert overlaps(0), 'Sampled face does not touch rear shell'
    upper=1
    while overlaps(upper):
        upper+=1
        assert upper<50, 'Cannot separate original sandstone from beetle'
    lower=upper-1
    for _ in range(12):
        middle=(lower+upper)/2
        if overlaps(middle): lower=middle
        else: upper=middle
    overlaps(lower-.08)
    o['asset_source'] = source.name
    o['asset_contract'] = 'Linked mesh/materials; unchanged original world scale; placement only'
    mat = source.data.materials[0]
    rock = o
    def surface(x,z):
        inverse = rock.matrix_world.inverted()
        hit,location,normal,index = rock.ray_cast(inverse @ world((x,-30,z)), inverse.to_3x3() @ back)
        if not hit:
            hit,location,normal,index = rock.closest_point_on_mesh(inverse @ world((x,70,z)))
        assert hit, f'No rock surface at fragment origin {x}, {z}'
        return rock.matrix_world @ location-back*.4
    # Each fragment begins attached to the near rock face; no spontaneous
    # airborne pebbles. Integrate gravity and damped floor bounces at 24 Hz.
    for i in range(170):
        radius = rng.uniform(.3, 1.1) if i < 145 else rng.uniform(1.2, 3.1)
        origin = surface(rng.uniform(1,35),rng.uniform(25,75))
        o = stone(f'Reaction | fragment {i:03}', origin, (radius, radius*.65, radius*.8), mat, rng, 1)
        fragment_scale = o.scale.copy()
        velocity = Vector((rng.uniform(-38, 44), rng.uniform(-45, -8), rng.uniform(5, 36)))
        velocity = world(velocity)-world((0, 0, 0))
        pos = origin.copy(); birth = HIT+rng.choice([0, 0, 1, 2]); spin = Vector((rng.uniform(-5,5), 3, 4))
        o['birth_frame'] = birth; o['radius'] = radius
        for f in range(1, END+1):
            if f >= birth:
                velocity.z -= 90/24; pos += velocity/24
                if pos.z < radius:
                    pos.z = radius; velocity.z = abs(velocity.z)*.30
                    velocity.x *= .64; velocity.y *= .64
            key(o, 'location', pos, f)
            key(o, 'rotation_euler', spin*max(0, (f-birth)/24), f)
            key(o, 'scale', fragment_scale if f >= birth else (.001,)*3, f)
    powder = dust_material()
    for i in range(26):
        origin = surface(rng.uniform(1,35),rng.uniform(25,64))
        size = rng.uniform(5, 10)
        o = stone(f'Reaction | powder {i:02}', origin, (1,1,1), powder, rng)
        for v in o.data.vertices:
            v.co *= .7+.65*noise.noise_vector(v.co*3+Vector((i*.7,i*.4,i*.3))).x
        velocity = world((rng.uniform(-15, 35), rng.uniform(-28, -7), rng.uniform(-5, 10)))-world((0,0,0))
        birth = HIT+rng.choice([0, 1, 2]); o['birth_frame'] = birth
        for f in range(1, END+1):
            t = max(0, (f-birth)/24)
            pos = origin+velocity*(1-math.exp(-t*1.7))/1.7
            pos.z = max(1.8, origin.z+velocity.z*t-35*t*t)
            grow = .001 if f < birth else .45+1.2*(1-math.exp(-t*5))
            key(o, 'location', pos, f)
            key(o, 'scale', (size*grow, size*grow*.7, size*grow*max(.24, .8-t*.45)), f)


def build(output, camera_mode='low'):
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE)); s = bpy.context.scene; s.frame_set(106)
    before = actor_state()
    source_camera = s.camera; source_camera_matrix = source_camera.matrix_world.copy()
    for image in bpy.data.images:
        if image.filepath: image.filepath = bpy.path.abspath(image.filepath)
    for o in s.objects: o.animation_data_clear()
    controls = {o.name[5:]: o for o in s.objects if o.name.startswith('BK |') and o.type == 'EMPTY'}
    root = controls['ROOT | placement']; station = root.location.copy(); rotation = root.rotation_euler.to_matrix()
    def world(xyz): return station+rotation @ Vector(xyz)
    base_rot = {name: o.rotation_euler.copy() for name, o in controls.items()}
    base_loc = {name: o.location.copy() for name, o in controls.items()}
    soles = {side: bpy.data.objects['BK | sole '+side].matrix_world.translation.copy() for side in ('L','R')}
    ankles = {side: controls['ankle '+side].matrix_world.copy() for side in ('L','R')}
    ankle_offsets = {side: ankles[side].translation-soles[side] for side in ('L','R')}
    ankle_rotations = {side: controls['pelvis'].matrix_world.to_quaternion().inverted() @ ankles[side].to_quaternion() for side in ('L','R')}
    rig = bpy.data.objects['actor_kaiju_robot']; robot_start = rig.location.copy(); robot_q = rig.rotation_quaternion.copy()
    camera = bpy.data.objects.new('Reaction | ground camera', bpy.data.cameras.new('Reaction | 38mm'))
    s.collection.objects.link(camera); s.camera = camera; camera.rotation_mode = 'QUATERNION'
    if camera_mode == 'continuation':
        camera.name = 'Reaction | dive camera continuation'
        camera.data = source_camera.data.copy(); camera.matrix_world = source_camera_matrix
    else:
        camera.data.lens = 32; camera.location = world((157, -142, 4.5))
        target = world((0, 28, 44))
        camera.rotation_quaternion = (target-camera.location).to_track_quat('-Z','Y')
    if camera_mode == 'low': camera.data.clip_end = 50000
    initial_camera_q = camera.rotation_quaternion.copy()
    plume_scales = {o.name:o.scale.copy() for o in s.objects if o.name.startswith('Booster ') and any(label in o.name for label in ('amber exhaust','incandescent core','blue throat jet'))}
    for f in range(1, END+1):
        n = f-1
        transferred = 8*(1-math.exp(-n/2))+1.6*n
        back = transferred if f <= 8 else curve(f, [(8,8*(1-math.exp(-7/2))+1.6*7), (22,24), (HIT,50), (46,47), (END,48)])
        root.location = world((0, back, 0)); key(root, 'location', root.location, f)
        dip = curve(f, [(1,0),(4,-5),(8,-12),(22,-13),(29,-10),(HIT,-3),(48,-5),(END,-1)])
        key(controls['pelvis'], 'location', base_loc['pelvis']+Vector((0,0,dip)), f)
        whip = curve(f, [(1,0),(8,-25),(23,-13),(HIT,-24),(46,9),(59,-5),(END,-2)])
        twist = curve(f, [(1,0),(10,13),(24,-12),(HIT,15),(49,-6),(END,3)])
        def joint(name, delta):
            key(controls[name], 'rotation_euler', tuple(a+math.radians(b) for a,b in zip(base_rot[name],delta)), f)
        joint('waist', (whip, 0, twist)); joint('neck', (-whip*.65, 0, -twist*.7))
        for side, sign in [('L', -1), ('R', 1)]:
            flare = curve(f, [(1,0),(12,1),(26,.65),(HIT,1.15),(52,.45),(END,.18)])
            joint('shoulder '+side, (35*flare, sign*53*flare, sign*18*flare))
            joint('elbow '+side, (45*flare, 0, 0))
            step_a, step_b = (2,18) if side == 'L' else (18,38)
            step = ramp(f, step_a, step_b); distance = 42 if side == 'L' else 55
            lift = 8*math.sin(math.pi*step)
            hip = controls['hip '+side]; hip.location = base_loc['hip '+side]
            bpy.context.view_layer.update()
            if f > 1:
                target_foot = soles[side]+rotation @ Vector((0,distance*step,lift))
                target_ankle = hip.parent.matrix_world.inverted() @ (target_foot+ankle_offsets[side])
                direction = target_ankle-hip.location; length = direction.length
                assert length < 29, f'Unreachable planted ankle: {side} frame {f}: {length}'
                alpha = math.acos(max(-1,min(1,(13*13+length*length-16*16)/(26*length))))
                beta = math.pi-math.acos(max(-1,min(1,(13*13+16*16-length*length)/(2*13*16))))
                qhip = Vector((0,0,-1)).rotation_difference(direction.normalized()) @ Quaternion((1,0,0),-alpha)
                qknee = Quaternion((1,0,0),beta)
                qankle = (qhip @ qknee).inverted() @ ankle_rotations[side]
                for name,q in [('hip '+side,qhip),('knee '+side,qknee),('ankle '+side,qankle)]:
                    key(controls[name], 'rotation_euler', q.to_euler(), f)
            else:
                for name in ('hip '+side,'knee '+side,'ankle '+side):
                    key(controls[name], 'rotation_euler', base_rot[name], f)
        # Incoming forward momentum decelerates into the stagger. The robot
        # glances sideways over the shoulder, then pitches up under thrust.
        forward = 8*(1-math.exp(-n/2))+1.6*n+.065*max(0,n-10)**2
        sideways = 46*ramp(n,1,16)
        upward = -3.2*(1-math.exp(-n/2))+.13*max(0,n-7)**2
        pos = robot_start+rotation @ Vector((sideways,forward,upward))
        key(rig, 'location', pos, f)
        pitch = math.radians(-19+74*ramp(n,6,25))
        heading = rotation @ Vector((.25*ramp(n,1,12),math.cos(pitch),math.sin(pitch)))
        q = robot_q.slerp(heading.to_track_quat('Z','Y'),ramp(n,0,8))
        key(rig, 'rotation_quaternion', q, f)
        for name,scale in plume_scales.items():
            gain=1+.5*ramp(n,8,18)
            key(bpy.data.objects[name],'scale',(scale.x,scale.y,scale.z*gain),f)
        if camera_mode == 'continuation':
            aim = world((0,back,42))-camera.location
            key(camera,'rotation_quaternion',initial_camera_q.slerp(aim.to_track_quat('-Z','Y'),ramp(f,1,28)),f)
    effects(world, random.Random(32260))
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in bag.fcurves:
                        for point in fc.keyframe_points: point.interpolation = 'LINEAR'
    s.frame_start = 1; s.frame_end = END; s.render.fps = 24
    s.cycles.volume_step_rate = 1; s.cycles.volume_max_steps = 256
    s['shot'] = 'T322 staging and draft motion only; final render requires Devin approval'
    s.timeline_markers.clear()
    for name, f in [('Contact / T320 f106',1),('Mid-stagger',22),('Rock collision',HIT),('Settle',END)]:
        s.timeline_markers.new(name, frame=f)
    s.frame_set(1); bpy.context.view_layer.update()
    after = actor_state()
    error = max(abs(a-b) for name in before for a,b in zip(before[name], after[name]))
    assert error < .0001, f'Contact handoff changed: {error}'
    s.frame_set(HIT+4); bpy.context.preferences.filepaths.save_version = 0
    dest = output/'reaction.blend'; bpy.ops.wm.save_as_mainfile(filepath=str(dest))
    (output/'manifest.json').write_text(json.dumps({'source':str(SOURCE),
        'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        'scene_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),
        'contact_transform_max_error':error, 'contact_state':before,
        'frames':END,'fps':24,'rock_contact_frame':HIT,'still_frames':[1,4,8,12,16,20,22,43,84],
        'camera_mode':camera_mode,'source_camera_world':[list(row) for row in source_camera_matrix],
        'final_approved':False}, indent=2)+'\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--camera',choices=['low','continuation'],default='low')
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]); build(a.output,a.camera)
