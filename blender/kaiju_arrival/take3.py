"""T313 ground-level previews derived from the saved T312 B scene.

PM authorized the wider sensor on 2026-10-12: the new feet-level perspective
supersedes the old field of view. The exact focal animation remains intact.
"""
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


TAKES = {
    'A': {'label': 'Ground approach', 'position': (5, -35, 1),
          'sensor_width': 130, 'opening_elevation': 4, 'hold_elevation': 24},
    'B': {'label': 'At the feet', 'position': (-15, -5, .7),
          'sensor_width': 160, 'opening_elevation': 13, 'hold_elevation': 29},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--take', choices=TAKES, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    config = TAKES[args.take]
    destination = args.output / f'take_{args.take}.blend'
    assert destination.resolve() != args.source.resolve(), 'Source must remain untouched'
    args.output.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()))
    scene = bpy.context.scene
    camera = scene.camera
    # Retain even legacy, unused shader actions across another save/reload.
    # Blender otherwise purges them, defeating the exact archive comparison.
    for action in bpy.data.actions:
        action.use_fake_user = True
    locked_before = locked_state(scene, camera)
    lenses = []
    for frame in range(1, 109):
        scene.frame_set(frame)
        lenses.append(camera.data.lens)
    original_action = camera.animation_data.action
    camera.animation_data.action = original_action.copy()
    camera.data.sensor_width = config['sensor_width']
    camera.location = config['position']
    for frame in range(1, 109):
        scene.frame_set(frame)
        t = max(0, min(1, (frame - 44) / 19))
        smooth = t * t * (3 - 2 * t)
        elevation = config['opening_elevation'] + smooth * (
            config['hold_elevation'] - config['opening_elevation'])
        # Complete the horizontal pan at contact, while the upward reveal
        # continues through the last zoom key. Position stays on its tripod.
        pan = max(0, min(1, (frame - 20) / 32))
        pan = pan * pan * (3 - 2 * pan)
        target = Vector((20, 108, 0)).lerp(Vector((-45, 75, 0)), pan)
        horizontal = Vector((target.x - camera.location.x,
                             target.y - camera.location.y, 0)).normalized()
        ray = horizontal * math.cos(math.radians(elevation))
        ray.z = math.sin(math.radians(elevation))
        camera.rotation_quaternion = ray.to_track_quat('-Z', 'Y')
        camera.keyframe_insert(data_path='rotation_quaternion', frame=frame)
        assert camera.data.lens == lenses[frame - 1], 'Focal animation changed'
    for layer in camera.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for point in curve.keyframe_points:
                        point.interpolation = 'LINEAR'
    assert locked_state(scene, camera, original_action) == locked_before, 'Actor/dust state changed'
    scene['shot'] = f'T313 worm\'s-eye preview {args.take}: {config["label"]}'
    scene['take3_source_sha256'] = source_hash
    scene['take3_optical_change'] = 'Wider sensor authorized by pm-midi-1; original focal curve unchanged'
    for image in bpy.data.images:
        if image.filepath:
            image.filepath = bpy.path.abspath(image.filepath)
    scene.frame_set(86)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(destination.resolve()))
    assert hashlib.sha256(args.source.read_bytes()).hexdigest() == source_hash
    (args.output / 'manifest.json').write_text(json.dumps({
        'take': args.take, **config, 'source': str(args.source.resolve()),
        'source_sha256': source_hash, 'blend': str(destination.resolve()),
        'locked_state_sha256': locked_before, 'lens_by_frame': lenses,
        'optical_change': scene['take3_optical_change'],
        'equivalent_36mm_sensor_focal_range': [32 * 36 / config['sensor_width'], 72 * 36 / config['sensor_width']],
        'tilt_frames': [44, 63], 'dust_changes': 'None',
        'approval': 'PREVIEW ONLY; final render awaits Devin pick',
    }, indent=2))
    print('TAKE3_BUILD_COMPLETE', args.take, flush=True)


if __name__ == '__main__':
    main()
