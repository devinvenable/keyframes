"""Saved-scene motion/continuity contracts, with reversible negative controls."""
import argparse
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

CONTACT,HIT,END=106,124,192


def check_speed(speeds):
    assert all(b>=a-.002 for a,b in zip(speeds[63:],speeds[64:])), 'Dive brakes before contact'


def tree(o):
    deps=bpy.context.evaluated_depsgraph_get(); e=o.evaluated_get(deps); m=e.to_mesh()
    result=BVHTree.FromPolygons([e.matrix_world @ v.co for v in m.vertices],[tuple(p.vertices) for p in m.polygons])
    e.to_mesh_clear(); return result


def verify():
    s=bpy.context.scene; rig=bpy.data.objects['actor_kaiju_robot']; root=bpy.data.objects['BK | ROOT | placement']
    rock=next(o for o in s.objects if o.name.startswith('Reaction | stack'))
    assert rock.data==bpy.data.objects[rock['asset_source']].data, 'Original sandstone geometry missing'
    assert s.frame_start==1 and s.frame_end==END, 'Full continuous timeline missing'
    assert s.camera.parent is None, 'Continuous camera not baked in world space'
    positions=[]; roots=[]; feet=[]; cameras=[]; rocks=[]
    fragments=[o for o in s.objects if o.name.startswith(('Reaction | fragment','Reaction | powder'))]
    assert len(fragments)==196, 'Impact effects missing'
    for f in range(1,END+1):
        s.frame_set(f)
        positions.append(rig.location.copy()); roots.append(root.location.copy()); cameras.append(s.camera.location.copy())
        rocks.append(tuple(v for row in rock.matrix_world for v in row))
        assert not rock.hide_render, 'Rock appears late'
        feet.append([min((bpy.data.objects['BK | sole '+side].matrix_world @ Vector(c)).z for c in bpy.data.objects['BK | sole '+side].bound_box) for side in ('L','R')])
        if f in (HIT-1,HIT):
            for o in fragments:
                if f==HIT-1: assert max(o.scale)<.002, 'Debris visible before rock impact'
                else: assert min(o.scale)>.01, 'Debris is late at rock impact'
    speeds=[(b-a).length for a,b in zip(positions[:CONTACT-1],positions[1:CONTACT])]
    check_speed(speeds)
    assert min(min(row) for row in feet[112:124])>10, 'Beetle not launched off both feet'
    assert min(min(row) for row in feet[CONTACT:])>-.02, 'Feet penetrate ground'
    assert (roots[HIT-1]-roots[CONTACT-1]).length>110, 'Launch lacks backward travel'
    assert roots[HIT-1].z-roots[165].z>15, 'Downward slide missing'
    assert all(m==rocks[0] for m in rocks), 'Collision environment changes during shot'
    shells=[o for o in s.objects if o.type=='MESH' and o.name.startswith('BK |')]
    contacts={}
    for f in (CONTACT,HIT-1,HIT):
        s.frame_set(f); r=tree(rock)
        contacts[f]=[]
        for o in shells:
            evaluated=o.evaluated_get(bpy.context.evaluated_depsgraph_get()); m=evaluated.to_mesh()
            distance=min(r.find_nearest(evaluated.matrix_world @ v.co)[3] for v in m.vertices)
            evaluated.to_mesh_clear()
            if distance<.5: contacts[f].append(o.name)
    assert not contacts[CONTACT] and not contacts[HIT-1], 'Beetle touches rock before impact cue'
    assert contacts[HIT], 'Beetle misses rock at impact cue'
    return {'status':'PASS','approach_speeds':speeds,'feet_by_frame':feet,'rock_contacts':contacts,
            'launch_distance':(roots[HIT-1]-roots[CONTACT-1]).length,
            'slide_drop':roots[HIT-1].z-roots[165].z,'single_fixed_environment':True}


def main(a):
    result=verify()
    if a.negative_checks:
        negatives={}; s=bpy.context.scene
        def mutation(name,obj,path,frame,change,expected):
            action=obj.animation_data.action; slot=obj.animation_data.action_slot
            copy=action.copy(); obj.animation_data.action=copy; obj.animation_data.action_slot=copy.slots[0]
            try:
                s.frame_set(frame); value=change(getattr(obj,path).copy()); setattr(obj,path,value)
                obj.keyframe_insert(data_path=path,frame=frame)
                try: verify()
                except AssertionError as e:
                    assert str(e)==expected, f'Wrong negative assertion: {e}'
                    negatives[name]=str(e)
                else: raise AssertionError(f'Undetected mutation: {name}')
            finally:
                obj.animation_data.action=action; obj.animation_data.action_slot=slot; bpy.data.actions.remove(copy)
        rig=bpy.data.objects['actor_kaiju_robot']; s.frame_set(CONTACT-1); prev=rig.location.copy()
        mutation('braking_approach',rig,'location',CONTACT,lambda v:prev+(v-prev)*.5,'Dive brakes before contact')
        root=bpy.data.objects['BK | ROOT | placement']
        mutation('grounded_tap',root,'location',116,lambda v:Vector((v.x,v.y,0)),'Beetle not launched off both feet')
        fragment=bpy.data.objects['Reaction | fragment 000']
        mutation('late_debris',fragment,'scale',HIT,lambda v:Vector((.001,)*3),'Debris is late at rock impact')
        verify()
        # The actual unfixed approved dive must fail the same speed assertion.
        saved=bpy.data.filepath
        source=json.loads((a.directory/'manifest.json').read_text())['source']
        bpy.ops.wm.open_mainfile(filepath=source)
        positions=[]
        for f in range(1,CONTACT+1):
            bpy.context.scene.frame_set(f); positions.append(bpy.data.objects['actor_kaiju_robot'].location.copy())
        old_speeds=[(b-a).length for a,b in zip(positions,positions[1:])]
        try: check_speed(old_speeds)
        except AssertionError as e: negatives['actual_unfixed_T320_approach']=str(e)
        else: raise AssertionError('Actual unfixed dive passed approach check')
        bpy.ops.wm.open_mainfile(filepath=saved); verify()
        result['negative_controls']=negatives
    (a.directory/'scene_qa.json').write_text(json.dumps(result,indent=2)+'\n')
    print('UNIFIED_QA',json.dumps({k:v for k,v in result.items() if k not in ('feet_by_frame','approach_speeds')}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--directory',type=Path,required=True); p.add_argument('--negative-checks',action='store_true')
    main(p.parse_args(sys.argv[sys.argv.index('--')+1:]))
