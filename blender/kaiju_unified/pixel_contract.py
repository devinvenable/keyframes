"""Occlusion-aware rendered-pixel gate; beauty frames carry aesthetic review."""
import argparse
import json
from pathlib import Path
import sys
import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

COLORS={'beetle':(1,0,0,1),'face':(1,0,1,1),'rock':(0,1,0,1),'fragment':(0,0,1,1),'robot':(1,1,0,1),'set':(0,0,0,1)}
FRAMES=(64,106,112,123,124,130,148,180,192)


def check(rows):
    for f in (106,112,123,124,130,148,180,192):
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


def check_flanks(row):
    assert min(row['rock_left_of_torso'],row['rock_right_of_torso'])>500, 'Rock does not flank both sides of torso'


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
    dest=a.directory/'pixel_masks'; dest.mkdir(parents=True,exist_ok=True)
    def render(f,suffix=''):
        s.frame_set(f); path=dest/f'frame_{f:04}{suffix}.png'; s.render.filepath=str(path); bpy.ops.render.render(write_still=True)
        im=bpy.data.images.load(str(path)); pixels=np.array(im.pixels[:]).reshape(-1,4); bpy.data.images.remove(im)
        row={name:int(np.sum(np.max(np.abs(pixels[:,:3]-np.array(col[:3])),axis=1)<.08)) for name,col in COLORS.items()}
        rgb=pixels.reshape(270,480,4)[:,144:336,:3]
        row['robot_in_action']=int(np.sum(np.max(np.abs(rgb-np.array(COLORS['robot'][:3])),axis=2)<.08))
        if f==124:
            torso=[world_to_camera_view(s,s.camera,o.matrix_world@Vector(c)) for o in s.objects
                   if o.name.startswith(('BK | abdomen','BK | elytron')) for c in o.bound_box]
            left=max(0,int(min(v.x for v in torso)*480)); right=min(480,int(max(v.x for v in torso)*480))
            bottom=max(0,int(min(v.y for v in torso)*270)); top=min(270,int(max(v.y for v in torso)*270))
            rock_mask=np.max(np.abs(pixels.reshape(270,480,4)[:,:,:3]-np.array(COLORS['rock'][:3])),axis=2)<.08
            row['rock_left_of_torso']=int(rock_mask[bottom:top,:left].sum())
            row['rock_right_of_torso']=int(rock_mask[bottom:top,right:].sum())
            row['torso_pixel_bounds']=[left,bottom,right,top]
        return row
    rows={str(f):render(f) for f in ((124,) if a.flanks_only else (148,) if a.slide_only else FRAMES)}
    if a.flanks_only:
        if a.expect_flanks_failure:
            try: check_flanks(rows['124'])
            except AssertionError as e: result={'status':'EXPECTED_FAILURE','assertion':str(e),'rows':rows}
            else: raise AssertionError('Actual edge impact passed bilateral rock pixels')
        else:
            check_flanks(rows['124']); result={'status':'PASS','rows':rows}
        (a.directory/'pixel_qa.json').write_text(json.dumps(result,indent=2)+'\n')
        print('FLANK_PIXELS',json.dumps(result),flush=True)
        return
    rocks=[o for o in s.objects if o.type=='MESH' and (o.name.startswith('Reaction | stack') or o.name.startswith('model.'))]
    for o in rocks: o.hide_render=True
    unobstructed=render(148,'_without_sandstone')
    for o in rocks: o.hide_render=False
    (a.directory/'pixel_counts.json').write_text(json.dumps(rows,indent=2)+'\n')
    if a.expect_slide_failure:
        assert a.slide_only, 'Negative baseline requires slide-only mode'
        try: check_slide(rows['148'],unobstructed)
        except AssertionError as error:
            result={'status':'EXPECTED_FAILURE','assertion':str(error),'rows':rows,'unobstructed':unobstructed}
            (a.directory/'pixel_qa.json').write_text(json.dumps(result,indent=2)+'\n')
            print('NEGATIVE_SLIDE_PIXELS',json.dumps(result),flush=True)
            return
        raise AssertionError('Actual obstructed slide passed rendered-pixel sanity')
    ratio=check_slide(rows['148'],unobstructed)
    if not a.slide_only: check(rows)
    if s.get('shot','').startswith(('T330', 'T331')): check_flanks(rows['124'])
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
    p.add_argument('--expect-slide-failure',action='store_true')
    p.add_argument('--flanks-only',action='store_true'); p.add_argument('--expect-flanks-failure',action='store_true')
    main(p.parse_args(sys.argv[sys.argv.index('--')+1:]))
