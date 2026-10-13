"""Append T316 ascent without modifying the approved animation through frame 217.

Run in Blender 5.1.2 with the approved kaiju_liftoff_final.blend loaded.
The renderer remains 5.1.2; only the recovered grading compositor uses 4.1.1.
"""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

FIRST = 217


def curves(obj):
    return [fc for layer in obj.animation_data.action.layers
            for strip in layer.strips for bag in strip.channelbags for fc in bag.fcurves]


def preserve_handles(obj):
    # Inserting keys after an AUTO_CLAMPED endpoint otherwise changes old frames.
    for fc in curves(obj):
        for key in fc.keyframe_points:
            left, right = key.handle_left.copy(), key.handle_right.copy()
            key.handle_left_type = key.handle_right_type = 'FREE'
            key.handle_left, key.handle_right = left, right
        fc.keyframe_points[-1].interpolation = 'LINEAR'


def snapshot(scene):
    result = []
    for frame in range(1, FIRST + 1):
        scene.frame_set(frame)
        result.append({o.name: tuple(v for row in o.matrix_world for v in row)
                       for o in scene.objects})
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--full-exit', action='store_true', help='Reproduce superseded long-exit preview')
    a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    assert a.output.resolve() != Path(bpy.data.filepath).resolve()
    assert not a.output.exists(), 'Use a new output path'
    scene = bpy.context.scene
    before = snapshot(scene)
    lift = bpy.data.objects['Flight | lift and recoil']
    scene.frame_set(FIRST - 1)
    previous_z = lift.location.z
    scene.frame_set(FIRST)
    start_z = lift.location.z
    velocity = start_z - previous_z
    camera = scene.camera
    plumes = [o for o in scene.objects if any(o.name.endswith(' | ' + suffix)
               for suffix in ('amber exhaust', 'incandescent core', 'blue throat jet'))]
    assert len(plumes) == 6
    for obj in [lift, camera, *plumes]:
        preserve_handles(obj)
    camera_location = camera.location.copy()
    camera_rotation = camera.rotation_quaternion.copy()
    ramp, cruise = 16., 2.3
    hero = [o for o in lift.children_recursive if o.type == 'MESH']
    assert len(hero) > 20
    exit_frame = safe_exit_frame = None
    for frame in range(FIRST + 1, FIRST + (2401 if a.full_exit else 49)):
        t = frame - FIRST
        u = min(t / ramp, 1.)
        # Integral of smoothstep velocity, matching the photographed last step.
        z = start_z + velocity * min(t, ramp) + (cruise - velocity) * ramp * (u**3 - .5*u**4)
        z += cruise * max(0, t - ramp)
        lift.location = (0, 0, z)
        lift.keyframe_insert(data_path='location', frame=frame)
        camera.location = camera_location
        camera.rotation_quaternion = camera_rotation
        camera.keyframe_insert(data_path='location', frame=frame)
        camera.keyframe_insert(data_path='rotation_quaternion', frame=frame)
        for plume in plumes:
            sign = -1 if plume.name.startswith('Booster L') else 1
            flutter = 1 + .10*math.sin(frame*2.14 + sign) + .055*math.sin(frame*.77)
            plume.scale = (1, 1, flutter)
            plume.keyframe_insert(data_path='scale', frame=frame)
        scene.frame_set(frame)
        deps = bpy.context.evaluated_depsgraph_get()
        bottom = min(world_to_camera_view(scene, camera, obj.matrix_world @ Vector(corner)).y
                     for source in hero for obj in [source.evaluated_get(deps)]
                     for corner in obj.bound_box)
        if bottom > 1.0 and exit_frame is None:
            exit_frame = frame
        # Feet are the trailing geometry; the bright plumes have already cleared.
        if bottom > 1.0 and safe_exit_frame is None:
            safe_exit_frame = frame
        if safe_exit_frame is not None and frame >= safe_exit_frame + 12:
            break
    if a.full_exit:
        assert safe_exit_frame is not None, 'Robot did not exit within 100 seconds'
    last = frame
    for obj in [lift, camera, *plumes]:
        for fc in curves(obj):
            for key in fc.keyframe_points:
                if key.co.x > FIRST:
                    key.interpolation = 'LINEAR'
    after = snapshot(scene)
    max_error = max(abs(x-y) for old, new in zip(before, after)
                    for name in old for x, y in zip(old[name], new[name]))
    assert max_error < 1e-5, f'Approved animation changed: {max_error}'
    scene.frame_end = last
    scene.timeline_markers.new('CONTINUE | higher into sky', frame=218)
    scene['liftoff_note'] = 'T316: locked camera, natural ascent. Approved final cuts at f265; full-exit preview is superseded.'
    scene.frame_set(FIRST)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(a.output.resolve()), compress=True)
    report = dict(approved_frames_checked=FIRST, object_matrix_max_error=max_error,
                  new_frames=[218, last], appended_frames=last-FIRST,
                  duration_seconds=(last-FIRST)/24, exit_frame=exit_frame,
                  safe_exit_frame=safe_exit_frame, empty_hold_frames=12 if a.full_exit else 0, start_height=start_z,
                  end_height=z, initial_step=velocity, cruise_step=cruise,
                  ramp_frames=ramp, animated_plumes=len(plumes), camera_behavior="locked at frame 217")
    a.output.with_suffix('.json').write_text(json.dumps(report, indent=2))
    print('CONTINUATION', json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
