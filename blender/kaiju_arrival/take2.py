"""Derive T312 camera/environment previews from the approved, baked T311 master.

Run in Blender 5.1.2. Never rebuild the actor or dust animation for this task.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


TAKES = {
    'A': {'label': 'Low classic', 'position': (130, -340, 9)},
    'B': {'label': 'Ground hero', 'position': (95, -325, 4), 'target_lift': 3},
    'C': {'label': 'Low oblique', 'position': (180, -385, 7), 'opening_target_x': 35},
}


def locked_state(scene, camera, original_camera_action=None):
    """All evaluated noncamera transforms, plus every noncamera animation curve."""
    excluded = {camera.animation_data.action} if camera.animation_data else set()
    excluded.add(original_camera_action)
    result = {'transforms': [], 'actions': []}
    for frame in range(1, 109):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        result['transforms'].append([
            (obj.name, [list(row) for row in obj.matrix_world], obj.hide_render)
            for obj in sorted(scene.objects, key=lambda item: item.name) if obj != camera
        ])
    for action in sorted(bpy.data.actions, key=lambda item: item.name):
        if action in excluded:
            continue
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        result['actions'].append((action.name, curve.data_path, curve.array_index,
                            [(list(k.co), k.interpolation) for k in curve.keyframe_points]))
    return hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--hdri', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--take', choices=TAKES, required=True)
    parser.add_argument('--rotation', type=float, default=250)
    parser.add_argument('--horizon-scale', type=float, default=2)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    assert args.output.resolve() != args.source.resolve().parent, 'Use a fresh output directory'
    assert hashlib.md5(args.hdri.read_bytes()).hexdigest() == 'a85297dfe6a1bbb2881c835cef24f1e4'
    args.output.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()))
    scene = bpy.context.scene
    camera = scene.camera
    locked_before = locked_state(scene, camera)
    lenses, targets = [], []
    for frame in range(1, 109):
        scene.frame_set(frame)
        lenses.append(camera.data.lens)
        # Recover the approved tracking target, including the brief impact recoil.
        track = max(0, min(1, (frame - 44) / 16))
        target_y = 108 + (75 - 108) * track
        ray = camera.rotation_quaternion @ Vector((0, 0, -1))
        targets.append(camera.location + ray * ((target_y - camera.location.y) / ray.y))
    # Retain the approved transform action (which has a fake user) and edit a copy.
    # The camera-data lens action is untouched.
    original_camera_action = camera.animation_data.action
    camera.animation_data.action = original_camera_action.copy()
    camera.location = TAKES[args.take]['position']
    for frame, target in enumerate(targets, 1):
        scene.frame_set(frame)
        target.z += TAKES[args.take].get('target_lift', 0)
        # The wider C station otherwise reveals a sliver of the waiting actor.
        # A gentle opening pan reaches the approved target before the fast zoom.
        target.x += TAKES[args.take].get('opening_target_x', 0) * max(0, (44 - frame) / 43)
        camera.rotation_quaternion = (target - camera.location).to_track_quat('-Z', 'Y')
        camera.keyframe_insert(data_path='rotation_quaternion', frame=frame)
        assert camera.data.lens == lenses[frame - 1], 'Approved lens curve changed'
    for layer in camera.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for point in curve.keyframe_points:
                        point.interpolation = 'LINEAR'
    # One natural panorama provides both lighting and the camera background.
    world = scene.world.copy()
    scene.world = world
    nodes, links = world.node_tree.nodes, world.node_tree.links
    nodes.clear()
    coord = nodes.new('ShaderNodeTexCoord')
    mapping = nodes.new('ShaderNodeMapping')
    mapping.inputs['Rotation'].default_value.z = math.radians(args.rotation)
    # Reduce the photographed trees' angular height to read as distant foliage
    # behind a giant suit monster, while retaining a level natural horizon.
    mapping.inputs['Scale'].default_value.z = args.horizon_scale
    environment = nodes.new('ShaderNodeTexEnvironment')
    environment.name = 'T312 | natural quarry foliage'
    environment.image = bpy.data.images.load(str(args.hdri.resolve()), check_existing=True)
    background = nodes.new('ShaderNodeBackground')
    background.inputs['Strength'].default_value = .3
    output = nodes.new('ShaderNodeOutputWorld')
    links.new(coord.outputs['Generated'], mapping.inputs['Vector'])
    links.new(mapping.outputs['Vector'], environment.inputs['Vector'])
    links.new(environment.outputs['Color'], background.inputs['Color'])
    links.new(background.outputs[0], output.inputs['Surface'])
    assert locked_state(scene, camera, original_camera_action) == locked_before, 'Noncamera motion or animation changed'
    for image in bpy.data.images:
        if image.filepath:
            image.filepath = bpy.path.abspath(image.filepath)
    scene['shot'] = f'Beetle arrival T312 preview {args.take}: {TAKES[args.take]["label"]}'
    scene['take2_source_sha256'] = source_hash
    scene['take2_locked_state_sha256'] = locked_before
    scene['take2_hdri'] = 'https://polyhaven.com/a/old_quarry_gerlingen (Andreas Mischok, CC0)'
    scene.frame_set(86)
    bpy.context.preferences.filepaths.save_version = 0
    destination = args.output / f'take_{args.take}.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(destination))
    assert hashlib.sha256(args.source.read_bytes()).hexdigest() == source_hash
    (args.output / 'manifest.json').write_text(json.dumps({
        'take': args.take, **TAKES[args.take], 'blend': str(destination.resolve()),
        'source': str(args.source.resolve()), 'source_sha256': source_hash,
        'locked_state_sha256': locked_before, 'lens_by_frame': lenses,
        'hdri': str(args.hdri.resolve()), 'hdri_rotation_degrees': args.rotation,
        'hdri_elevation_scale': args.horizon_scale,
        'hdri_sha256': hashlib.sha256(args.hdri.read_bytes()).hexdigest(),
        'hdri_url': scene['take2_hdri'], 'approval': 'PREVIEW ONLY; final render awaits Devin pick',
    }, indent=2))
    print('TAKE2_BUILD_COMPLETE', args.take, flush=True)


if __name__ == '__main__':
    main()
