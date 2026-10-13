"""T320: seamless distant terrain and continuation to the first contact instant.

Run in Blender 5.1.2, with the approved swept-arm source loaded. Original
animation through frame 96 is retained. The world and grade are untouched.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector, noise
from mathutils.bvhtree import BVHTree


def fingerprint():
    """Evaluated transforms of every original actor/camera over the approved arc."""
    s = bpy.context.scene
    objects = sorted((o for o in s.objects if o.name.startswith(('BK |', 'Hatch ', 'Booster ', 'Dive |'))
                      or o.name in ('actor_kaiju_robot', 'kaiju_robot_mesh')), key=lambda o: o.name)
    result = []
    for frame in range(1, 97):
        s.frame_set(frame)
        result.append([[o.name, [round(v, 5) for row in o.matrix_world for v in row]] for o in objects])
    return hashlib.sha256(json.dumps(result).encode()).hexdigest()


def terrain():
    s = bpy.context.scene
    ground = bpy.data.objects['GroundPlane']
    material = ground.data.materials[0]
    # A continuous disk has no square corners. Keep the original UV scale and
    # flat central stage; relief only begins outside the action/set dressing.
    count = 256
    radii = [0] + list(range(100, 4001, 100)) + list(range(4200, 12001, 200)) + [16000, 24000, 40000]
    verts = [(0, 0, 0)]
    for radius in radii[1:]:
        for i in range(count):
            angle = 2*math.pi*i/count
            x, y = radius*math.cos(angle), radius*math.sin(angle)
            fade = min(1, max(0, (radius-1500)/1300))
            fade = fade*fade*(3-2*fade)
            z = fade*(100 + 170*noise.fractal(Vector((x/1400, y/1400, .73)), 1, 2, 4))
            verts.append((x, y, z))
    faces = [(0, 1+i, 1+(i+1)%count) for i in range(count)]
    for ring in range(len(radii)-2):
        a, b = 1+ring*count, 1+(ring+1)*count
        faces.extend((a+i, b+i, b+(i+1)%count, a+(i+1)%count) for i in range(count))
    mesh = bpy.data.meshes.new('T320 | continuous miniature terrain')
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(material)
    uv = mesh.uv_layers.new(name='UVMap')
    for poly in mesh.polygons:
        poly.use_smooth = True
        for li in poly.loop_indices:
            x, y, _ = verts[mesh.loops[li].vertex_index]
            uv.data[li].uv = ((x+3000)/600, (y+3000)/600)
    ground.data = mesh

    # Distant painted haze samples exactly the same camera-ray HDRI as the
    # untouched world. No global fog, lighting or compositor changes.
    nodes, links = material.node_tree.nodes, material.node_tree.links
    output = next(n for n in nodes if n.type == 'OUTPUT_MATERIAL')
    surface = output.inputs['Surface'].links[0].from_socket
    geometry = nodes.new('ShaderNodeNewGeometry')
    incoming = nodes.new('ShaderNodeVectorMath'); incoming.operation = 'SCALE'
    incoming.inputs[3].default_value = -1
    links.new(geometry.outputs['Incoming'], incoming.inputs[0])
    world = s.world.node_tree.nodes
    original_mapping = next(n for n in world if n.type == 'MAPPING')
    mapping = nodes.new('ShaderNodeMapping'); mapping.vector_type = original_mapping.vector_type
    for name in ('Location', 'Rotation', 'Scale'):
        mapping.inputs[name].default_value = original_mapping.inputs[name].default_value
    links.new(incoming.outputs[0], mapping.inputs['Vector'])
    lift = nodes.new('ShaderNodeVectorMath'); lift.operation = 'ADD'
    lift.inputs[1].default_value = (0, 0, 1.3)
    links.new(mapping.outputs[0], lift.inputs[0])
    sky = nodes.new('ShaderNodeTexEnvironment')
    sky.image = world['Dive | upper sky camera background'].image
    links.new(lift.outputs[0], sky.inputs[0])
    emission = nodes.new('ShaderNodeEmission'); emission.inputs['Strength'].default_value = .3
    links.new(sky.outputs[0], emission.inputs['Color'])
    camera = nodes.new('ShaderNodeCameraData')
    haze = nodes.new('ShaderNodeMapRange'); haze.interpolation_type = 'SMOOTHERSTEP'
    haze.inputs['From Min'].default_value = 1800
    haze.inputs['From Max'].default_value = 8500
    links.new(camera.outputs['View Distance'], haze.inputs['Value'])
    ray = nodes.new('ShaderNodeLightPath')
    factor = nodes.new('ShaderNodeMath'); factor.operation = 'MULTIPLY'
    links.new(haze.outputs[0], factor.inputs[0]); links.new(ray.outputs['Is Camera Ray'], factor.inputs[1])
    mix = nodes.new('ShaderNodeMixShader')
    links.new(factor.outputs[0], mix.inputs[0]); links.new(surface, mix.inputs[1])
    links.new(emission.outputs[0], mix.inputs[2]); links.new(mix.outputs[0], output.inputs['Surface'])


def key(obj, path, value, frame):
    setattr(obj, path, value)
    obj.keyframe_insert(data_path=path, frame=frame)


def tree(obj, deps):
    evaluated = obj.evaluated_get(deps)
    mesh = evaluated.to_mesh()
    result = BVHTree.FromPolygons([evaluated.matrix_world @ v.co for v in mesh.vertices],
                                 [tuple(p.vertices) for p in mesh.polygons])
    evaluated.to_mesh_clear()
    return result


def contact_pairs():
    deps = bpy.context.evaluated_depsgraph_get()
    robot = tree(bpy.data.objects['kaiju_robot_mesh'], deps)
    return [o.name for o in bpy.context.scene.objects if o.type == 'MESH'
            and o.name.startswith('BK |') and not o.hide_render and robot.overlap(tree(o, deps))]


def extend():
    s = bpy.context.scene
    rig = bpy.data.objects['actor_kaiju_robot']
    s.frame_set(95); previous = rig.location.copy()
    s.frame_set(96); origin = rig.location.copy(); velocity = origin-previous
    controls = {name: bpy.data.objects['BK | '+name] for name in ('waist', 'neck', 'shoulder L', 'shoulder R', 'elbow L', 'elbow R')}
    starts = {name: obj.rotation_euler.copy() for name, obj in controls.items()}
    # Continuing anticipation only: no recoil, impact response or foot motion.
    rates = {'waist': (-.35, .12, .08), 'neck': (.2, 0, -.4),
             'shoulder L': (-.55, .1, 0), 'shoulder R': (-.4, -.1, 0),
             'elbow L': (-.4, 0, 0), 'elbow R': (-.3, 0, 0)}

    def pose(t, frame=None):
        rig.location = origin+velocity*t
        for name, obj in controls.items():
            obj.rotation_euler = tuple(starts[name][i]+math.radians(rates[name][i])*t for i in range(3))
        if frame is not None:
            rig.keyframe_insert(data_path='location', frame=frame)
            for obj in controls.values():
                obj.keyframe_insert(data_path='rotation_euler', frame=frame)
            for side, phase in [('L', 0), ('R', 1.7)]:
                for label in ('amber exhaust', 'incandescent core', 'blue throat jet'):
                    plume = bpy.data.objects['Booster '+side+' | '+label]
                    flutter = 1+.075*math.sin(frame*1.8+phase)+.04*math.sin(frame*.53+phase)
                    key(plume, 'scale', (1, 1, flutter), frame)
        bpy.context.view_layer.update()

    assert not contact_pairs(), 'Approved endpoint already intersects beetle'
    # Quarter-frame search prevents skipping a thin horn/guard contact.
    for step in range(1, 241):
        time = step/4
        pose(time)
        if contact_pairs():
            lo, hi = time-.25, time
            break
    else:
        raise AssertionError('Continuation misses beetle; revise trajectory')
    for _ in range(18):
        mid = (lo+hi)/2; pose(mid)
        if contact_pairs(): hi = mid
        else: lo = mid
    pose(hi); touched = contact_pairs()
    # First intersecting position within 0.000006 world units of contact.
    duration = hi
    extra = math.ceil(duration)
    # Spread a fractional last step evenly: constant velocity, <1 frame timing
    # quantization, and no slow final frame or post-impact penetration.
    for f in range(97, 97+extra):
        pose(duration*(f-96)/extra, f)
    s.frame_end = 96+extra
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for point in curve.keyframe_points:
                            if point.co.x > 96: point.interpolation = 'LINEAR'
    s.frame_set(s.frame_end)
    return {'end_frame': s.frame_end, 'contact_time_after_96': duration,
            'contact_objects': touched, 'velocity_before': list(velocity),
            'velocity_after': list(velocity*(duration/extra)), 'contact_bracket_world_units': (hi-lo)*velocity.length}


def main():
    p = argparse.ArgumentParser(); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(sys.argv[sys.argv.index('--')+1:]); a.output.mkdir(parents=True, exist_ok=True)
    source = Path(bpy.data.filepath)
    report = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    report['original_motion_before'] = fingerprint()
    terrain()
    report['continuation'] = extend()
    report['original_motion_after'] = fingerprint()
    assert report['original_motion_before'] == report['original_motion_after'], 'Original motion changed'
    s = bpy.context.scene; s.frame_set(s.frame_end)
    s['shot'] = 'T320 first-contact endpoint candidate; short still gate required before final'
    s['terrain_fix'] = 'Continuous UV-preserving relief disk; camera-only distance haze matches existing upper sky'
    bpy.context.preferences.filepaths.save_version = 0
    path = a.output/'dive_contact.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    report['scene_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (a.output/'scene_manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    print('CONTACT_SCENE', json.dumps(report), flush=True)


if __name__ == '__main__': main()
