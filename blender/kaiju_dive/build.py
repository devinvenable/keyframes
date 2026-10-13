"""T317 review: shoulder-mounted flying camera and an articulated beetle reaction.

Build with Blender 5.1 (the inherited actions use layered animation); render
native EXRs and run ../kaiju_arrival/grade.py in Blender 4.1.1.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix, Quaternion, Vector

SOURCE = Path('/home/devin/src/2026/videdit/work/kaiju_arrival_313_take3/B_hold_left_third/hold_B_left_third.blend')
FLIGHT = Path('/home/devin/src/2026/videdit/work/liftoff_305/kaiju_liftoff_cinematic.blend')


def key(obj, path, value, frame):
    setattr(obj, path, value)
    obj.keyframe_insert(data_path=path, frame=frame)


def smooth(a, b, t):
    t = max(0, min(1, (t-a)/(b-a)))
    return t*t*(3-2*t)


def build(output, pose):
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    s = bpy.context.scene
    s.frame_set(86)
    # Freeze the approved landed state before discarding arrival-only effects.
    for image in bpy.data.images:
        if image.filepath:
            image.filepath = bpy.path.abspath(image.filepath)
    for obj in list(s.objects):
        obj.animation_data_clear()
        if obj.name.startswith(('Arrival | powder', 'Arrival | thrown grit')):
            bpy.data.objects.remove(obj, do_unlink=True)
    # Keep the master's reviewed gunmetal face palette on the deployed robot.
    mesh = bpy.data.objects['kaiju_robot_mesh']
    bpy.data.objects.remove(bpy.data.objects['actor_kaiju_robot'], do_unlink=True)
    with bpy.data.libraries.load(str(FLIGHT), link=False) as (src, dst):
        dst.objects = [name for name in src.objects if name in
                       ('actor_kaiju_robot',) or
                       name.startswith(('Booster ', 'Hatch '))]
    imported = [obj for obj in dst.objects if obj]
    for obj in imported:
        if obj.name not in s.objects:
            s.collection.objects.link(obj)
    s.frame_set(217)
    for obj in imported:
        obj.animation_data_clear()
        if obj.type == 'LIGHT':
            obj.data.animation_data_clear()
    rig = bpy.data.objects['actor_kaiju_robot']
    rig.parent = None
    rig.matrix_parent_inverse = Matrix.Identity(4)
    rig.scale = (1.3,)*3
    rig.rotation_mode = 'QUATERNION'
    mesh.parent = rig
    for modifier in mesh.modifiers:
        if modifier.type == 'ARMATURE':
            modifier.object = rig
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    faces = [face for face in bm.faces if all(abs(v.co.y-8.8)<.015 and 36.99<=v.co.z<=53.01 for v in face.verts)]
    assert faces and abs(sum(face.calc_area() for face in faces)-435.2)<.1, 'Expected original closed dorsal bay'
    bmesh.ops.delete(bm, geom=faces, context='FACES')
    bm.to_mesh(mesh.data)
    bm.free()
    for bone in rig.pose.bones:
        bone.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    # Arms are rigid weighted assemblies. Rotate about their actual shoulders,
    # in armature space so the rest-bone orientation cannot invert the gesture.
    for side in ('L', 'R'):
        bone = rig.pose.bones['arm_'+side]
        pivot = bone.head.copy()
        angle = math.radians(172 if pose == 'forward' else -12)
        bone.matrix = Matrix.Translation(pivot) @ Matrix.Rotation(angle, 4, 'X') @ Matrix.Translation(-pivot) @ bone.matrix
        bpy.context.view_layer.update()
    controls = {o.name[5:]: o for o in s.objects if o.name.startswith('BK |') and o.type == 'EMPTY'}
    root = controls['ROOT | placement']
    mark = Vector((-45, 75, 0))
    away = Vector((math.sin(math.radians(50)), -math.cos(math.radians(50)), 0))
    camera = bpy.data.objects.new('Dive | shoulder camera', bpy.data.cameras.new('Dive | 26mm'))
    s.collection.objects.link(camera)
    camera.rotation_mode = 'QUATERNION'
    camera.data.lens = 26
    camera.data.sensor_width = 36
    camera.data.clip_end = 10000
    camera.data.dof.use_dof = False
    s.camera = camera
    # The camera is carried by the robot with a fixed local offset. This is
    # deliberately a close flying viewpoint, not a world-space orbit camera.
    camera.parent = rig
    camera.location = (-42, 65, -65)
    direction = (Vector((22, 0, 135))-camera.location).normalized()
    right = direction.cross(Vector((0, 1, 0))).normalized()
    up = right.cross(direction).normalized()
    camera.rotation_quaternion = Matrix((right, up, -direction)).transposed().to_quaternion()
    # A broad miniature-stage bounce keeps the dorsal armor legible in sky.
    fill = bpy.data.objects.new('Dive | broad sky bounce', bpy.data.lights.new('Dive | broad sky bounce', 'AREA'))
    s.collection.objects.link(fill)
    fill.parent = rig
    fill.location = (-70, 100, 95)
    fill.rotation_euler = (Vector((0, 0, 50))-fill.location).to_track_quat('-Z', 'Y').to_euler()
    fill.data.energy = 180000
    fill.data.shape = 'DISK'
    fill.data.size = 100
    fill.data.color = (.74, .82, 1)
    # Preserve the approved photographic light; a high-altitude camera sees
    # the upper sky, not the HDRI's ground-level photographed treeline.
    nodes, links = s.world.node_tree.nodes, s.world.node_tree.links
    env = next(n for n in nodes if n.type == 'TEX_ENVIRONMENT')
    sky = nodes.new('ShaderNodeTexEnvironment')
    sky.name = 'Dive | upper sky camera background'
    sky.image = env.image
    lift = nodes.new('ShaderNodeVectorMath')
    lift.operation = 'ADD'
    lift.inputs[1].default_value = (0, 0, 1.3)
    links.new(env.inputs['Vector'].links[0].from_socket, lift.inputs[0])
    links.new(lift.outputs[0], sky.inputs[0])
    background = nodes.new('ShaderNodeBackground')
    background.inputs['Strength'].default_value = .3
    links.new(sky.outputs[0], background.inputs['Color'])
    world_output = next(n for n in nodes if n.type == 'OUTPUT_WORLD')
    old = world_output.inputs['Surface'].links[0].from_socket
    ray = nodes.new('ShaderNodeLightPath')
    mix = nodes.new('ShaderNodeMixShader')
    links.new(ray.outputs['Is Camera Ray'], mix.inputs[0])
    links.new(old, mix.inputs[1])
    links.new(background.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], world_output.inputs['Surface'])
    p0 = mark + away*850 + Vector((0, 0, 650))
    p1 = mark + away*680 + Vector((0, 0, 825))
    p2 = mark + away*330 + Vector((0, 0, 155))
    p3 = mark + away*155 + Vector((0, 0, 98))

    def joint(name, xyz, frame):
        key(controls[name], 'rotation_euler', tuple(math.radians(x) for x in xyz), frame)

    for f in range(1, 97):
        t = (f-1)/95
        pos = (1-t)**3*p0 + 3*(1-t)**2*t*p1 + 3*(1-t)*t*t*p2 + t**3*p3
        pitch = math.radians(45-67*smooth(0, .65, t)+4*smooth(.65, 1, t))
        heading = -away*math.cos(pitch)+Vector((0, 0, math.sin(pitch)))
        q = heading.to_track_quat('Z', 'Y')
        q = q @ Quaternion((0, 0, 1), math.radians(3*math.sin(t*math.pi)))
        key(rig, 'location', pos, f)
        key(rig, 'rotation_quaternion', q, f)
        for side, phase in [('L', 0), ('R', 1.7)]:
            for label in ('amber exhaust', 'incandescent core', 'blue throat jet'):
                plume = bpy.data.objects['Booster '+side+' | '+label]
                flutter = 1+.075*math.sin(f*1.8+phase)+.04*math.sin(f*.53+phase)
                key(plume, 'scale', (1, 1, flutter), f)
        notice = smooth(.25, .73, t)
        brace = smooth(.63, 1, t)
        breath = math.sin(t*math.pi*3)
        joint('waist', (4-17*notice+7*brace, 3*notice-7*brace, -8+19*notice-9*brace), f)
        joint('neck', (-2-20*notice+5*brace, 0, 22-39*notice+12*brace), f)
        key(controls['pelvis'], 'location', (3.2*notice-5*brace, 0, 34.15+2.4*notice-3.5*brace+.35*breath), f)
        for side, sign in [('L', -1), ('R', 1)]:
            crouch = 15-3*notice+7*brace+sign*2.5*notice
            joint('hip '+side, (-crouch, 0, sign*2*brace), f)
            joint('knee '+side, (2*crouch, 0, 0), f)
            joint('ankle '+side, (-crouch, 0, -sign*2*brace), f)
            joint('shoulder '+side, ((-40 if side == 'L' else -15)-24*notice-15*brace, sign*(18+5*brace), sign*12), f)
            joint('elbow '+side, ((-45 if side == 'L' else -75)-12*brace, 0, 0), f)
        # Lock each ankle pivot to its original ground station by compensating
        # the hip translation. Hinged legs can bend without skating the feet.
        root.location = mark
        for side in ('L', 'R'):
            hip = controls['hip '+side]
            hip.location = ((-13 if side == 'L' else 13), 0, -1)
        bpy.context.view_layer.update()
        for side in ('L', 'R'):
            sole = bpy.data.objects['BK | sole '+side]
            hip = controls['hip '+side]
            foot_target = root.matrix_world @ Vector(((-13 if side == 'L' else 13), -3.88, 0))
            current = sole.matrix_world.translation.copy()
            floor = min((sole.matrix_world @ Vector(c)).z for c in sole.bound_box)
            delta = Vector((foot_target.x-current.x, foot_target.y-current.y, -floor))
            hip.location += hip.parent.matrix_world.inverted().to_3x3() @ delta
            key(hip, 'location', hip.location.copy(), f)
        key(root, 'location', root.location.copy(), f)

    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for point in curve.keyframe_points:
                            point.interpolation = 'LINEAR'
    s.frame_start, s.frame_end = 1, 96
    s.render.fps = 24
    s.render.resolution_x, s.render.resolution_y = 1920, 1080
    s.render.resolution_percentage = 100
    s.render.use_compositing = False
    s.render.engine = 'CYCLES'
    s.cycles.samples = 64
    s.cycles.use_denoising = True
    s.cycles.use_adaptive_sampling = True
    s.cycles.adaptive_threshold = .08
    s.cycles.volume_step_rate = 2
    s.cycles.volume_max_steps = 128
    s.render.image_settings.file_format = 'OPEN_EXR'
    s.view_settings.view_transform = 'AgX'
    s.view_settings.look = 'None'
    s.view_settings.exposure = -.8
    s.timeline_markers.clear()
    for label, f in [('Sky / full thrust', 1), ('Dive / ground reveal', 36), ('Beetle notices', 64), ('Brace / pre-impact endpoint', 96)]:
        s.timeline_markers.new(label, frame=f)
    s['shot'] = 'T317 preview only; pose and framing pending Devin review; no final render approval'
    s['arm_pose'] = pose
    s['grade'] = 'Native linear EXR -> pinned kaiju_1960s in Blender 4.1.1 -> AgX, exposure -0.8'
    bpy.context.preferences.filepaths.save_version = 0
    s.frame_set(96)
    bpy.ops.file.pack_all()
    path = output / ('dive_'+pose+'.blend')
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    manifest = {'pose': pose, 'frames': [1,96], 'fps': 24, 'review_only': True,
                'sources': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (SOURCE, FLIGHT)},
                'scene': str(path), 'camera_local': list(camera.location),
                'motion': 'Head-first cubic descent; fixed shoulder camera; articulated notice/brace with planted feet.'}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pose', choices=['forward', 'swept'], required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    build(args.output.resolve(), args.pose)
