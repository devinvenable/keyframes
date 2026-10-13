"""Render camera-visible category masks, including actual surface occlusion.

The graded beauty stills remain the aesthetic/dust-density gate. These masks
test whether the subjects/debris have any visible pixels, not just 3D bounds.
"""
import argparse
import json
from pathlib import Path
import sys
import bpy
import numpy as np

COLORS = {'beetle':(1,0,0,1), 'face':(1,0,1,1), 'rock':(0,1,0,1),
          'fragment':(0,0,1,1), 'robot':(1,1,0,1), 'set':(0,0,0,1)}


def check(rows):
    for frame in (1,22,43,84):
        row = rows[str(frame)]
        assert row['beetle'] > 1700, f'Beetle occluded at {frame}'
        assert row['face'] > 15, f'Face occluded at {frame}'
        assert row['rock'] > 1200, f'Rock stack does not read at {frame}'
    assert rows['1']['fragment'] == 0 and rows['22']['fragment'] == 0, 'Debris visible before rock impact'
    assert rows['43']['fragment'] > 35, 'Collision fragments do not read'
    assert rows['1']['robot'] > 500, 'Robot absent at first contact'
    assert rows['43']['robot'] == 0 and rows['84']['robot'] == 0, 'Robot remains in frame'


def main(a):
    s = bpy.context.scene
    materials = {}
    for name, color in COLORS.items():
        mat=bpy.data.materials.new('QA | '+name); mat.use_nodes=True
        n=mat.node_tree.nodes; n.clear()
        emission=n.new('ShaderNodeEmission'); emission.inputs[0].default_value=color
        output=n.new('ShaderNodeOutputMaterial'); mat.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])
        materials[name]=mat
    for o in s.objects:
        if o.type == 'LIGHT': o.hide_render=True
        if o.type != 'MESH': continue
        if o.name=='FogVolume' or o.name.startswith('Reaction | powder'):
            o.hide_render=True; continue
        group='set'
        if o.name.startswith('BK |'):
            group='face' if any(x in o.name for x in ('eye','drill','horn')) else 'beetle'
        elif o.name.startswith('Reaction | stack'): group='rock'
        elif o.name.startswith('Reaction | fragment'): group='fragment'
        elif o.name=='kaiju_robot_mesh' or o.name.startswith(('Booster ','Hatch ')): group='robot'
        o.data=o.data.copy(); o.data.materials.clear(); o.data.materials.append(materials[group])
    s.world=bpy.data.worlds.new('QA | black'); s.world.use_nodes=True
    s.world.node_tree.nodes['Background'].inputs[0].default_value=(0,0,0,1)
    s.render.engine='CYCLES'; s.cycles.samples=1; s.cycles.use_denoising=False
    prefs=bpy.context.preferences.addons['cycles'].preferences; prefs.compute_device_type='CUDA'; prefs.get_devices()
    for dev in prefs.devices: dev.use=dev.type=='CUDA' and '3060' in dev.name
    s.cycles.device='GPU'; s.render.resolution_percentage=25
    s.render.use_compositing=False; s.render.image_settings.file_format='PNG'
    s.view_settings.view_transform='Standard'; s.view_settings.look='None'; s.view_settings.exposure=0
    dest=a.directory/'pixel_masks'; dest.mkdir(exist_ok=True)
    rows={}
    for f in (1,22,43,84):
        s.frame_set(f); path=dest/f'frame_{f:04}.png'; s.render.filepath=str(path)
        bpy.ops.render.render(write_still=True)
        im=bpy.data.images.load(str(path)); pixels=np.array(im.pixels[:]).reshape(-1,4)
        rows[str(f)]={name:int(np.sum(np.max(np.abs(pixels[:,:3]-np.array(col[:3])),axis=1)<.08)) for name,col in COLORS.items()}
        bpy.data.images.remove(im)
    (a.directory/'pixel_counts.json').write_text(json.dumps(rows,indent=2)+'\n')
    check(rows)
    print('PIXEL_CONTRACT_PASS',json.dumps(rows))


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--directory',type=Path,required=True)
    main(p.parse_args(sys.argv[sys.argv.index('--')+1:]))
