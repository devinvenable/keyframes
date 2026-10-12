"""Run with blender -b SOURCE --python inspect_scene.py -- OUTPUT.json."""
import bpy, json, sys
from mathutils import Vector

def curves(action):
    if hasattr(action, 'fcurves'):
        return list(action.fcurves)
    return [fc for layer in action.layers for strip in layer.strips for bag in strip.channelbags for fc in bag.fcurves]

def vec(v): return [round(float(x),5) for x in v]
s=bpy.context.scene
report={'file':bpy.data.filepath,'scene':s.name,'range':[s.frame_start,s.frame_end], 'frame':s.frame_current,'engine':s.render.engine, 'fps':s.render.fps,'camera':s.camera.name if s.camera else None,'objects':[], 'images':[], 'markers':[(m.name,m.frame) for m in s.timeline_markers]}
for o in s.objects:
    action=o.animation_data.action if o.animation_data else None
    d={'name':o.name,'type':o.type,'parent':o.parent.name if o.parent else None,'loc':vec(o.location),'rot':vec(o.rotation_euler),'scale':vec(o.scale),'dim':vec(o.dimensions),'hide':o.hide_render,'collections':[c.name for c in o.users_collection], 'materials':[m.name if m else None for m in o.data.materials] if hasattr(o.data,'materials') else []}
    if action:
        d['action']=action.name
        d['curves']=[{'path':f.data_path,'i':f.array_index,'keys':[vec(k.co) for k in f.keyframe_points]} for f in curves(action)]
    if o.type=='CAMERA': d['lens']=o.data.lens
    if o.type=='ARMATURE':d['bones']=[b.name for b in o.pose.bones]
    report['objects'].append(d)
for im in bpy.data.images:report['images'].append({'name':im.name,'path':im.filepath,'packed':bool(im.packed_file)})
report['samples']={}
for f in [1,384,408,432,436,450]:
    s.frame_set(f)
    report['samples'][str(f)]={o.name:{'matrix':[vec(row) for row in o.matrix_world],'bounds':[vec(o.matrix_world@Vector(c)) for c in o.bound_box]} for o in s.objects if o.type in {'CAMERA','ARMATURE'} or any(w in o.name.lower() for w in ['robot','kaiju','body','torso','head','leg'])}
with open(sys.argv[sys.argv.index('--')+1],'w') as out:json.dump(report,out,indent=2)
print('INSPECT',report['range'],report['camera'],len(report['objects']))
