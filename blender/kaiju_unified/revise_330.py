"""Center the strike on a broad sandstone face and frame the head/torso tightly."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
from revise_328 import geometry, key, smooth


def revise(source, performance, output):
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(performance))
    s = bpy.context.scene
    root = bpy.data.objects['BK | ROOT | placement']
    original = {}
    for f in range(106, 193):
        s.frame_set(f); original[f] = root.location.copy()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    s = bpy.context.scene; root = bpy.data.objects['BK | ROOT | placement']
    rotation = root.rotation_euler.to_matrix(); inverse = rotation.transposed()
    back = rotation @ Vector((0, 1, 0))
    beetle = [o for o in s.objects if o.type == 'MESH' and o.name.startswith('BK |')]
    stack = next(o for o in s.objects if o.name.startswith('Reaction | stack'))
    # Keep UVs/materials and the stratified silhouette. Broaden the formation and
    # reduce its projecting lower ledges; a raked face receives the rear torso.
    s.frame_set(124)
    points = [inverse @ (stack.matrix_world @ v.co-original[124]) for v in stack.data.vertices]
    low = Vector(tuple(min(v[i] for v in points) for i in range(3)))
    high = Vector(tuple(max(v[i] for v in points) for i in range(3)))
    stack.data = stack.data.copy(); stack.matrix_world = Matrix.Identity(4)
    for vertex, point in zip(stack.data.vertices, points):
        x = (point.x-low.x)/(high.x-low.x)*240-120
        z = (point.z-low.z)/(high.z-low.z)*175-35
        y = 20 + (point.y-low.y)/(high.y-low.y)*18 + .55*max(0,z-45)
        vertex.co = original[124] + rotation @ Vector((x, y, z))
    stack['asset_contract'] = 'T330 broad raked sandstone face; original UVs and materials retained'
    stack['centered_face_revision'] = True
    # Existing background rocks stay part of the fixed set, behind the new face.
    for o in s.objects:
        if o.type == 'MESH' and o.name.startswith('model.'):
            o.location += back*180
    bpy.context.view_layer.update()

    def cliff_tree():
        vertices, faces = geometry([stack])
        return BVHTree.FromPolygons(vertices, faces)

    def clearance(cliff):
        vertices, faces = geometry(beetle)
        shift = -100.
        for v in vertices:
            hit, _, _, _ = cliff.ray_cast(v-back*600, back, 1200)
            if hit is not None: shift = max(shift, (v-hit).dot(back)+.3)
        while cliff.overlap(BVHTree.FromPolygons([v-back*shift for v in vertices], faces)):
            shift += .1
            assert shift < 100, 'Cannot separate full beetle mesh from face'
        return shift

    # Position the face against the centered, original strike location. The
    # beetle never takes the previous 26-unit lateral detour.
    key(root, 'location', original[124], 124); bpy.context.view_layer.update()
    shift = clearance(cliff_tree())
    stack.location += back*shift; bpy.context.view_layer.update()
    cliff = cliff_tree(); corrections = {}
    for f in range(124, 193):
        s.frame_set(f); root.location = original[f]; bpy.context.view_layer.update()
        shift = clearance(cliff)
        key(root, 'location', original[f]-back*shift, f)
        corrections[f] = shift
    s.frame_set(124); strike = root.location.copy()
    for f in range(113, 124):
        key(root, 'location', original[112].lerp(strike, (f-112)/12), f)

    # Redistribute the same effects across both shoulders on the new rock face.
    for i, o in enumerate(o for o in s.objects if o.name.startswith(('Reaction | fragment', 'Reaction | powder'))):
        s.frame_set(124); old = o.location.copy()
        x = (-1 if i % 2 else 1)*(20+(i%13)*1.5)
        z = 44+(i%17)*2.1
        origin = original[124]+rotation @ Vector((x,-100,z))
        hit, _, _, _ = cliff.ray_cast(origin, back, 600)
        assert hit is not None, 'Effect origin misses sandstone'
        delta = hit-back*.8-old
        for layer in o.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in bag.fcurves:
                        if fc.data_path == 'location':
                            for k in fc.keyframe_points:
                                k.co.y += delta[fc.array_index]

    camera = s.camera; old = {}
    for f in range(1, 193):
        s.frame_set(f); old[f] = (camera.location.copy(), camera.rotation_quaternion.copy(), camera.data.lens)
    s.frame_set(106); camera.data.lens = 42
    direction = (rotation @ Vector((.4, -1, .20))).normalized()
    distance, aim_height = 80., 75.
    for _ in range(40):
        camera.location = root.location+direction*distance+Vector((0,0,90))
        camera.rotation_quaternion = (root.location+Vector((0,0,aim_height))-camera.location).to_track_quat('-Z','Y')
        bpy.context.view_layer.update()
        projected = [world_to_camera_view(s,camera,v) for v in geometry(beetle)[0]]
        y0,y1 = min(v.y for v in projected),max(v.y for v in projected)
        distance *= ((y1-y0)/2.25)**.6
        aim_height += ((y0+y1)/2+.205)*15
    offset = camera.location-root.location; follow_q = camera.rotation_quaternion.copy()
    for f in range(1,193):
        s.frame_set(f); follow = root.location+offset
        if f < 106:
            t = smooth((f-88)/18)
            pos = old[f][0].lerp(follow,t); q = old[f][1].slerp(follow_q,t); lens = old[f][2]+(42-old[f][2])*t
        elif f <=124:
            pos,q,lens = follow,follow_q,42
        else:
            t = smooth((f-124)/30)
            wide = root.location+direction*280+Vector((0,0,30))
            wide_q = (root.location+Vector((0,0,42))-wide).to_track_quat('-Z','Y')
            pos,q,lens = follow.lerp(wide,t),follow_q.slerp(wide_q,t),42
        key(camera,'location',pos,f); key(camera,'rotation_quaternion',q,f); key(camera.data,'lens',lens,f)
    for owner in (root,camera,camera.data):
        for layer in owner.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in bag.fcurves:
                        for k in fc.keyframe_points: k.interpolation='LINEAR'
    camera.name = 'Unified | head torso fly-with centered rock smash'
    s['shot'] = 'T330 round_06 centered torso smash; tight fly-with; draft gate pending'
    s.frame_set(124); bpy.context.preferences.filepaths.save_version=0
    dest=output/'unified.blend'; bpy.ops.wm.save_as_mainfile(filepath=str(dest))
    manifest=json.loads((source.parent/'manifest.json').read_text())
    manifest.update(revision_source=str(source), revision_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    performance_source=str(performance), scene_sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
                    outside_correction_by_frame=corrections, camera_follow_offset=list(offset), revision=330, final_approved=False)
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('CENTERED_REVISION',json.dumps({'corrections':corrections,'follow_offset':list(offset)}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--source',type=Path,required=True)
    p.add_argument('--performance',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]); revise(a.source,a.performance,a.output)
