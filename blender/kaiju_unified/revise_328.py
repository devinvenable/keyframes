"""T328: preserve the approved round_04 performance; solid cliff and fly-with camera."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view


def key(obj, path, value, frame):
    setattr(obj, path, value)
    obj.keyframe_insert(data_path=path, frame=frame)


def smooth(t):
    t = min(1, max(0, t))
    return t*t*(3-2*t)


def geometry(objects):
    deps = bpy.context.evaluated_depsgraph_get()
    vertices, faces = [], []
    for obj in objects:
        evaluated = obj.evaluated_get(deps)
        mesh = evaluated.to_mesh()
        offset = len(vertices)
        vertices.extend(evaluated.matrix_world @ v.co for v in mesh.vertices)
        faces.extend(tuple(offset+i for i in p.vertices) for p in mesh.polygons)
        evaluated.to_mesh_clear()
    return vertices, faces


def revise(source, output):
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    s = bpy.context.scene
    root = bpy.data.objects['BK | ROOT | placement']
    beetle = [o for o in s.objects if o.type == 'MESH' and o.name.startswith('BK |')]
    rocks = [o for o in s.objects if o.type == 'MESH' and (o.name.startswith('Reaction | stack') or o.name.startswith('model.'))]
    back = root.rotation_euler.to_matrix() @ Vector((0, 1, 0))
    side = root.rotation_euler.to_matrix() @ Vector((-26, 0, 0))
    rock_vertices, rock_faces = geometry(rocks)
    cliff = BVHTree.FromPolygons(rock_vertices, rock_faces)
    corrections = {}
    # Cast from safely outside toward the cliff for every evaluated beetle vertex.
    # The first surface gives an outside envelope even for contained parts. Then
    # test full triangles too, so a ledge cannot pass between sampled vertices.
    original_roots = {}
    for f in range(112, 193):
        s.frame_set(f); original_roots[f] = root.location.copy()
    for f in range(124, 193):
        s.frame_set(f)
        verts, faces = geometry(beetle)
        verts = [v+side for v in verts]
        shift = -100.
        for v in verts:
            hit, normal, index, distance = cliff.ray_cast(v-back*600, back, 1200)
            if hit is not None:
                shift = max(shift, (v-hit).dot(back)+.3)
        while cliff.overlap(BVHTree.FromPolygons([v-back*shift for v in verts], faces)):
            shift += .2
            assert shift < 100, 'Unable to clear sandstone'
        key(root, 'location', original_roots[f]+side-back*shift, f)
        corrections[f] = shift

    # The old take's feet already intersected both cliffs at the strike. Route
    # the last twelve airborne frames along the outside edge, at constant speed,
    # reaching the solid face on the same strike frame without a one-frame pop.
    strike = original_roots[124]+side-back*corrections[124]
    for f in range(113, 124):
        key(root, 'location', original_roots[112].lerp(strike, (f-112)/12), f)

    camera = s.camera
    old = {}
    for f in range(1, 193):
        s.frame_set(f)
        old[f] = (camera.location.copy(), camera.rotation_quaternion.copy())
    lens = camera.data.lens
    s.frame_set(106)
    camera.data.lens = 42
    direction = (root.rotation_euler.to_matrix() @ Vector((.45, -1, .52))).normalized()
    # Fit at first contact, then keep the exact world-space offset and orientation
    # through the strike. This reads as a camera flying beside the robot/beetle.
    distance, aim_height = 145., 65.
    for _ in range(25):
        camera.location = root.location+direction*distance
        camera.rotation_quaternion = (root.location+Vector((0, 0, aim_height))-camera.location).to_track_quat('-Z', 'Y')
        bpy.context.view_layer.update()
        verts, _ = geometry(beetle)
        ys = [world_to_camera_view(s, camera, v).y for v in verts]
        height = max(ys)-min(ys)
        distance *= height/1.12
        aim_height += ((min(ys)+max(ys))/2-.40)*95
    offset = camera.location-root.location
    follow_q = camera.rotation_quaternion.copy()
    for f in range(1, 193):
        s.frame_set(f)
        follow_pos = root.location+offset
        if f < 106:
            blend = smooth((f-88)/18)
            pos = old[f][0].lerp(follow_pos, blend)
            q = old[f][1].slerp(follow_q, blend)
            focal = lens+(42-lens)*blend
        elif f <= 124:
            pos, q, focal = follow_pos, follow_q, 42
        else:
            blend = smooth((f-124)/26)
            # Retreat with the falling subject to reveal feet, cliff and ground.
            wide_pos = root.location+direction*280
            wide_q = (root.location+Vector((0, 0, 42))-wide_pos).to_track_quat('-Z', 'Y')
            pos = follow_pos.lerp(wide_pos, blend)
            q = follow_q.slerp(wide_q, blend)
            focal = 42
        key(camera, 'location', pos, f)
        key(camera, 'rotation_quaternion', q, f)
        key(camera.data, 'lens', focal, f)
    for owner in (root, camera, camera.data):
        for layer in owner.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in bag.fcurves:
                        for k in fc.keyframe_points: k.interpolation = 'LINEAR'
    camera.name = 'Unified | close fly-with then slide coverage'
    s['shot'] = 'T328 round_05 solid sandstone slide and close fly-with; draft gate pending'
    s.frame_set(124)
    bpy.context.preferences.filepaths.save_version = 0
    dest = output/'unified.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(dest))
    manifest = json.loads((source.parent/'manifest.json').read_text())
    manifest.update({'revision_source': str(source), 'revision_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                     'scene_sha256': hashlib.sha256(dest.read_bytes()).hexdigest(),
                     'outside_correction_by_frame': corrections, 'camera_follow_offset': list(offset),
                     'camera_follow_quaternion': list(follow_q), 'final_approved': False})
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('REVISED', json.dumps({'corrections': corrections, 'follow_offset': list(offset)}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    revise(a.source, a.output)
