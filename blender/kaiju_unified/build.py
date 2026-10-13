"""T325: one set, one camera, accelerating dive, airborne smash and slide.

Creates the full shot; only the impact excerpt is authorized for draft rendering.
Run using Blender 5.1.2. Source assets and previously approved takes stay intact.
"""
import argparse
import bisect
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import sys

import bpy
from mathutils import Vector, Quaternion

spec = importlib.util.spec_from_file_location('reaction_builder', Path(__file__).resolve().parents[1]/'kaiju_reaction/build.py')
reaction = importlib.util.module_from_spec(spec); spec.loader.exec_module(reaction)
key, ramp, curve = reaction.key, reaction.ramp, reaction.curve
SOURCE = reaction.SOURCE
CONTACT, HIT, END = 106, 124, 192


def linear_keys():
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in bag.fcurves:
                        for point in fc.keyframe_points: point.interpolation = 'LINEAR'


def retime_dive():
    """Resample the existing path by growing arc distance, retaining its poses.

    s(t)=L*(.65*t+.35*t²) has strictly increasing speed. Resampling all animated
    objects together retains the original brace, hatch and booster relationships.
    """
    s = bpy.context.scene; rig = bpy.data.objects['actor_kaiju_robot']
    animated = [o for o in s.objects if o.animation_data and o.animation_data.action]
    old_camera = s.camera
    times = [1+i/8 for i in range((CONTACT-1)*8+1)]
    lengths = [0.]; prev = None
    for time in times:
        s.frame_set(int(time), subframe=time-int(time))
        pos = rig.location.copy()
        if prev is not None: lengths.append(lengths[-1]+(pos-prev).length)
        prev = pos
    samples = []; camera_samples = []; mapping = []
    for f in range(1, CONTACT+1):
        t = (f-1)/(CONTACT-1); distance = lengths[-1]*(.65*t+.35*t*t)
        i = min(len(times)-1, max(1, bisect.bisect_left(lengths, distance)))
        u = (distance-lengths[i-1])/(lengths[i]-lengths[i-1])
        time = times[i-1]+u*(times[i]-times[i-1]); mapping.append(time)
        s.frame_set(int(time), subframe=time-int(time))
        samples.append({o.name:(o.location.copy(), o.rotation_quaternion.copy(), o.rotation_euler.copy(), o.scale.copy()) for o in animated})
        camera_samples.append(old_camera.matrix_world.copy())
    for o in animated: o.animation_data_clear()
    for f, sample in enumerate(samples, 1):
        for name, (pos, q, euler, scale) in sample.items():
            o = bpy.data.objects[name]
            key(o, 'location', pos, f); key(o, 'scale', scale, f)
            key(o, 'rotation_quaternion' if o.rotation_mode=='QUATERNION' else 'rotation_euler',
                q if o.rotation_mode=='QUATERNION' else euler, f)
    camera = bpy.data.objects.new('Unified | continuous chase and pan', old_camera.data.copy())
    s.collection.objects.link(camera); camera.rotation_mode='QUATERNION'; s.camera=camera
    for f, matrix in enumerate(camera_samples, 1):
        key(camera, 'location', matrix.translation, f)
        key(camera, 'rotation_quaternion', matrix.to_quaternion(), f)
    s.frame_set(CONTACT)
    return mapping, camera_samples[-1]


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE)); s=bpy.context.scene
    for image in bpy.data.images:
        if image.filepath: image.filepath=bpy.path.abspath(image.filepath)
    s.frame_set(CONTACT); contact_state=reaction.actor_state()
    mapping, camera_end=retime_dive()
    controls={o.name[5:]:o for o in s.objects if o.name.startswith('BK |') and o.type=='EMPTY'}
    root=controls['ROOT | placement']; station=root.location.copy(); rotation=root.rotation_euler.to_matrix()
    def world(xyz): return station+rotation @ Vector(xyz)
    base_rot={name:o.rotation_euler.copy() for name,o in controls.items()}
    base_loc={name:o.location.copy() for name,o in controls.items()}
    rig=bpy.data.objects['actor_kaiju_robot']; robot_start=rig.location.copy(); robot_q=rig.rotation_quaternion.copy()
    s.frame_set(CONTACT-1); incoming=robot_start-rig.location; s.frame_set(CONTACT)
    camera=s.camera; initial_q=camera_end.to_quaternion()
    plumes={o.name:o.scale.copy() for o in s.objects if o.name.startswith('Booster ') and any(x in o.name for x in ('amber exhaust','incandescent core','blue throat jet'))}
    for f in range(CONTACT+1, END+1):
        n=f-CONTACT
        # Eighteen frames from punch to cliff. Full backward velocity survives
        # until impact; the downward slide starts only after the shell hits.
        back=6.8*min(n,HIT-CONTACT)
        lift=4.2*n-.14*n*n if f<=HIT else 30.24-42*min(1,((f-HIT)/30)**2)
        if f>HIT: back+=curve(f,[(HIT,0),(HIT+2,1.5),(HIT+7,-3),(END,-3)])
        key(root,'location',world((0,back,lift)),f)
        whip=curve(f,[(CONTACT,0),(CONTACT+4,-24),(HIT-1,-32),(HIT+2,10),(HIT+7,-20),(HIT+36,24),(END,24)])
        twist=curve(f,[(CONTACT,0),(CONTACT+7,8),(HIT,-7),(HIT+3,10),(HIT+30,4),(END,4)])
        def joint(name,delta):
            key(controls[name],'rotation_euler',tuple(a+math.radians(b) for a,b in zip(base_rot[name],delta)),f)
        joint('waist',(whip,0,twist)); joint('neck',(-whip*.55,0,-twist*.6))
        flare=curve(f,[(CONTACT,0),(CONTACT+5,1),(HIT,1),(HIT+3,.5),(HIT+12,.9),(HIT+36,.12),(END,.12)])
        slump=ramp(f,HIT+8,HIT+38)
        key(controls['pelvis'],'location',base_loc['pelvis']+Vector((0,0,-12*slump)),f)
        for side,sign in [('L',-1),('R',1)]:
            joint('shoulder '+side,(40*flare,sign*66*flare,sign*22*flare))
            joint('elbow '+side,(35*flare,0,0))
            # Relax out of the inherited raised guard after the collision.
            # Absolute hinge poses leave a hanging arm instead of a reset stance.
            for name,target in [('shoulder '+side,(8,sign*10,sign*5)),('elbow '+side,(-12,0,0))]:
                o=controls[name]; q=tuple(a+(math.radians(b)-a)*slump for a,b in zip(o.rotation_euler,target))
                key(o,'rotation_euler',q,f)
            kick=ramp(f,CONTACT,CONTACT+6)*(1-.55*slump)
            joint('hip '+side,(-24*kick-25*slump,sign*10*kick,0))
            joint('knee '+side,(48*kick+35*slump,0,0))
            joint('ankle '+side,(-22*kick-12*slump,0,0))
        neck=controls['neck']; key(neck,'rotation_euler',tuple(a+(b-a)*slump for a,b in zip(neck.rotation_euler,(math.radians(28),0,0))),f)
        bpy.context.view_layer.update()
        floor=min((bpy.data.objects['BK | sole '+side].matrix_world @ Vector(c)).z for side in ('L','R') for c in bpy.data.objects['BK | sole '+side].bound_box)
        if floor<0:
            p=root.location.copy(); p.z-=floor; key(root,'location',p,f)
        # Forward momentum transfers on contact. Robot glances past the shoulder
        # and only then climbs under increased thrust.
        travel=2.4*(1-math.exp(-n/2.4))
        pos=robot_start+incoming*travel+rotation @ Vector((130*ramp(n,1,12),1.2*n+.065*max(0,n-8)**2,.5*max(0,n-4)**2))
        key(rig,'location',pos,f)
        pitch=math.radians(-19+74*ramp(n,5,24))
        heading=rotation @ Vector((.3*ramp(n,1,12),math.cos(pitch),math.sin(pitch)))
        key(rig,'rotation_quaternion',robot_q.slerp(heading.to_track_quat('Z','Y'),ramp(n,0,9)),f)
        for name,scale in plumes.items(): key(bpy.data.objects[name],'scale',(scale.x,scale.y,scale.z*(1+.5*ramp(n,7,17))),f)
        aim=world((0,back,47+max(0,lift)*.7))-camera_end.translation
        q=initial_q.slerp(aim.to_track_quat('-Z','Y'),ramp(n,0,12))
        # A two-frame practical-camera jolt belongs after the rock contact.
        shake={HIT:.7,HIT+1:-.45,HIT+2:.2}.get(f,0)
        q=q @ Quaternion((1,0,0),math.radians(shake))
        key(camera,'location',camera_end.translation,f); key(camera,'rotation_quaternion',q,f)
    reaction.HIT, reaction.END=HIT,END
    reaction.effects(world,random.Random(32560),burst_z=30,synchronized=True,force=2.1)
    linear_keys()
    s.frame_start=1; s.frame_end=END; s.render.fps=24
    s.cycles.volume_step_rate=1; s.cycles.volume_max_steps=256
    s['shot']='T325 unified flight and airborne rock impact; draft gate pending'
    s.timeline_markers.clear()
    for name,f in [('Accelerating dive',1),('First chest contact',CONTACT),('Airborne rock smash / debris birth',HIT),('Slide down rock',145),('Slumped settle',END)]: s.timeline_markers.new(name,frame=f)
    s.frame_set(CONTACT); bpy.context.view_layer.update()
    after=reaction.actor_state()
    error=max(abs(v-w) for name,row in contact_state.items() for v,w in zip(row,after[name]))
    assert error<.0002, f'Contact pose changed: {error}'
    s.frame_set(HIT); bpy.context.preferences.filepaths.save_version=0
    dest=output/'unified.blend'; bpy.ops.wm.save_as_mainfile(filepath=str(dest))
    report={'source':str(SOURCE),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            'scene_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'frames':END,'fps':24,
            'contact_frame':CONTACT,'rock_contact_frame':HIT,'contact_transform_max_error':error,
            'source_time_by_frame':mapping,'draft_range':[100,180],'final_approved':False}
    (output/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print('UNIFIED_BUILT',json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,required=True)
    build(p.parse_args(sys.argv[sys.argv.index('--')+1:]).output)
