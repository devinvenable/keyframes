"""Check saved T320 motion locks, live anticipation and first-contact endpoint."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector

spec = importlib.util.spec_from_file_location('final_scene', Path(__file__).with_name('final_scene.py'))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


def endpoint():
    s = bpy.context.scene
    rig = bpy.data.objects['actor_kaiju_robot']
    position = rig.location.copy()
    direction = Vector((-4.27764892578125, 3.589374542236328, -2.0020675659179688)).normalized()
    try:
        rig.location = position-direction*.01; bpy.context.view_layer.update()
        before = mod.contact_pairs()
        assert not before, f'Endpoint penetrates beetle: {before}'
        rig.location = position+direction*.01; bpy.context.view_layer.update()
        after = mod.contact_pairs()
        assert after, 'Endpoint stops short of contact'
        return after
    finally:
        rig.location = position; bpy.context.view_layer.update()


def terrain():
    ground = bpy.data.objects['GroundPlane']
    assert min(ground.dimensions[:2]) >= 70000, 'Finite square stage boundary remains'
    assert len(ground.data.vertices) > 10000, 'Missing distant relief'
    for loop in ground.data.loops:
        v = ground.data.vertices[loop.vertex_index].co
        uv = ground.data.uv_layers.active.data[loop.index].uv
        assert abs(uv.x-(v.x+3000)/600) < 1e-5 and abs(uv.y-(v.y+3000)/600) < 1e-5, 'Ground texture scale changed'


def main():
    p = argparse.ArgumentParser(); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--negative-checks', action='store_true')
    a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    s = bpy.context.scene
    manifest = json.loads(Path(bpy.data.filepath).with_name('scene_manifest.json').read_text())
    assert mod.fingerprint() == manifest['original_motion_before'], 'Original motion changed'
    terrain()
    rig = bpy.data.objects['actor_kaiju_robot']
    assert s.camera.parent == rig and s['arm_pose'] == 'swept'
    assert (s.frame_end, s.render.fps) == (manifest['continuation']['end_frame'], 24)
    reaction = []
    for f in range(96, s.frame_end+1):
        s.frame_set(f)
        for side in ('L', 'R'):
            sole = bpy.data.objects['BK | sole '+side]
            assert abs(min((sole.matrix_world @ Vector(c)).z for c in sole.bound_box)) < .05, 'Foot contact lost'
        reaction.append([list(bpy.data.objects['BK | '+n].rotation_euler) for n in ('waist', 'neck', 'shoulder L')])
        if f < s.frame_end:
            assert not mod.contact_pairs(), f'Premature contact at {f}'
    assert all(reaction[-1][i] != reaction[0][i] for i in range(3)), 'Frozen anticipation'
    report = {'status': 'PASS', 'first_contact_frame': s.frame_end, 'contact_objects': endpoint(),
              'original_96_frames_unchanged': True, 'terrain_uv_preserved': True,
              'reaction_samples': reaction, 'negative_controls': {}}
    if a.negative_checks:
        position = rig.location.copy()
        try:
            rig.location += Vector((10, -8, 4)); bpy.context.view_layer.update()
            try: endpoint()
            except AssertionError as e:
                assert str(e) == 'Endpoint stops short of contact'
                report['negative_controls']['short_endpoint'] = str(e)
            else: raise AssertionError('Short endpoint mutation passed')
        finally:
            rig.location = position; bpy.context.view_layer.update()
        endpoint()
        ground = bpy.data.objects['GroundPlane']; scale = ground.scale.copy()
        try:
            ground.scale = (.075, .075, 1); bpy.context.view_layer.update()
            try: terrain()
            except AssertionError as e:
                assert str(e) == 'Finite square stage boundary remains'
                report['negative_controls']['finite_stage'] = str(e)
            else: raise AssertionError('Finite stage mutation passed')
        finally:
            ground.scale = scale; bpy.context.view_layer.update()
        terrain()
    a.output.write_text(json.dumps(report, indent=2)+'\n')
    print('FINAL_SCENE_QA', report['status'], report['contact_objects'], report['negative_controls'])


if __name__ == '__main__': main()
