"""Work backwards from the approved T314 endpoint to a tripod pan/zoom."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from take2 import locked_state
from take3_hold import bounds, composition, clearance
from verify_take2 import lenses
from verify_take3 import world_state


def smooth(value):
    value = max(0, min(1, value))
    return value * value * (3 - 2 * value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.output.mkdir(parents=True, exist_ok=True)
    destination = args.output / 'arrival_move.blend'
    assert destination.resolve() != args.source.resolve()
    source_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()))
    scene = bpy.context.scene
    camera = scene.camera
    for action in bpy.data.actions:
        action.use_fake_user = True
    original_action = camera.animation_data.action
    expected = locked_state(scene, camera)
    expected_lenses, expected_world = lenses(scene), world_state(scene)
    scene.frame_set(86)
    endpoint = camera.rotation_quaternion.copy()
    station = camera.location.copy()
    optics = (camera.data.sensor_width, camera.data.sensor_height, camera.data.sensor_fit)
    ray = endpoint @ Vector((0, 0, -1))
    final_pitch = math.asin(ray.z)
    final_yaw = math.atan2(ray.x, ray.y)
    # Preserve the initial B opening bearing, then arrive at the approved yaw.
    initial_yaw = math.atan2(20 - (-15), 108 - (-5))
    camera.animation_data.action = original_action.copy()
    camera.animation_data.action.name = 'T314 | approved endpoint backwards move'
    poses = {}
    for frame in range(1, 109):
        scene.frame_set(frame)
        pitch = math.radians(13) + smooth((frame - 44) / 19) * (final_pitch - math.radians(13))
        yaw = initial_yaw + smooth((frame - 20) / 32) * (final_yaw - initial_yaw)
        ray = Vector((math.sin(yaw) * math.cos(pitch), math.cos(yaw) * math.cos(pitch), math.sin(pitch)))
        camera.rotation_quaternion = endpoint if frame >= 63 else ray.to_track_quat('-Z', 'Y')
        camera.keyframe_insert(data_path='rotation_quaternion', frame=frame)
        poses[frame] = list(camera.rotation_quaternion)
    for layer in camera.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation = 'LINEAR'

    def verify():
        assert locked_state(scene, scene.camera, bpy.data.actions[original_action.name]) == expected
        assert lenses(scene) == expected_lenses, 'Lens timing changed'
        assert world_state(scene) == expected_world, 'HDRI changed'
        cam = scene.camera
        assert (cam.data.sensor_width, cam.data.sensor_height, cam.data.sensor_fit) == optics
        for frame in range(1, 109):
            scene.frame_set(frame)
            assert (cam.location - station).length < 1e-6, 'Tripod moved'
            assert max(abs(a-b) for a,b in zip(cam.rotation_quaternion, poses[frame])) < 1e-6
            direction = cam.rotation_quaternion @ Vector((0, 0, -1))
            if frame <= 44:
                assert abs(math.degrees(math.asin(direction.z)) - 13) < 1e-4, 'Opening tilt must remain 13 degrees through frame 44'
            if frame >= 52:
                assert abs(math.atan2(direction.x, direction.y) - final_yaw) < 1e-6, 'Pan must settle by contact'
            if frame >= 63:
                assert list(cam.rotation_quaternion) == list(endpoint), 'Approved endpoint changed'
        scene.frame_set(86)
        composition(scene)
        clearance(scene)

    verify()
    scene['shot'] = 'T314 approved endpoint with backwards-derived tripod pan-up and locked focal push-in'
    scene['take3_hold_only'] = False
    scene.frame_set(86)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(destination.resolve()))
    # Keep the action name independent of invalidated Blender data on reopen.
    original_name = original_action.name
    bpy.ops.wm.open_mainfile(filepath=str(destination.resolve()))
    scene = bpy.context.scene
    original_action = bpy.data.actions[original_name]
    verify()
    assert hashlib.sha256(args.source.read_bytes()).hexdigest() == source_hash
    (args.output / 'move_verification.json').write_text(json.dumps({
        'status': 'PASS', 'source': str(args.source.resolve()), 'source_sha256': source_hash,
        'blend': str(destination.resolve()), 'blend_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
        'station': list(station), 'endpoint_quaternion': list(endpoint),
        'tilt_degrees': [13, math.degrees(final_pitch)], 'tilt_frames': [44, 63], 'pan_frames': [20, 52],
        'locked_state_sha256': expected, 'exact_lens_frames_compared': 108,
        'endpoint_bounds': bounds(scene), 'camera_poses': poses,
    }, indent=2) + '\n')
    print('T314_MOVE_READY', destination, flush=True)


if __name__ == '__main__':
    main()
