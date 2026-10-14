"""Extend the approved round-06 beetle-relative camera through the settle."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
from revise_328 import key
from verify_328 import parts, mesh


def revise(source, output):
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    scene = bpy.context.scene
    camera = scene.camera
    root = bpy.data.objects['BK | ROOT | placement']
    scene.frame_set(124)
    offset = camera.location - root.location
    rotation = camera.rotation_quaternion.copy()
    lens = camera.data.lens
    neck = bpy.data.objects['BK | neck']
    head_at_hit = (neck.matrix_world @ Vector((0, 0, 10))).copy()
    root_at_hit = root.location.copy()
    up = rotation @ Vector((0, 1, 0))
    forward = rotation @ Vector((0, 0, -1))
    def bounds():
        projected = []
        head = []
        for obj in parts():
            points = [world_to_camera_view(scene, camera, v) for v in mesh(obj)[0]]
            projected.extend(points)
            if any(t in obj.name for t in ('helmet', 'eye', 'drill', 'horn', 'crown', 'mandible')):
                head.extend(points)
        return (max(v.y for v in projected) - min(v.y for v in projected),
                (min(v.y for v in head) + max(v.y for v in head)) / 2)
    target_height, target_head_y = bounds()
    # Preserve every key through the smash. Follow the root down the rock at
    # a close distance and fixed orientation. Track the helmet's hinged slump
    # as well as the root's slide, so its face never falls below the close frame.
    for frame in range(125, 193):
        scene.frame_set(frame)
        pose_shift = (neck.matrix_world @ Vector((0, 0, 10))) - root.location - (head_at_hit - root_at_hit)
        camera.location = root.location + offset + pose_shift
        camera.rotation_quaternion = rotation
        camera.data.lens = lens
        # A crumpled body is shorter. Ease closer with the pose rather than
        # allowing the subject to shrink; keep the head centered vertically.
        for _ in range(12):
            bpy.context.view_layer.update()
            height, head_y = bounds()
            depth = ((neck.matrix_world @ Vector((0, 0, 10))) - camera.location).dot(forward)
            camera.location += forward * depth * (1 - height / target_height) * .6
            frame_height = depth * camera.data.sensor_width / lens * scene.render.resolution_y / scene.render.resolution_x
            camera.location += up * (head_y - target_head_y) * frame_height * .8
        key(camera, 'location', camera.location, frame)
        key(camera, 'rotation_quaternion', rotation, frame)
        key(camera.data, 'lens', lens, frame)
    scene['shot'] = 'T331 round_07 close tracking through crash, slide and settle; draft gate pending'
    scene.frame_set(124)
    bpy.context.preferences.filepaths.save_version = 0
    destination = output / 'unified.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(destination))
    manifest = json.loads((source.parent / 'manifest.json').read_text())
    manifest.update(revision_source=str(source),
                    revision_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    scene_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                    camera_follow_offset=list(offset), revision=331,
                    draft_range=[100, 192], final_approved=False)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('LOCKED_CAMERA', list(offset), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    revise(args.source, args.output)
