"""Saved-scene contracts; no changes are saved by this verifier."""
import argparse
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
from mathutils.bvhtree import BVHTree


def tree(o, deps):
    ob = o.evaluated_get(deps); mesh = ob.to_mesh()
    result = BVHTree.FromPolygons([ob.matrix_world @ v.co for v in mesh.vertices],
                                 [tuple(p.vertices) for p in mesh.polygons])
    ob.to_mesh_clear(); return result


def verify(manifest):
    s = bpy.context.scene; s.frame_set(1)
    error = max(abs(v-expected) for name, values in manifest['contact_state'].items()
                for v,expected in zip((v for row in bpy.data.objects[name].matrix_world for v in row),values))
    assert error < .0001, 'Contact pose differs from approved dive'
    root = bpy.data.objects['BK | ROOT | placement']; start = root.location.copy()
    feet = {}; rotations = []; robot_visible = []
    for f in range(1,85):
        s.frame_set(f)
        floor = []
        for side in ('L','R'):
            sole = bpy.data.objects['BK | sole '+side]
            floor.append(min((sole.matrix_world @ Vector(c)).z for c in sole.bound_box))
        assert min(floor) < .15, f'Both feet airborne at {f}'
        assert min(floor) > -.15, f'Foot buried at {f}'
        feet[f] = floor
        rotations.append(bpy.data.objects['BK | waist'].rotation_euler.x)
        rig = bpy.data.objects['kaiju_robot_mesh'].evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = rig.to_mesh()
        points = [world_to_camera_view(s,s.camera,rig.matrix_world @ v.co) for v in mesh.vertices]
        robot_visible.append(any(p.z > 0 and 0 < p.x < 1 and 0 < p.y < 1 for p in points))
        rig.to_mesh_clear()
    assert (root.location-start).length > 40, 'No backward stagger'
    assert max(rotations)-min(rotations) > .45, 'Torso whip missing'
    assert not any(robot_visible[24:]), 'Robot fails to ricochet out of frame'
    assert max(row[0] for row in feet.values()) > 7 and max(row[1] for row in feet.values()) > 7, 'Two steps missing'
    s.frame_set(43)
    deps = bpy.context.evaluated_depsgraph_get()
    rocks = [tree(o,deps) for o in s.objects if o.name.startswith('Reaction | stack')]
    shell = [o for o in s.objects if o.type=='MESH' and o.name.startswith('BK | elytron')]
    contacts = [o.name for o in shell if any(tree(o,deps).overlap(r) for r in rocks)]
    s.frame_set(39)
    deps = bpy.context.evaluated_depsgraph_get()
    rocks = [tree(o,deps) for o in s.objects if o.name.startswith('Reaction | stack')]
    impact_contacts = [o.name for o in shell if any(tree(o,deps).overlap(r) for r in rocks)]
    assert impact_contacts, 'Shell misses rock at impact'
    return {'status':'PASS','contact_max_error':error,'feet_by_frame':feet,
            'robot_visible_by_frame':robot_visible,'rock_contact_objects':impact_contacts,
            'post_contact_objects':contacts}


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--negative-checks',action='store_true')
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]); manifest=json.loads((a.directory/'manifest.json').read_text())
    result=verify(manifest)
    if a.negative_checks:
        root=bpy.data.objects['BK | ROOT | placement']; action=root.animation_data.action; slot=root.animation_data.action_slot
        root.animation_data_clear(); root.location=(-45,75,0)
        try:
            verify(manifest)
        except AssertionError as e:
            result['negative_frozen_stagger']=str(e)
        else: raise AssertionError('Frozen stagger was accepted')
        root.animation_data_create(); root.animation_data.action=action; root.animation_data.action_slot=slot
        verify(manifest)
    (a.directory/'scene_qa.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('feet_by_frame','robot_visible_by_frame')}))
