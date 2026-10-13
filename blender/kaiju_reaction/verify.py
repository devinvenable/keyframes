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
    stack=[o for o in s.objects if o.name.startswith('Reaction | stack')]
    assert len(stack)==1 and 'asset_source' in stack[0], 'Collision stack is not the original sandstone asset'
    rock=stack[0]; original=bpy.data.objects[rock['asset_source']]
    assert rock.data==original.data, 'Collision stack mesh/materials are not linked to original'
    assert max(abs(a-b) for a,b in zip(rock.matrix_world.to_scale(),original.matrix_world.to_scale())) < .0001, 'Original sandstone scale changed'
    if manifest.get('camera_mode')=='continuation':
        camera_error=max(abs(v-ref) for row,expected in zip(s.camera.matrix_world,manifest['source_camera_world']) for v,ref in zip(row,expected))
        assert camera_error < .0001, 'Continuation camera does not start at dive endpoint'
        assert abs(s.camera.data.lens-26)<.0001, 'Continuation lens changed'
    root = bpy.data.objects['BK | ROOT | placement']; start = root.location.copy()
    hips = {side:bpy.data.objects['BK | hip '+side].location.copy() for side in ('L','R')}
    feet = {}; rotations = []; robot_visible = []; robot_positions=[]; plume_lengths=[]
    for f in range(1,85):
        s.frame_set(f)
        floor = []
        for side in ('L','R'):
            assert (bpy.data.objects['BK | hip '+side].location-hips[side]).length < .0001, f'Hip socket translates at {f}'
            sole = bpy.data.objects['BK | sole '+side]
            floor.append(min((sole.matrix_world @ Vector(c)).z for c in sole.bound_box))
        assert min(floor) < .15, f'Both feet airborne at {f}'
        assert min(floor) > -.15, f'Foot buried at {f}'
        feet[f] = floor
        rotations.append(bpy.data.objects['BK | waist'].rotation_euler.x)
        robot_positions.append(root.rotation_euler.to_matrix().inverted() @ bpy.data.objects['actor_kaiju_robot'].location)
        plume_lengths.append(bpy.data.objects['Booster L | amber exhaust'].scale.z)
        rig = bpy.data.objects['kaiju_robot_mesh'].evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = rig.to_mesh()
        points = [world_to_camera_view(s,s.camera,rig.matrix_world @ v.co) for v in mesh.vertices]
        robot_visible.append(any(p.z > 0 and 0 < p.x < 1 and 0 < p.y < 1 for p in points))
        rig.to_mesh_clear()
    assert (root.location-start).length > 40, 'No backward stagger'
    assert max(rotations)-min(rotations) > .45, 'Torso whip missing'
    assert not any(robot_visible[42:]), 'Robot fails to clear the collision frame'
    assert robot_positions[3].y-robot_positions[0].y > 8, 'Robot reverses instead of transferring forward momentum'
    assert robot_positions[7].z <= robot_positions[0].z, 'Robot bounces upward before the powered pull-up'
    assert plume_lengths[20] > plume_lengths[0]*1.4, 'Pull-up has no visible thrust increase'
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
            'post_contact_objects':contacts,'sandstone_asset':original.name,
            'linked_geometry_materials':True,'original_scale_preserved':True,
            'robot_positions_local': [list(p) for p in robot_positions],
            'powered_plume_scale':plume_lengths}


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
        negatives={}
        def reject(label,message):
            try:
                verify(manifest)
            except AssertionError as error:
                assert str(error)==message, f'Wrong negative failure: {error}'
                negatives[label]=str(error)
            else: raise AssertionError(f'{label} was accepted')
        rock=next(o for o in bpy.context.scene.objects if o.name.startswith('Reaction | stack'))
        original_scale=rock.scale.copy()
        try:
            rock.scale*=1.1
            reject('rescaled_original','Original sandstone scale changed')
        finally: rock.scale=original_scale
        def mutate_key(label,obj,path,frame,value,message):
            original_action=obj.animation_data.action; original_slot=obj.animation_data.action_slot
            copied=original_action.copy(); obj.animation_data.action=copied; obj.animation_data.action_slot=copied.slots[0]
            try:
                bpy.context.scene.frame_set(frame); setattr(obj,path,value)
                obj.keyframe_insert(data_path=path,frame=frame)
                reject(label,message)
            finally:
                obj.animation_data.action=original_action; obj.animation_data.action_slot=original_slot
                bpy.data.actions.remove(copied)
        rig=bpy.data.objects['actor_kaiju_robot']; s=bpy.context.scene; s.frame_set(1); start=rig.location.copy()
        wrong=start+root.rotation_euler.to_matrix() @ Vector((1.5,-95*.125,155*.125+18*.125**2))
        mutate_key('old_backward_rebound',rig,'location',4,wrong,'Robot reverses instead of transferring forward momentum')
        s.frame_set(8); wrong=rig.location.copy(); wrong.z=start.z+20
        mutate_key('premature_upward_bounce',rig,'location',8,wrong,'Robot bounces upward before the powered pull-up')
        s.frame_set(1); plume=bpy.data.objects['Booster L | amber exhaust']; original=plume.scale.copy()
        mutate_key('unpowered_climb',plume,'scale',21,original,'Pull-up has no visible thrust increase')
        if manifest.get('camera_mode')=='continuation':
            s.frame_set(1); wrong=s.camera.rotation_quaternion.copy()
            from mathutils import Quaternion
            wrong=wrong @ Quaternion((1,0,0),.05)
            mutate_key('wrong_camera_start',s.camera,'rotation_quaternion',1,wrong,'Continuation camera does not start at dive endpoint')
        verify(manifest); result['negative_controls']=negatives
    (a.directory/'scene_qa.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('feet_by_frame','robot_visible_by_frame','robot_positions_local','powered_plume_scale')}))
