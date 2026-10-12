"""Derive only the revised frame-86 endpoint; the camera move is not approved."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
from take2 import locked_state
from verify_take2 import lenses
from verify_take3 import elevation, world_state


def bounds(scene):
    bpy.context.view_layer.update()
    points = [world_to_camera_view(scene, scene.camera, obj.matrix_world @ Vector(corner))
              for obj in scene.objects if obj.name.startswith('BK |') and obj.type == 'MESH'
              for corner in obj.bound_box]
    assert min(p.z for p in points) > 0, 'Actor must remain in front of camera'
    return [min(p.x for p in points), min(p.y for p in points),
            max(p.x for p in points), max(p.y for p in points)]


def composition(scene):
    box = bounds(scene)
    assert abs((box[0] + box[2]) / 2 - 1 / 3) < .001, 'Actor silhouette must center on left third'


def clearance(scene):
    box = bounds(scene)
    assert min(box[:2]) > .015 and max(box[2:]) < .985, ('Actor/horn cropped', box)


def distance(scene):
    position = scene.camera.location
    return (Vector((position.x, position.y)) - Vector((-45, 75))).length


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--negative-checks', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    destination = args.output / 'hold_B_left_third.blend'
    assert destination.resolve() != args.source.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()))
    scene, negative = bpy.context.scene, []
    camera = scene.camera
    for action in bpy.data.actions:
        action.use_fake_user = True
    original_action = camera.animation_data.action
    expected = locked_state(scene, camera)
    expected_lenses, expected_world = lenses(scene), world_state(scene)
    scene.frame_set(86)
    original_position = camera.location.copy()
    original_distance, original_elevation = distance(scene), elevation(scene, 86)

    def closer():
        assert distance(scene) < original_distance * .95, 'Endpoint must move materially closer than B'

    def higher():
        assert elevation(scene, 86) > original_elevation + 2, 'Endpoint must tilt further upward than B'

    def reject(check, label):
        try:
            check()
        except AssertionError as error:
            negative.append({'mutation': label, 'assertion': str(error)})
        else:
            raise AssertionError(f'Negative check failed to discriminate: {label}')

    if args.negative_checks:
        reject(lambda: composition(scene), 'Unmodified B hold is centered')
        reject(closer, 'Unmodified B stand-off')
        reject(higher, 'Unmodified B upward tilt')
    # Save a static endpoint camera. Earlier frames deliberately carry no new
    # authored move: Devin will work backwards from this composition.
    camera.animation_data_clear()
    mark = Vector((-45, 75, original_position.z))
    camera.location = mark + (original_position - mark) * .88
    pitch = math.radians(31.5)
    lo, hi = -math.pi / 2, math.pi / 2
    for _ in range(40):
        yaw = (lo + hi) / 2
        ray = Vector((math.sin(yaw) * math.cos(pitch),
                      math.cos(yaw) * math.cos(pitch), math.sin(pitch)))
        camera.rotation_quaternion = ray.to_track_quat('-Z', 'Y')
        box = bounds(scene)
        if (box[0] + box[2]) / 2 > 1 / 3:
            lo = yaw
        else:
            hi = yaw
    camera.keyframe_insert(data_path='rotation_quaternion', frame=86)
    camera.animation_data.action.name = 'T313 | revised hold only'
    composition(scene)
    clearance(scene)
    closer()
    higher()
    if args.negative_checks:
        sensor = camera.data.sensor_width
        try:
            camera.data.sensor_width = 36
            reject(lambda: clearance(scene), 'Restore narrow sensor and crop the close hold')
        finally:
            camera.data.sensor_width = sensor
        clearance(scene)
    assert locked_state(scene, camera, original_action) == expected, 'Actor/dust animation changed'
    assert lenses(scene) == expected_lenses, 'Lens timing changed'
    assert world_state(scene) == expected_world, 'Environment changed'
    scene.frame_set(86)
    scene['shot'] = 'T313 B revised endpoint: left third, 12% closer, 31.5-degree upward tilt'
    scene['take3_hold_only'] = 'Frame 86 composition review only; earlier camera move awaits direction'
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(destination.resolve()))
    # Verify the serialized scene, including retained animation archives.
    action_name = original_action.name
    bpy.ops.wm.open_mainfile(filepath=str(destination.resolve()))
    scene = bpy.context.scene
    assert locked_state(scene, scene.camera, bpy.data.actions[action_name]) == expected
    assert lenses(scene) == expected_lenses and world_state(scene) == expected_world
    scene.frame_set(86)
    composition(scene)
    clearance(scene)
    closer()
    higher()
    assert hashlib.sha256(args.source.read_bytes()).hexdigest() == source_hash
    (args.output / 'hold_verification.json').write_text(json.dumps({
        'status': 'PASS', 'stage': 'Endpoint preview only; camera move deferred by Devin',
        'source': str(args.source.resolve()), 'source_sha256': source_hash,
        'blend': str(destination.resolve()), 'blend_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
        'frame': 86, 'original_position': list(original_position),
        'position': list(scene.camera.location), 'distance_from_landing': distance(scene),
        'original_distance': original_distance, 'closer_percent': 12,
        'original_elevation': original_elevation, 'elevation': elevation(scene, 86),
        'beetle_bounds': bounds(scene), 'silhouette_center_x': 1 / 3,
        'lens': scene.camera.data.lens, 'sensor_width': scene.camera.data.sensor_width,
        'locked_state_sha256': expected, 'exact_lens_frames_compared': 108,
        'dust_changes': 'None', 'negative_checks': negative,
    }, indent=2))
    print('T313_REVISED_HOLD_READY', destination, flush=True)


if __name__ == '__main__':
    main()
