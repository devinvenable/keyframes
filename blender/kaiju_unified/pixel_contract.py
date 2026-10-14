"""Occlusion-aware rendered-pixel gate; beauty frames carry aesthetic review."""
import argparse
import json
from pathlib import Path
import sys
import bpy
import numpy as np

COLORS={'beetle':(1,0,0,1),'face':(1,0,1,1),'rock':(0,1,0,1),'fragment':(0,0,1,1),'robot':(1,1,0,1),'set':(0,0,0,1)}
FRAMES=(64,106,112,123,124,130,148,180)


def check(rows):
    for f in (106,112,123,124,130,148,180):
        assert rows[str(f)]['beetle']>1300, f'Beetle obscured at {f}'
        assert rows[str(f)]['face']>12, f'Face obscured at {f}'
        assert rows[str(f)]['rock']>1000, f'Cliff absent at {f}'
    assert rows['64']['rock']>100, 'Collision cliff missing from dive'
    assert rows['123']['fragment']==0, 'Fragments visible before contact'
    assert rows['124']['fragment']>12, 'Fragments invisible at contact'
    assert rows['130']['fragment']>35, 'Debris burst invisible'
    assert rows['124']['robot_in_action']<300, 'Robot hides rock smash'


def check_slide(visible, unobstructed):
    ratio=(visible['beetle']+visible['face'])/(unobstructed['beetle']+unobstructed['face'])
    assert ratio>.95, f'Rock hides beetle during slide: only {ratio:.3%} of unobstructed pixels visible'
    return ratio


def main(a):
    s=bpy.context.scene; materials={}; fragments=[]
    for name,color in COLORS.items():
        mat=bpy.data.materials.new('QA | '+name); mat.use_nodes=True; n=mat.node_tree.nodes; n.clear()
        emission=n.new('ShaderNodeEmission'); emission.inputs[0].default_value=color
        out=n.new('ShaderNodeOutputMaterial'); mat.node_tree.links.new(emission.outputs[0],out.inputs['Surface']); materials[name]=mat
    for o in s.objects:
        if o.type=='LIGHT': o.hide_render=True
        if o.type!='MESH': continue
        if o.name=='FogVolume' or o.name.startswith('Reaction | powder'): o.hide_render=True; continue
        group='set'
        if o.name.startswith('BK |'): group='face' if any(x in o.name for x in ('eye','drill','horn')) else 'beetle'
        elif o.name.startswith('Reaction | stack'): group='rock'
        elif o.name.startswith('Reaction | fragment'): group='fragment'; fragments.append(o)
        elif o.name=='kaiju_robot_mesh' or o.name.startswith(('Booster ','Hatch ')): group='robot'
        o.data=o.data.copy(); o.data.materials.clear(); o.data.materials.append(materials[group])
    s.world=bpy.data.worlds.new('QA | black'); s.world.use_nodes=True; s.world.node_tree.nodes['Background'].inputs[0].default_value=(0,0,0,1)
    s.render.engine='CYCLES'; s.cycles.samples=1; s.cycles.use_denoising=False
    prefs=bpy.context.preferences.addons['cycles'].preferences; prefs.compute_device_type='CUDA'; prefs.get_devices()
    for dev in prefs.devices: dev.use=dev.type=='CUDA' and '3060' in dev.name
    s.cycles.device='GPU'; s.render.resolution_percentage=25; s.render.use_compositing=False; s.render.image_settings.file_format='PNG'
    s.view_settings.view_transform='Standard'; s.view_settings.look='None'; s.view_settings.exposure=0
    dest=a.directory/'pixel_masks'; dest.mkdir(exist_ok=True)
    def render(f,suffix=''):
        s.frame_set(f); path=dest/f'frame_{f:04}{suffix}.png'; s.render.filepath=str(path); bpy.ops.render.render(write_still=True)
        im=bpy.data.images.load(str(path)); pixels=np.array(im.pixels[:]).reshape(-1,4); bpy.data.images.remove(im)
        row={name:int(np.sum(np.max(np.abs(pixels[:,:3]-np.array(col[:3])),axis=1)<.08)) for name,col in COLORS.items()}
        rgb=pixels.reshape(270,480,4)[:,144:336,:3]
        row['robot_in_action']=int(np.sum(np.max(np.abs(rgb-np.array(COLORS['robot'][:3])),axis=2)<.08))
        return row
    rows={str(f):render(f) for f in ((148,) if a.slide_only else FRAMES)}
    rocks=[o for o in s.objects if o.type=='MESH' and (o.name.startswith('Reaction | stack') or o.name.startswith('model.'))]
    for o in rocks: o.hide_render=True
    unobstructed=render(148,'_without_sandstone')
    for o in rocks: o.hide_render=False
    (a.directory/'pixel_counts.json').write_text(json.dumps(rows,indent=2)+'\n')
    ratio=check_slide(rows['148'],unobstructed)
    if not a.slide_only: check(rows)
    result={'status':'PASS','rows':rows}
    result['slide_visible_fraction']=ratio
    result['slide_without_sandstone']=unobstructed
    if a.negative_checks:
        for o in fragments: o.hide_render=True
        bad=dict(rows); bad['124']=render(124,'_negative_late_fragments')
        try: check(bad)
        except AssertionError as e:
            assert str(e)=='Fragments invisible at contact', f'Wrong negative assertion: {e}'
            result['negative_rendered_late_debris']=str(e)
        else: raise AssertionError('Missing rendered fragments passed')
        for o in fragments: o.hide_render=False
        check(rows)
    (a.directory/'pixel_qa.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PIXEL_QA',json.dumps(result),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--directory',type=Path,required=True); p.add_argument('--negative-checks',action='store_true')
    p.add_argument('--slide-only',action='store_true')
    main(p.parse_args(sys.argv[sys.argv.index('--')+1:]))
