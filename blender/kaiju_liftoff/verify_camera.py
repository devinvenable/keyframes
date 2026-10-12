"""Compare camera revision against the actual approved packed scene, not its builder."""
import argparse
from array import array
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def properties(data):
    result = {}
    for prop in data.bl_rna.properties:
        if prop.identifier in {'session_uid', 'users', 'tag', 'is_updated', 'is_updated_data'}:
            continue
        if prop.type in {'BOOLEAN', 'INT', 'FLOAT', 'STRING', 'ENUM'}:
            value = getattr(data, prop.identifier)
            if getattr(prop, 'is_array', False):
                value = list(value)
            if isinstance(value, set):
                value = sorted(value)
            result[prop.identifier] = value
    return result


def snapshot(path):
    if path is not None:
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    scene.frame_set(1)
    camera = scene.camera
    actions = {}
    for action in bpy.data.actions:
        if action == camera.animation_data.action:
            continue
        actions[action.name] = [
            (curve.data_path, curve.array_index,
             [(list(k.co), list(k.handle_left), list(k.handle_right), k.interpolation)
              for k in curve.keyframe_points])
            for layer in action.layers for strip in layer.strips
            for bag in strip.channelbags for curve in bag.fcurves]
    geometry = {}
    for mesh in bpy.data.meshes:
        coords = array('f', [0]) * (len(mesh.vertices)*3)
        mesh.vertices.foreach_get('co', coords)
        loops = array('i', [0]) * len(mesh.loops)
        mesh.loops.foreach_get('vertex_index', loops)
        geometry[mesh.name] = hashlib.sha256(coords.tobytes()+loops.tobytes()).hexdigest()
    materials = {}
    for mat in bpy.data.materials:
        tree = mat.node_tree
        materials[mat.name] = (properties(mat), None if not tree else {
            'nodes': [(properties(n), [(i.name, list(i.default_value)
                       if hasattr(i.default_value, '__len__') and not isinstance(i.default_value, str)
                       else i.default_value) for i in n.inputs
                       if hasattr(i, 'default_value') and i.type != 'OBJECT']) for n in tree.nodes],
            'links': [(l.from_node.name, l.from_socket.identifier,
                       l.to_node.name, l.to_socket.identifier) for l in tree.links]})
    static = {'actions': digest(actions), 'geometry': geometry,
              'materials': digest(materials),
              'lights': {l.name: properties(l) for l in bpy.data.lights},
              'camera_data': properties(camera.data),
              'render': properties(scene.render), 'cycles': properties(scene.cycles),
              'view': properties(scene.view_settings),
              'images': [(im.name, None if im.packed_file else bpy.path.abspath(im.filepath),
                          hashlib.sha256(im.packed_file.data).hexdigest() if im.packed_file else None)
                         for im in bpy.data.images if im.users > 0]}
    camera_samples = []
    other_samples = []
    for frame in range(1, 218):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        camera_samples.append([list(row) for row in camera.matrix_world])
        objects = {o.name: ([list(row) for row in o.matrix_world], o.hide_render,
                           o.visible_camera,
                           [[list(row) for row in b.matrix] for b in o.pose.bones]
                           if o.type == 'ARMATURE' else None)
                   for o in scene.objects if o != camera}
        other_samples.append(digest(objects))
    # Check subframes too: no pre-ignition interpolation drift is permitted.
    lock_samples = []
    for quarter in range(4, 445):
        scene.frame_set(quarter // 4, subframe=(quarter % 4)/4)
        lock_samples.append([list(row) for row in camera.matrix_world])
    return static, other_samples, camera_samples, lock_samples


def verify(baseline, candidate):
    static, other, cameras, locked = candidate
    old_static, old_other, old_cameras, old_locked = baseline
    assert static == old_static, 'Non-camera data/settings changed: ' + str([
        key for key in static if static[key] != old_static[key]])
    assert other == old_other, 'Non-camera evaluated animation changed'
    lock_error = max(abs(x-y) for a, b in zip(locked, old_locked)
                     for row_a, row_b in zip(a, b) for x, y in zip(row_a, row_b))
    assert lock_error < 1e-6, f'Approved camera window changed: {lock_error}'
    positions = [Matrix(m).translation for m in cameras]
    steps = [(b-a).length for a, b in zip(positions, positions[1:])]
    accel = [(positions[i+1]-2*positions[i]+positions[i-1]).length
             for i in range(1, len(positions)-1)]
    rotations = [Matrix(m).to_quaternion() for m in cameras]
    turns = [a.rotation_difference(b).angle for a, b in zip(rotations, rotations[1:])]
    assert positions[-1].z - positions[110].z > 15, 'Camera never cranes upward'
    assert positions[-1].x - positions[110].x < -50, 'Camera never sweeps left'
    assert min(steps) > .02 and max(steps) < 2, 'Frozen or discontinuous camera'
    assert max(accel) < .07, 'Camera acceleration is discontinuous'
    assert max(turns) < .025, 'Camera orientation jumps'
    assert max(steps[-12:]) < .12, 'Camera fails to settle into its final glide'
    # At 12 mm / 36 mm horizontal sensor / 16:9, the bottom-center ray
    # must look above the horizon once the crane leaves the shallow fog.
    bottom_rays = [(Matrix(m).to_quaternion() @ Vector((0, -10.125, -12))).normalized().z
                   for m, pos in zip(cameras, positions) if pos.z > 8]
    assert min(bottom_rays) > 0, 'Crane exposes the flat fog/set boundary'
    return {'status': 'PASS', 'lock_frames': [1, 111], 'lock_quarter_frames': len(locked),
            'lock_matrix_max_error': lock_error, 'non_camera_frames_identical': len(other),
            'non_camera_data_identical': sorted(static),
            'camera_min_step': min(steps), 'camera_max_step': max(steps),
            'camera_max_acceleration': max(accel), 'camera_max_turn_radians': max(turns),
            'final_glide_max_step': max(steps[-12:]),
            'elevated_camera_bottom_ray_min_z': min(bottom_rays),
            'camera_start': list(positions[0]), 'camera_end': list(positions[-1])}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--negative-controls', action='store_true')
    a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    baseline = snapshot(a.baseline)
    report = verify(baseline, snapshot(a.candidate))
    if a.negative_controls:
        failures = {}
        # Mutation is in memory only. Reload the exact candidate for each case;
        # neither the implementation files nor the saved scene are modified.
        for case in ['unfixed_camera', 'join_drift', 'changed_lift', 'camera_jump']:
            if case == 'unfixed_camera':
                broken = baseline
            else:
                bpy.ops.wm.open_mainfile(filepath=str(a.candidate), load_ui=False, use_scripts=False)
                scene = bpy.context.scene
                frame = 60 if case == 'join_drift' else 180
                scene.frame_set(frame)
                obj = (bpy.data.objects['Flight | lift and recoil']
                       if case == 'changed_lift' else scene.camera)
                obj.location.x += 20 if case == 'camera_jump' else 1
                obj.keyframe_insert(data_path='location', frame=frame)
                broken = snapshot(None)
            try:
                verify(baseline, broken)
            except AssertionError as error:
                failures[case] = str(error)
            else:
                raise AssertionError(f'Negative control incorrectly passed: {case}')
        report['negative_controls'] = failures
    report['baseline_sha256'] = hashlib.sha256(a.baseline.read_bytes()).hexdigest()
    report['candidate_sha256'] = hashlib.sha256(a.candidate.read_bytes()).hexdigest()
    a.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
