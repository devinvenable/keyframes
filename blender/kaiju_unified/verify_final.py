"""Hash all approved transforms, geometry and camera frames without saving."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_331 import snapshot


def capture():
    result = snapshot()
    camera = []
    scene = bpy.context.scene
    for frame in range(1, 193):
        scene.frame_set(frame)
        camera.append([v for row in scene.camera.matrix_world for v in row] +
                      [scene.camera.data.lens, scene.camera.data.shift_x, scene.camera.data.shift_y])
    result.pop('camera')
    result['camera_f1_192'] = hashlib.sha256(np.asarray(camera, dtype=np.float32).tobytes()).hexdigest()
    return result


def compare(current, baseline):
    for key in baseline:
        assert current[key] == baseline[key], 'Approved round_07 changed: ' + key


def main(args):
    current = capture()
    bpy.ops.wm.open_mainfile(filepath=str(args.baseline))
    baseline = capture()
    compare(current, baseline)
    negatives = {}
    # In-memory mutations, never saved to either source or final scene.
    saved = bpy.data.filepath
    for kind in ('performance', 'geometry', 'camera_f1_192'):
        bpy.ops.wm.open_mainfile(filepath=saved)
        scene = bpy.context.scene
        scene.frame_set(192)
        if kind == 'geometry':
            obj = next(o for o in scene.objects if o.type == 'MESH' and len(o.data.vertices))
            obj.data.vertices[0].co.x += 1
        else:
            obj = scene.camera if kind == 'camera_f1_192' else bpy.data.objects['BK | ROOT | placement']
            obj.location.x += 1
            obj.keyframe_insert(data_path='location', frame=192)
        try:
            compare(capture(), baseline)
        except AssertionError as error:
            assert str(error) == 'Approved round_07 changed: ' + kind, str(error)
            negatives[kind] = str(error)
        else:
            raise AssertionError('Undetected parity mutation: ' + kind)
    bpy.ops.wm.open_mainfile(filepath=saved)
    compare(capture(), baseline)
    args.output.write_text(json.dumps({'status': 'PASS', 'hashes': current,
                                      'negative_controls': negatives}, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args(sys.argv[sys.argv.index('--') + 1:]))
