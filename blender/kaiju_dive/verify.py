"""Saved-scene checks for the T317 preview; visual occlusion still needs review."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


def check():
    s = bpy.context.scene
    rig = bpy.data.objects['actor_kaiju_robot']
    assert s.camera.parent == rig, 'Camera must ride the robot'
    assert (s.frame_start, s.frame_end, s.render.fps) == (1, 96, 24)
    samples = []
    for f in range(1, 97):
        s.frame_set(f)
        foot = []
        for side in ('L', 'R'):
            sole = bpy.data.objects['BK | sole '+side]
            floor = min((sole.matrix_world @ Vector(c)).z for c in sole.bound_box)
            assert abs(floor) < .05, f'Foot contact lost at {f}: {floor}'
            foot.append(list(sole.matrix_world.translation))
            plume = bpy.data.objects['Booster '+side+' | incandescent core']
            assert min(plume.scale) > .75, 'Thrust must remain lit'
        samples.append({'frame': f, 'robot': list(rig.location), 'feet': foot,
                        'waist': list(bpy.data.objects['BK | waist'].rotation_euler),
                        'neck': list(bpy.data.objects['BK | neck'].rotation_euler)})
    for joint, axis, minimum in [('waist', 0, 10), ('neck', 2, 25)]:
        span = math.degrees(max(x[joint][axis] for x in samples)-min(x[joint][axis] for x in samples))
        assert span > minimum, f'Beetle {joint} reaction is static or too small: {span}'
    for side in (0, 1):
        for axis in (0, 1):
            drift = max(x['feet'][side][axis] for x in samples)-min(x['feet'][side][axis] for x in samples)
            assert drift < .1, f'Planted foot skates: {drift}'
    assert samples[0]['robot'][2]-samples[-1]['robot'][2] > 500, 'Missing sky-to-ground descent'
    points = [world_to_camera_view(s, s.camera, o.matrix_world @ Vector(c))
              for o in s.objects if o.name.startswith('BK |') and o.type == 'MESH' for c in o.bound_box]
    bounds = [min(p.x for p in points), max(p.x for p in points), min(p.y for p in points), max(p.y for p in points)]
    assert all(p.z > 0 for p in points), 'Beetle behind endpoint camera'
    assert 0 < bounds[0] < bounds[1] < 1 and 0 < bounds[2] < bounds[3] < 1, f'Endpoint beetle cropped: {bounds}'
    assert bounds[3]-bounds[2] > .25, f'Endpoint beetle too small: {bounds}'
    # Arm directions distinguish the two requested candidates in rig space.
    for side in ('L', 'R'):
        bone = rig.pose.bones['arm_'+side]
        direction = (bone.tail-bone.head).normalized()
        if s['arm_pose'] == 'forward':
            assert direction.z > .8, 'Forward arm is not extended along flight'
        else:
            assert direction.z < -.8, 'Swept arm is not trailing along body'
    return {'status': 'PASS', 'endpoint_beetle_bounds': bounds, 'samples': samples}


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--negative-checks', action='store_true')
a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
result = check()
result['negative_controls'] = {}
if a.negative_checks:
    s = bpy.context.scene
    camera, parent = s.camera, s.camera.parent
    camera.parent = None
    try:
        check()
    except AssertionError as error:
        assert str(error) == 'Camera must ride the robot'
        result['negative_controls']['detached_camera'] = str(error)
    else:
        raise AssertionError('Detached camera mutation passed')
    finally:
        camera.parent = parent
    controls = [bpy.data.objects['BK | '+name] for name in ('waist', 'neck')]
    backups = [(o, o.animation_data.action, o.animation_data.action_slot) for o in controls]
    try:
        for obj, _, _ in backups:
            obj.animation_data.action = None
        check()
    except AssertionError as error:
        assert 'reaction is static' in str(error), str(error)
        result['negative_controls']['statue_beetle'] = str(error)
    else:
        raise AssertionError('Static beetle mutation passed')
    finally:
        for obj, action, slot in backups:
            obj.animation_data.action = action
            obj.animation_data.action_slot = slot
    check()
result['scene_sha256'] = hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest()
a.output.write_text(json.dumps(result, indent=2)+'\n')
print('DIVE_VERIFIED', result['endpoint_beetle_bounds'], result['negative_controls'])
