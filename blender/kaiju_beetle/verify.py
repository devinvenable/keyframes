"""Audit saved assets; optional destructive checks operate in memory, never save.

blender -b --python-exit-code 1 --python verify.py -- --directory DIR --negative-checks
"""
import argparse
import json
import math
import sys
from pathlib import Path
import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

DEFORM={'ARMATURE','LATTICE','SIMPLE_DEFORM','MESH_DEFORM','SURFACE_DEFORM','SUBSURF'}


def audit():
    s=bpy.context.scene;coll=bpy.data.collections['BEETLE | bronze knight']
    meshes=[o for o in coll.objects if o.type=='MESH']
    joints=[o for o in coll.objects if o.type=='EMPTY']
    assert len(meshes)>=170,'Missing rigid parts'
    assert len(joints)>=25,'Missing animation joints'
    for o in meshes:
        assert o.parent and o.parent.type=='EMPTY',f'Nonrigid parenting: {o.name}'
        assert not any(m.type in DEFORM for m in o.modifiers),f'Deforming modifier: {o.name}'
        assert not o.hide_render,f'Hidden beetle part: {o.name}'
        bm=bmesh.new();bm.from_mesh(o.data)
        closed=all(e.is_manifold for e in bm.edges)
        bm.free()
        assert closed,f'Open solid: {o.name}'
    for name in ['waist','neck','shoulder L','shoulder R','elbow L','elbow R',
                 'hip L','hip R','knee L','knee R','ankle L','ankle R',
                 'elytron hinge L','elytron hinge R','drill spindle']:
        assert bpy.data.objects.get('BK | '+name),'Missing joint: '+name
    assert bpy.data.objects.get('BK | drill | continuous helical cutting ridge'),'Missing drill ridge'
    s.frame_set(1);bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get()
    groups={'beetle':meshes}
    if s.get('shot'):
        robot=bpy.data.objects['kaiju_robot_mesh'];groups['robot']=[robot]
        assert len(robot.data.materials)==10,'Robot original material assignments lost'
        assert len(robot.data.vertices)==1822,'Native robot geometry changed'
        assert len(robot.data.polygons)==1854,'Native robot face count changed'
        assert len(set(f.material_index for f in robot.data.polygons))==10,'Robot material face mapping lost'
        assert all(v.groups for v in robot.data.vertices),'Unweighted robot vertices'
        for mat in robot.data.materials:
            bs=mat.node_tree.nodes.get('Principled BSDF')
            assert bs.inputs['Emission Strength'].default_value==0,'Invented robot emission'
        assert s.world.node_tree.nodes.get('Teaser | upper sky only'),'Hillside sky not corrected'
        assert bpy.data.materials['FogMaterial'].node_tree.nodes.get('Volume Scatter').inputs['Density'].is_linked,'Flat fog slab restored'
    bounds={}
    for name,objects in groups.items():
        points=[]
        for o in objects:
            ev=o.evaluated_get(deps)
            points.extend(ev.matrix_world@v.co for v in ev.data.vertices)
        low=min(p.z for p in points);high=max(p.z for p in points)
        assert abs(low)<.035,f'{name} not planted: {low}'
        projected=[world_to_camera_view(s,s.camera,p) for p in points]
        uv=[min(p.x for p in projected),max(p.x for p in projected),
            min(p.y for p in projected),max(p.y for p in projected)]
        assert all(p.z>0 for p in projected),f'{name} behind camera'
        assert 0.015<uv[0]<uv[1]<.985 and .015<uv[2]<uv[3]<.985,f'{name} cropped: {uv}'
        bounds[name]={'height':high-low,'lowest_z':low,'camera_bounds':uv}
    if 'robot' in bounds:
        ratio=bounds['beetle']['height']/bounds['robot']['height']
        assert .8<ratio<1.3,'Not peer-scale adversaries'
    missing=[im.name for im in bpy.data.images if im.source=='FILE' and im.users and not im.packed_file
             and (not im.filepath or not Path(bpy.path.abspath(im.filepath)).exists())]
    assert not missing,f'Missing resources: {missing}'
    return {'meshes':len(meshes),'joints':len(joints),'bounds':bounds,
            'all_parts_closed':True,'rigid_only':True,'missing_resources':missing}


def negative_checks():
    """Each mutation must fail its intended assertion, then restore exact state."""
    results=[]
    def rejected(label,fragment):
        try:audit()
        except AssertionError as exc:
            assert fragment in str(exc),f'{label} failed for wrong reason: {exc}'
            results.append({'mutation':label,'assertion':str(exc)})
        else:raise AssertionError('Mutation survived: '+label)
    o=bpy.data.objects['BK | hip chassis']
    mod=o.modifiers.new('Negative check only','ARMATURE')
    try:rejected('deforming modifier','Deforming modifier')
    finally:o.modifiers.remove(mod)
    original=o.data;temporary=original.copy();o.data=temporary
    try:
        bm=bmesh.new();bm.from_mesh(temporary);bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm,geom=[bm.faces[0]],context='FACES');bm.to_mesh(temporary);bm.free()
        rejected('hole in rigid solid','Open solid')
    finally:o.data=original;bpy.data.meshes.remove(temporary)
    lens=bpy.context.scene.camera.data.lens
    try:
        bpy.context.scene.camera.data.lens=180
        rejected('camera crops fighters','cropped')
    finally:bpy.context.scene.camera.data.lens=lens
    if bpy.context.scene.get('shot'):
        robot=bpy.data.objects['kaiju_robot_mesh'];original=robot.data;temporary=original.copy();robot.data=temporary
        try:
            temporary.materials.pop(index=len(temporary.materials)-1)
            rejected('collapsed material slots','material assignments lost')
        finally:robot.data=original;bpy.data.meshes.remove(temporary)
    audit()
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--negative-checks',action='store_true')
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);report={}
    for name in ['kaiju_beetle','beetle_faceoff','beetle_clash']:
        bpy.ops.wm.open_mainfile(filepath=str(a.directory/(name+'.blend')))
        report[name]=audit()
        if a.negative_checks:report[name]['negative_checks']=negative_checks()
        print('VERIFIED',name)
    (a.directory/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
