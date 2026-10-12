"""Compare a saved T312 take with T311, including discriminating negative checks."""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from take2 import locked_state


def lenses(scene):
    values = []
    for frame in range(1, 109):
        scene.frame_set(frame)
        values.append(scene.camera.data.lens)
    return values


def low_camera(scene):
    camera = scene.camera
    assert 0 < camera.location.z <= 9, 'Camera must be lowered from original height 26'
    for frame in range(1, 109):
        scene.frame_set(frame)
        ray = camera.rotation_quaternion @ Vector((0, 0, -1))
        assert ray.z > 0, 'Camera must look upward throughout the shot'


def foliage(scene):
    nodes = scene.world.node_tree.nodes
    environment = nodes.get('T312 | natural quarry foliage')
    assert environment is not None, 'Natural foliage environment is absent'
    assert environment.image.name.startswith('old_quarry_gerlingen_4k'), 'Wrong HDRI'
    backgrounds = [link.to_node for link in environment.outputs['Color'].links]
    assert any(node.type == 'BACKGROUND' and any(
        link.to_node.type == 'OUTPUT_WORLD' for link in node.outputs[0].links
    ) for node in backgrounds), 'Natural environment must feed the visible world directly'


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
            raise AssertionError(f'Negative check failed to discriminate: {label}')

    bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()))
    source = bpy.context.scene
    original_action_name = source.camera.animation_data.action.name
    expected_state = locked_state(source, source.camera)
    expected_lenses = lenses(source)
    if args.negative_checks:
        reject(lambda: low_camera(source), 'Unmodified T311 camera')
        reject(lambda: foliage(source), 'Unmodified T311 sky-only environment')

    bpy.ops.wm.open_mainfile(filepath=str(args.take.resolve()))
    scene = bpy.context.scene
    original_action = bpy.data.actions[original_action_name]

    def motion():
        assert locked_state(scene, scene.camera, original_action) == expected_state, 'Noncamera transforms or animation differ from T311'

    def zoom():
        assert lenses(scene) == expected_lenses, 'Lens curve differs from approved T311 on one or more frames'

    low_camera(scene)
    foliage(scene)
    motion()
    zoom()
    if args.negative_checks:
        root = bpy.data.objects['BK | ROOT | placement']
        scale = root.scale.copy()
        try:
            root.scale *= 1.1
            reject(motion, 'Alter actor scale without changing timing')
        finally:
            root.scale = scale
        motion()
        # Mutate the exact camera-data lens curve, restore every coordinate in memory.
        curves = [curve for layer in scene.camera.data.animation_data.action.layers
                  for strip in layer.strips for bag in strip.channelbags
                  for curve in bag.fcurves if curve.data_path == 'lens']
        assert len(curves) == 1, 'Lens mutation must have a unique target'
        points = curves[0].keyframe_points
        saved = [point.co.copy() for point in points]
        try:
            for point in points:
                point.co.y = 32
            curves[0].update()
            reject(zoom, 'Remove approved zoom')
        finally:
            for point, value in zip(points, saved):
                point.co = value
            curves[0].update()
        zoom()
    scene.frame_set(86)
    ray = scene.camera.rotation_quaternion @ Vector((0, 0, -1))
    args.output.write_text(json.dumps({
        'status': 'PASS', 'source': str(args.source.resolve()), 'take': str(args.take.resolve()),
        'locked_state_sha256': expected_state, 'exact_lens_frames_compared': 108,
        'camera_height': scene.camera.location.z,
        'upward_angle_at_86_degrees': math.degrees(math.asin(ray.z)),
        'negative_checks': negative,
        'pixel_review': 'Required separately; state checks cannot establish visible foliage or unoccluded contact',
    }, indent=2))
    print('TAKE2_VERIFIED', args.take, flush=True)


if __name__ == '__main__':
    main()
