"""Compare saved dive hardware with deployed T305 and inventory robot skinning.

Run in Blender 5.1. No source scene is saved or modified on disk.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

FLIGHT = Path('/home/devin/src/2026/videdit/work/liftoff_305/kaiju_liftoff_cinematic.blend')
MASTER = Path('/home/devin/src/2026/videdit/work/kaiju_arrival_313_take3/B_hold_left_third/hold_B_left_third.blend')
ROUND = Path('/home/devin/src/2026/videdit/work/kaiju_dive_317/round_03')


def hardware():
    return {o.name: o for o in bpy.context.scene.objects if o.name.startswith(('Hatch ', 'Booster '))}


def matrix(o):
    return bpy.data.objects['actor_kaiju_robot'].matrix_world.inverted() @ o.matrix_world


def flat(m):
    return [v for row in m for v in row]


def delta(a, b):
    return max(abs(x-y) for x, y in zip(a, b))


def geometry(o):
    if o.type != 'MESH':
        return None
    return {'vertices': [list(v.co) for v in o.data.vertices],
            'faces': [list(p.vertices) for p in o.data.polygons]}


def skin(mesh):
    groups = {g.index: g.name for g in mesh.vertex_groups}
    return [[(groups[g.group], round(g.weight, 6)) for g in v.groups] for v in mesh.data.vertices]


def check_transforms(reference):
    objects = hardware()
    assert set(objects) == set(reference), 'Hardware inventory differs from T305'
    errors = {}
    for name, o in objects.items():
        # Exhaust flutter intentionally changes scale; compare its attachment,
        # position and rotation separately from its varying length.
        if any(label in name for label in ('amber exhaust', 'incandescent core', 'blue throat jet')):
            value = list(o.location) + list(o.rotation_euler)
            error = delta(value, reference[name]['local_position_rotation'])
        else:
            error = delta(flat(matrix(o)), reference[name]['rig_matrix'])
        assert error < 0.0002, f'Incorrect deployed transform: {name} ({error})'
        errors[name] = error
    return max(errors.values())


def main(out, negative):
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(FLIGHT))
    bpy.context.scene.frame_set(217)
    reference = {n: {'rig_matrix': flat(matrix(o)), 'geometry': geometry(o),
                     'parent': o.parent.name if o.parent else None,
                     'local_position_rotation': list(o.location) + list(o.rotation_euler)}
                 for n, o in hardware().items()}
    hinges = {n: list(o.rotation_euler) for n, o in hardware().items() if 'rear hinge' in n}
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    original = bpy.data.objects['kaiju_robot_mesh']
    master_vertices = [list(v.co) for v in original.data.vertices]
    master_skin = skin(original)
    master_faces = {tuple(p.vertices) for p in original.data.polygons}
    dorsal_faces = {tuple(p.vertices) for p in original.data.polygons
                    if all(abs(original.data.vertices[i].co.y-8.8) < .015
                           and 36.99 <= original.data.vertices[i].co.z <= 53.01 for i in p.vertices)}
    report = {'source_hinge_euler_radians': hinges, 'poses': {}, 'sources': {}}
    for path in (FLIGHT, MASTER, *(ROUND/p/f'dive_{p}.blend' for p in ('forward', 'swept'))):
        report['sources'][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    for pose in ('forward', 'swept'):
        bpy.ops.wm.open_mainfile(filepath=str(ROUND/pose/f'dive_{pose}.blend'))
        s = bpy.context.scene
        mesh = bpy.data.objects['kaiju_robot_mesh']
        assert [list(v.co) for v in mesh.data.vertices] == master_vertices, 'Native vertex geometry changed'
        assert skin(mesh) == master_skin, 'Native skin weights changed'
        assert {tuple(p.vertices) for p in mesh.data.polygons} == master_faces-dorsal_faces, 'Expected only dorsal face removal'
        rig = bpy.data.objects['actor_kaiju_robot']
        assert mesh.parent == rig
        assert all(m.object == rig for m in mesh.modifiers if m.type == 'ARMATURE')
        unweighted = [v.index for v in mesh.data.vertices if not any(g.weight > 0 and mesh.vertex_groups[g.group].name in rig.pose.bones for g in v.groups)]
        assert not unweighted, f'Unposed native vertices: {unweighted}'
        for name, o in hardware().items():
            assert geometry(o) == reference[name]['geometry'], f'Geometry changed: {name}'
            assert (o.parent.name if o.parent else None) == reference[name]['parent'], f'Parent changed: {name}'
        errors = []
        for frame in range(1, 97):
            s.frame_set(frame)
            errors.append(check_transforms(reference))
        s.frame_set(64)
        # Enumerate every visible mesh beyond the set and beetle; unknown items
        # remain explicit in the report rather than silently assuming attachment.
        inventory = []
        for o in s.objects:
            if o.type == 'MESH' and not o.hide_render:
                parent = o.parent
                attached = o == mesh
                while parent:
                    attached |= parent == rig
                    parent = parent.parent
                inventory.append({'name': o.name, 'robot_attached': attached,
                                  'parent': o.parent.name if o.parent else None})
        projected = {}
        for side in ('L', 'R'):
            name = f'Hatch {side} | original armor'
            o = bpy.data.objects[name]
            coords = [world_to_camera_view(s, s.camera, o.matrix_world @ Vector(v)) for v in o.bound_box]
            projected[name] = {'bbox_960x540': [min(c.x for c in coords)*960, (1-max(c.y for c in coords))*540,
                                              max(c.x for c in coords)*960, (1-min(c.y for c in coords))*540]}
        # Ray hits independently identify the rendered silhouettes, including
        # the narrow edge and bolts, in the rear shoulder region.
        deps = bpy.context.evaluated_depsgraph_get()
        corners = s.camera.data.view_frame(scene=s)
        left, right = min(v.x for v in corners), max(v.x for v in corners)
        bottom, top = min(v.y for v in corners), max(v.y for v in corners)
        hits = {}
        for y in range(270, 485):
            for x in range(280, 610):
                direction = Vector((left+(right-left)*(x+.5)/960,
                                    top-(top-bottom)*(y+.5)/540, corners[0].z))
                direction = (s.camera.matrix_world.to_3x3() @ direction).normalized()
                hit, loc, normal, idx, obj, mat = s.ray_cast(deps, s.camera.matrix_world.translation, direction)
                if hit and obj.name.startswith(('Hatch ', 'Booster ')):
                    hits.setdefault(obj.name, []).append([x, y])
        for name in projected:
            pixels = hits.get(name, [])
            projected[name]['ray_hit_count'] = len(pixels)
            projected[name]['ray_hit_example'] = pixels[len(pixels)//2] if pixels else None
        (out/f'{pose}_hardware_pixels.json').write_text(json.dumps(hits))
        result = {'frames_checked': 96, 'max_rig_matrix_error': max(errors),
                  'hardware_objects': len(reference), 'unweighted_vertices': unweighted,
                  'native_vertices': len(master_vertices), 'dorsal_faces_removed': len(dorsal_faces), 'native_weights_match_master': True,
                  'visible_mesh_inventory': inventory, 'hatches': projected}
        if negative:
            hinge = bpy.data.objects['Hatch R | rear hinge']
            backup = hinge.rotation_euler.copy()
            hinge.rotation_euler.z += .1
            bpy.context.view_layer.update()
            try:
                check_transforms(reference)
            except AssertionError as e:
                assert 'Incorrect deployed transform:' in str(e)
                result['negative_hinge'] = str(e)
            else:
                raise AssertionError('Hinge negative control did not fail')
            finally:
                hinge.rotation_euler = backup
                bpy.context.view_layer.update()
            check_transforms(reference)
        report['poses'][pose] = result
    report['status'] = 'PASS'
    (out/'geometry_audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print('GEOMETRY_AUDIT PASS', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--negative-checks', action='store_true')
    a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    main(a.output, a.negative_checks)
