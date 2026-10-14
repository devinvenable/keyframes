"""Whole-mesh clearance, torso contact, centered travel, and 60% close framing."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_328 import mesh, parts, rocks, solidity, flight, preserved


def framing():
    s=bpy.context.scene; root=bpy.data.objects['BK | ROOT | placement']; reference=None; rows=[]
    for f in range(106,125):
        s.frame_set(f)
        points=[world_to_camera_view(s,s.camera,v) for o in parts() for v in mesh(o)[0]]
        head=[world_to_camera_view(s,s.camera,v) for o in parts() if any(t in o.name for t in ('helmet','eye','drill','horn','crown','mandible')) for v in mesh(o)[0]]
        y0,y1=min(v.y for v in points),max(v.y for v in points); height=y1-y0
        crop=max(0,-y0)/height
        assert .54 <= crop <= .67, f'Bottom crop outside head/torso target at f{f}: {crop:.3f}'
        assert all(v.z>0 and .01<v.x<.99 and .01<v.y<.99 for v in head), f'Head outside frame at f{f}'
        assert max(0,y1-1)<.01 and min(v.x for v in points)>-.08 and max(v.x for v in points)<1.08, f'Crop is not bottom-dominant at f{f}'
        offset=s.camera.location-root.location
        if reference is None: reference=offset.copy()
        drift=(offset-reference).length
        assert drift<.002, f'Camera does not fly with beetle at f{f}'
        rows.append({'frame':f,'bottom_crop_fraction':crop,'height':height,'camera_drift':drift})
    return rows


def centered():
    s=bpy.context.scene; root=bpy.data.objects['BK | ROOT | placement']; inv=root.rotation_euler.to_matrix().transposed()
    s.frame_set(112); launch=root.location.copy(); s.frame_set(124)
    lateral=(inv@(root.location-launch)).x
    assert abs(lateral)<.01, f'Flight veers toward rock edge: {lateral:.3f}'
    surfaces=[mesh(o)[1] for o in rocks()]
    distances={o.name:min(r.find_nearest(v)[3] for r in surfaces for v in mesh(o)[0]) for o in parts() if o.name.startswith('BK | elytron')}
    assert min(distances.values())<.5, f'Torso misses rock face: {min(distances.values()):.3f}'
    assert min(d for n,d in distances.items() if ' L ' in n)<3 and min(d for n,d in distances.items() if ' R ' in n)<3, 'Only one edge of torso reaches rock'
    return {'lateral_travel':lateral,'shell_distances':distances}


def main(a):
    result={'status':'PASS','framing':framing(),'centered_contact':centered(),
            'solidity':solidity(range(113,193)), 'airborne_speeds':flight(),
            'preserved_contact_launch_error':preserved(a.baseline)}
    if a.negative_checks:
        saved=bpy.data.filepath; failures={}
        def rejects(name,check,expected):
            try: check()
            except AssertionError as e:
                assert str(e).startswith(expected), f'Wrong negative assertion: {e}'
                failures[name]=str(e)
            else: raise AssertionError('Undetected negative: '+name)
        bpy.ops.wm.open_mainfile(filepath=str(a.baseline))
        rejects('actual_round05_framing',framing,'Bottom crop outside')
        rejects('actual_round05_edge_strike',centered,'Flight veers')
        bpy.ops.wm.open_mainfile(filepath=str(a.baseline.parent.parent/'round_04/unified.blend'))
        rejects('actual_round04_solidity',lambda:solidity(range(130,131)),'Rock interpenetration')
        bpy.ops.wm.open_mainfile(filepath=saved)
        root=bpy.data.objects['BK | ROOT | placement']; s=bpy.context.scene; s.frame_set(124)
        root.location+=root.rotation_euler.to_matrix()@Vector((0,8,0)); root.keyframe_insert(data_path='location',frame=124)
        rejects('penetrating_torso',lambda:solidity(range(124,125)),'Rock interpenetration')
        bpy.ops.wm.open_mainfile(filepath=saved)
        s=bpy.context.scene; camera=s.camera; s.frame_set(106); station=camera.location.copy()
        s.frame_set(107); camera.location=station; camera.keyframe_insert(data_path='location',frame=107)
        rejects('frozen_camera',framing,'Camera does not fly')
        bpy.ops.wm.open_mainfile(filepath=saved)
        s=bpy.context.scene; s.camera.data.shift_y+=.5
        rejects('head_cropped',framing,'Bottom crop outside')
        bpy.ops.wm.open_mainfile(filepath=saved)
        result['negative_controls']=failures
        result['negative_round05_sha256']=hashlib.sha256(a.baseline.read_bytes()).hexdigest()
    (a.directory/'revision_qa.json').write_text(json.dumps(result,indent=2)+'\n')
    print('CENTERED_QA',json.dumps({k:v for k,v in result.items() if k!='solidity'}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True); p.add_argument('--negative-checks',action='store_true')
    main(p.parse_args(sys.argv[sys.argv.index('--')+1:]))
