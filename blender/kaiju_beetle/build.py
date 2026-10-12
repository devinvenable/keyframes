"""Build standalone beetle and two posed shots from the original desert scene.
blender -b --python-exit-code 1 --python build.py -- --output DIR --source ORIGINAL
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import build, COLLECTION
sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'kaiju_liftoff'))
from restore_teaser_state import restore_teaser_state

p=argparse.ArgumentParser()
p.add_argument('--output',type=Path,required=True)
p.add_argument('--source',type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
out=a.output.resolve(); source=a.source.resolve()
assert source.is_file() and out != source.parent, 'Use a separate output directory'
out.mkdir(parents=True,exist_ok=True)


def settings(s):
    s.render.engine='CYCLES'
    s.cycles.samples=48
    s.cycles.use_denoising=True
    s.render.resolution_x=1920; s.render.resolution_y=1080
    s.render.resolution_percentage=100
    s.render.image_settings.file_format='PNG'
    s.render.image_settings.color_mode='RGB'
    s.view_settings.view_transform='AgX'
    s.render.fps=24; s.frame_start=s.frame_end=1
    s.world.color=(.14,.14,.14)


def camera(s, loc, target, lens):
    if not s.camera:
        data=bpy.data.cameras.new('Review camera')
        s.camera=bpy.data.objects.new('Review camera',data)
        s.collection.objects.link(s.camera)
    c=s.camera; c.animation_data_clear(); c.constraints.clear()
    c.location=loc; c.rotation_mode='QUATERNION'
    c.rotation_quaternion=(Vector(target)-c.location).to_track_quat('-Z','Y')
    c.data.lens=lens; c.data.clip_end=5000; c.data.dof.use_dof=False


def area(s,name,loc,target,color,power,size):
    d=bpy.data.lights.new(name,'AREA'); d.energy=power; d.color=color; d.shape='DISK';d.size=size
    o=bpy.data.objects.new(name,d); s.collection.objects.link(o);o.location=loc
    o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()


def save(path):
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(path))


def ground(root, objects):
    bpy.context.view_layer.update()
    deps=bpy.context.evaluated_depsgraph_get()
    lowest=min((o.evaluated_get(deps).matrix_world @ v.co).z
               for o in objects if o.type=='MESH' for v in o.evaluated_get(deps).data.vertices)
    root.location.z-=lowest
    bpy.context.view_layer.update()


bpy.ops.wm.read_factory_settings(use_empty=True)
root,coll=build();s=bpy.context.scene
s.world=bpy.data.worlds.new('Studio world');s.world.use_nodes=True
s.world.node_tree.nodes.get('Background').inputs[0].default_value=(.14,.17,.21,1)
s.world.node_tree.nodes.get('Background').inputs[1].default_value=.4
settings(s)
camera(s,(126,-208,100),(0,0,51),43)
area(s,'Studio warm key',(-70,-110,135),(0,0,44),(1,.78,.55),310000,85)
area(s,'Studio cool fill',(75,-60,75),(0,0,45),(.55,.72,1),170000,70)
area(s,'Studio rim',(35,80,130),(0,0,50),(1,.65,.27),370000,65)
bpy.ops.mesh.primitive_plane_add(size=2000)
floor=bpy.context.object;floor.name='Studio floor'
m=bpy.data.materials.new('Studio charcoal');m.diffuse_color=(.055,.064,.075,1);m.use_nodes=True
m.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=m.diffuse_color
m.node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value=.65
floor.data.materials.append(m)
ground(root,coll.objects)
s['asset_collection']=COLLECTION
s['notes']='Append BEETLE collection. +Z up, -Y forward. Named empty pivots; all mesh parts rigid.'
bpy.ops.object.select_all(action='DESELECT');root.select_set(True);bpy.context.view_layer.objects.active=root
save(out/'kaiju_beetle.blend')

# Load each shot afresh: no mutations accumulate between poses.
for shot in ['faceoff','clash']:
    bpy.ops.wm.open_mainfile(filepath=str(source))
    s=bpy.context.scene
    for im in bpy.data.images:
        if im.filepath:im.filepath=bpy.path.abspath(im.filepath)
    s.frame_set(1)
    rig=bpy.data.objects['actor_kaiju_robot']
    base_pose={b.name:b.matrix_basis.copy() for b in rig.pose.bones}
    for o in s.objects:
        o.animation_data_clear()
        if o.name.startswith('actor_plasma_ring'):o.hide_render=True;o.hide_viewport=True
    for name,matrix in base_pose.items():rig.pose.bones[name].matrix_basis=matrix
    restoration=restore_teaser_state()
    (out/'continuity_restoration.json').write_text(json.dumps(restoration,indent=2)+'\n')
    with bpy.data.libraries.load(str(out/'kaiju_beetle.blend'),link=False) as (src,dst):
        dst.collections=[COLLECTION]
    coll=dst.collections[0];s.collection.children.link(coll)
    root=bpy.data.objects['BK | ROOT | placement']
    def joint(name,xyz):
        bpy.data.objects['BK | '+name].rotation_euler=tuple(math.radians(v) for v in xyz)
    if shot=='faceoff':
        root.location=(-70,73,0);root.rotation_euler.z=math.radians(35)
        rig.location=(20,92,0);rig.rotation_euler.z=math.radians(-55)
        joint('waist',(0,0,-4));joint('neck',(0,0,12))
        joint('shoulder L',(-12,-10,-8));joint('elbow L',(-24,0,0))
        joint('shoulder R',(-22,8,9));joint('elbow R',(-36,0,0))
        joint('hip L',(-9,-4,0));joint('knee L',(9,0,0));joint('ankle L',(0,4,0))
        joint('hip R',(8,4,0));joint('knee R',(0,0,0));joint('ankle R',(-8,-4,0))
        camera(s,(-115,-170,18),(-23,83,50),40)
    else:
        root.location=(-45,74,0);root.rotation_euler.z=math.radians(61)
        rig.location=(14,82,0);rig.rotation_euler.z=math.radians(-65)
        rig.rotation_euler.x=math.radians(-5)
        joint('waist',(13,0,7));joint('neck',(12,0,5))
        joint('shoulder R',(-69,8,0));joint('elbow R',(-31,0,0))
        joint('shoulder L',(-40,-18,-8));joint('elbow L',(-67,0,0))
        joint('wrist L',(14,0,0));joint('wrist R',(8,0,0))
        joint('hip L',(-20,-6,0));joint('knee L',(30,0,0));joint('ankle L',(-10,6,0))
        joint('hip R',(19,7,0));joint('knee R',(8,0,0));joint('ankle R',(-27,-7,0))
        camera(s,(-118,-125,17),(-24,76,48),36)
    # Rotate robot's complete rigid arm around its shoulder in armature space.
    bpy.context.view_layer.update()
    for name,angle in [('arm_L',-38 if shot=='faceoff' else -78),('arm_R',-22 if shot=='faceoff' else -53)]:
        b=rig.pose.bones[name]; pivot=b.head.copy()
        b.matrix=Matrix.Translation(pivot) @ Quaternion((1,0,0),math.radians(angle)).to_matrix().to_4x4() @ Matrix.Translation(-pivot) @ b.matrix
        bpy.context.view_layer.update()
    ground(root,coll.objects)
    ground(rig,[bpy.data.objects['kaiju_robot_mesh']])
    settings(s)
    # Retain original HDRI, terrain, arch and low fog. Add broad photographic fill.
    area(s,'BK shot | bronze key',(-85,-65,150),(-20,75,45),(1,.78,.53),45000,100)
    area(s,'BK shot | neutral fill',(110,-30,100),(20,75,45),(.66,.79,1),30000,90)
    area(s,'BK shot | rim',(-30,170,150),(0,75,45),(1,.70,.42),70000,80)
    area(s,'BK shot | charged plasma blue',(48,35,37),(17,84,38),(.055,.32,1),30000,24)
    s.view_settings.exposure=-.8
    s['shot']=shot
    s['source_scene']=str(source)
    s['design_reference']='kaiju_beetle_voxel.png'
    s['pose_notes']='Static posed review. All beetle transforms on named empty joints; robot original rig retained.'
    bpy.ops.file.pack_all()
    save(out/f'beetle_{shot}.blend')

manifest={'source':str(source),'output':str(out),'files':['kaiju_beetle.blend','beetle_faceoff.blend','beetle_clash.blend'],
          'reference':'/home/devin/src/2026/videdit/work/kaiju_beetle_refs/kaiju_beetle_voxel.png',
          'axes':'+Z up, -Y front','construction':'independent rigid solids, empty joint hierarchy'}
(out/'build_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('BEETLE_BUILD_COMPLETE',out)
