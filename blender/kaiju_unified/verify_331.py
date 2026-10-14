"""Post-smash close framing and exact preservation of the approved performance."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_330 import framing, centered, debris_floor
from verify_328 import mesh, parts, solidity, flight


def post_framing(frames=range(124, 193)):
    scene = bpy.context.scene
    rows = []
    for frame in frames:
        scene.frame_set(frame)
        points, head = [], []
        for obj in parts():
            projected = [world_to_camera_view(scene, scene.camera, v) for v in mesh(obj)[0]]
            points.extend(projected)
            if any(t in obj.name for t in ('helmet', 'eye', 'drill', 'horn', 'crown', 'mandible')):
                head.extend(projected)
        y0, y1 = min(v.y for v in points), max(v.y for v in points)
        height = y1 - y0
        crop = max(0, -y0) / height
        assert 1.85 <= height <= 2.3, f'Post-impact beetle too small or oversized at f{frame}: {height:.3f}'
        assert .43 <= crop <= .67, f'Post-impact crop outside tight band at f{frame}: {crop:.3f}'
        assert all(v.z > 0 and .01 < v.x < .99 and .01 < v.y < .99 for v in head), f'Post-impact head outside frame at f{frame}'
        assert max(0, y1 - 1) < .01, f'Post-impact top cropped at f{frame}'
        rows.append({'frame': frame, 'height': height, 'bottom_crop_fraction': crop,
                     'head_bounds': [min(v.x for v in head), min(v.y for v in head),
                                     max(v.x for v in head), max(v.y for v in head)]})
    return rows


def snapshot():
    scene = bpy.context.scene
    performance = hashlib.sha256()
    geometry = hashlib.sha256()
    objects = sorted((o for o in scene.objects if o != scene.camera), key=lambda o: o.name)
    for obj in objects:
        geometry.update(obj.name.encode())
        if obj.type == 'MESH':
            coords = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
            obj.data.vertices.foreach_get('co', coords)
            geometry.update(coords.tobytes())
    camera = []
    for frame in range(1, 193):
        scene.frame_set(frame)
        values = [v for obj in objects for row in obj.matrix_world for v in row]
        performance.update(np.asarray(values, dtype=np.float32).tobytes())
        performance.update(bytes(obj.hide_render for obj in objects))
        if frame <= 124:
            camera.append([v for row in scene.camera.matrix_world for v in row] +
                          [scene.camera.data.lens, scene.camera.data.shift_x, scene.camera.data.shift_y])
    return {'performance': performance.hexdigest(), 'geometry': geometry.hexdigest(), 'camera': camera}


def preserved(source):
    saved = bpy.data.filepath
    current = snapshot()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    baseline = snapshot()
    bpy.ops.wm.open_mainfile(filepath=saved)
    assert current['performance'] == baseline['performance'], 'Approved non-camera performance changed'
    assert current['geometry'] == baseline['geometry'], 'Approved scene geometry changed'
    error = float(np.max(np.abs(np.array(current['camera']) - np.array(baseline['camera']))))
    assert error < .00001, f'Approved camera through f124 changed: {error}'
    return {'performance_sha256': current['performance'], 'geometry_sha256': current['geometry'],
            'camera_max_error_f1_124': error}


def main(args):
    result = {'status': 'PASS', 'framing': framing(), 'post_impact_framing': post_framing(),
              'centered_contact': centered(), 'solidity': solidity(range(113, 193)),
              'airborne_speeds': flight(), 'debris_min_ground_clearance': debris_floor(),
              'preserved_round06': preserved(args.baseline)}
    if args.negative_checks:
        saved = bpy.data.filepath
        failures = {}
        def rejects(name, check, prefix):
            try:
                check()
            except AssertionError as error:
                assert str(error).startswith(prefix), f'Wrong negative assertion: {error}'
                failures[name] = str(error)
            else:
                raise AssertionError('Undetected negative: ' + name)
        bpy.ops.wm.open_mainfile(filepath=str(args.baseline))
        rejects('actual_round06_pullback', post_framing, 'Post-impact beetle too small')
        bpy.ops.wm.open_mainfile(filepath=saved)
        bpy.context.scene.camera.data.shift_y += .4
        rejects('post_impact_excessive_crop', post_framing, 'Post-impact crop outside')
        bpy.ops.wm.open_mainfile(filepath=saved)
        bpy.context.scene.camera.data.shift_x += 1
        rejects('post_impact_head_cropped', post_framing, 'Post-impact head outside')
        bpy.ops.wm.open_mainfile(filepath=saved)
        scene = bpy.context.scene
        scene.frame_set(192)
        scene.camera.data.lens = 20
        scene.camera.data.keyframe_insert(data_path='lens', frame=192)
        rejects('final_frame_opens_out', lambda: post_framing(range(192, 193)), 'Post-impact beetle too small')
        bpy.ops.wm.open_mainfile(filepath=saved)
        scene = bpy.context.scene
        scene.frame_set(148)
        root = bpy.data.objects['BK | ROOT | placement']
        root.location.x += 1
        root.keyframe_insert(data_path='location', frame=148)
        rejects('changed_slide_pose', lambda: preserved(args.baseline), 'Approved non-camera performance changed')
        bpy.ops.wm.open_mainfile(filepath=saved)
        scene = bpy.context.scene
        scene.frame_set(124)
        scene.camera.location.x += 1
        scene.camera.keyframe_insert(data_path='location', frame=124)
        rejects('changed_approved_camera', lambda: preserved(args.baseline), 'Approved camera through f124 changed')
        bpy.ops.wm.open_mainfile(filepath=saved)
        obj = next(o for o in parts() if len(o.data.vertices))
        obj.data.vertices[0].co.x += 1
        rejects('changed_geometry', lambda: preserved(args.baseline), 'Approved scene geometry changed')
        bpy.ops.wm.open_mainfile(filepath=saved)
        result['negative_controls'] = failures
        result['negative_round06_sha256'] = hashlib.sha256(args.baseline.read_bytes()).hexdigest()
    (args.directory / 'revision_qa.json').write_text(json.dumps(result, indent=2) + '\n')
    print('LOCKED_CAMERA_QA', json.dumps({k: v for k, v in result.items() if k not in ('solidity', 'framing', 'post_impact_framing')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--negative-checks', action='store_true')
    main(parser.parse_args(sys.argv[sys.argv.index('--') + 1:]))
