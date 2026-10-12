"""Verify saved T313 previews, with assertion-level negative mutations."""
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
from verify_take2 import foliage, lenses


def empty_start(scene):
    # The close B camera puts the waiting actor behind its near plane. A
    # projected-X test alone reverses sign there and falsely reports visibility.
    bpy.context.view_layer.update()
    camera = scene.camera
    inverse = camera.matrix_world.inverted()
    corners = camera.data.view_frame(scene=scene)
    left, right = min(p.x / -p.z for p in corners), max(p.x / -p.z for p in corners)
    bottom, top = min(p.y / -p.z for p in corners), max(p.y / -p.z for p in corners)
    for obj in scene.objects:
        if not obj.name.startswith('BK |') or obj.type != 'MESH':
            continue
        points = [inverse @ obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        outside = (all(p.z >= 0 for p in points)
                   or all(p.x < left * -p.z for p in points)
                   or all(p.x > right * -p.z for p in points)
                   or all(p.y < bottom * -p.z for p in points)
                   or all(p.y > top * -p.z for p in points))
        assert outside, f'Waiting beetle may appear in opening: {obj.name}'


def world_state(scene):
    nodes = scene.world.node_tree.nodes
    env = nodes['T312 | natural quarry foliage']
    mapping = next(node for node in nodes if node.type == 'MAPPING')
    background = next(node for node in nodes if node.type == 'BACKGROUND')
    return {'image_sha256': hashlib.sha256(Path(bpy.path.abspath(env.image.filepath)).read_bytes()).hexdigest(),
            'rotation': list(mapping.inputs['Rotation'].default_value),
            'scale': list(mapping.inputs['Scale'].default_value),
            'strength': background.inputs['Strength'].default_value,
            'links': sorted((link.from_node.name, link.from_socket.name,
                             link.to_node.name, link.to_socket.name)
                            for link in scene.world.node_tree.links)}


def elevation(scene, frame):
    scene.frame_set(frame)
    ray = scene.camera.rotation_quaternion @ Vector((0, 0, -1))
    return math.degrees(math.asin(ray.z))


def worm_camera(scene):
    scene.frame_set(86)
    position = scene.camera.location
    distance = (Vector((position.x, position.y)) - Vector((-45, 75))).length
    assert 0 < position.z <= 1, 'Camera must be at ground level, at most one unit high'
    assert distance < 150, 'Camera must be near landing mark, below 150-unit stand-off'
    assert elevation(scene, 86) >= 20, 'Hold must look distinctly upward'


def upward_reveal(scene):
    values = [elevation(scene, frame) for frame in range(44, 64)]
    assert values[-1] - values[0] >= 15, 'Zoom must reveal at least 15 degrees of upward tilt'
    assert all(b >= a - 1e-4 for a, b in zip(values, values[1:])), 'Reveal must tilt steadily upward'
    assert abs(elevation(scene, 86) - values[-1]) < 1e-4, 'Tilt must settle by frame 63'


def framing(scene):
    meshes = [obj for obj in scene.objects if obj.name.startswith('BK |') and obj.type == 'MESH']
    report = {}
    for frame in [40, *range(44, 109)]:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        points = [world_to_camera_view(scene, scene.camera, obj.matrix_world @ Vector(corner))
                  for obj in meshes for corner in obj.bound_box]
        bounds = [min(p.x for p in points), min(p.y for p in points),
                  max(p.x for p in points), max(p.y for p in points)]
        assert min(p.z for p in points) > 0, ('Actor behind camera', frame)
        assert min(bounds[:2]) > .015 and max(bounds[2:]) < .985, ('Beetle cropped', frame, bounds)
        if frame in [40, 52, 58, 63, 86]:
            report[frame] = bounds
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--take', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--negative-checks', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    negative = []

    def reject(check, label):
        try:
            check()
        except AssertionError as error:
            negative.append({'mutation': label, 'assertion': str(error)})
        else:
            raise AssertionError(f'Negative check did not discriminate: {label}')

    bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()))
    source = bpy.context.scene
    original_action_name = source.camera.animation_data.action.name
    expected = locked_state(source, source.camera)
    expected_lenses = lenses(source)
    expected_world = world_state(source)
    if args.negative_checks:
        reject(lambda: worm_camera(source), 'Unfixed T312 B camera')
        reject(lambda: upward_reveal(source), 'Unfixed T312 B tilt')
    bpy.ops.wm.open_mainfile(filepath=str(args.take.resolve()))
    scene = bpy.context.scene
    assert locked_state(scene, scene.camera, bpy.data.actions.get(original_action_name)) == expected, 'Actor/dust animation changed'
    assert lenses(scene) == expected_lenses, 'Original focal curve changed'
    assert world_state(scene) == expected_world, 'HDRI environment changed'
    foliage(scene)
    scene.frame_set(1)
    empty_start(scene)
    worm_camera(scene)
    upward_reveal(scene)
    bounds = framing(scene)
    if args.negative_checks:
        scene.frame_set(1)
        saved_rotation = scene.camera.rotation_quaternion.copy()
        try:
            scene.camera.rotation_quaternion = (Vector((-380, 75, 50)) - scene.camera.location).to_track_quat('-Z', 'Y')
            reject(lambda: empty_start(scene), 'Aim opening at waiting actor')
        finally:
            scene.camera.rotation_quaternion = saved_rotation
        empty_start(scene)
        # Optical negative control: restore the old sensor while retaining
        # the close camera. The full-body assertion must reject this crop.
        saved_sensor = scene.camera.data.sensor_width
        try:
            scene.camera.data.sensor_width = 36
            reject(lambda: framing(scene), 'Restore old narrow field of view at the feet')
        finally:
            scene.camera.data.sensor_width = saved_sensor
        framing(scene)
    args.output.write_text(json.dumps({
        'status': 'PASS', 'source': str(args.source.resolve()), 'take': str(args.take.resolve()),
        'exact_lens_frames_compared': 108, 'locked_state_sha256': expected,
        'environment': expected_world, 'framing': bounds,
        'elevation_degrees': {f: elevation(scene, f) for f in [1, 40, 44, 52, 58, 63, 86]},
        'camera_position': list(scene.camera.location), 'sensor_width': scene.camera.data.sensor_width,
        'negative_checks': negative,
        'pixel_review': 'Review graded frames 52/58/63 separately for lens occlusion; state checks cannot establish this.',
    }, indent=2))
    print('TAKE3_VERIFIED', args.take, flush=True)


if __name__ == '__main__':
    main()
