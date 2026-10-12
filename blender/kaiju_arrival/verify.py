"""Measure animation/foot-contact contracts and mutation-check their assertions."""
import argparse
import json
import sys
from pathlib import Path
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--negative-checks',action='store_true')
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);s=bpy.context.scene
assert (s.frame_start,s.frame_end,s.render.fps)==(1,108,24),'Shot must be 108 frames at 24 fps'
root=bpy.data.objects['BK | ROOT | placement'];cam=s.camera
soles=[bpy.data.objects['BK | sole '+side] for side in ['L','R']]
meshes=[o for o in s.objects if o.name.startswith('BK |') and o.type=='MESH']

def floor():
    bpy.context.view_layer.update()
    return min((o.matrix_world@Vector(c)).z for o in soles for c in o.bound_box)

def check_airborne():assert floor()>30,'Airborne beat must clear the ground by 30 units'
def check_landing():assert abs(floor())<.03,'Contact beat must plant soles on the ground'
def check_zoom():assert cam.data.lens>=70,'Zoom must finish at a tight lens'
def check_dust():assert bpy.data.objects['Arrival | powder 00'].scale.x>2,'Dust must expand after impact'
def projected(objects):
    points=[world_to_camera_view(s,cam,o.matrix_world@Vector(c)) for o in objects for c in o.bound_box]
    return [min(p.x for p in points),min(p.y for p in points),max(p.x for p in points),max(p.y for p in points)]

report={'shot':bpy.data.filepath,'samples':{},'negative_checks':[]}
for f in [1,29,40,51,52,54,58,63,86,108]:
    s.frame_set(f);bpy.context.view_layer.update()
    report['samples'][str(f)]={'floor':floor(),'lens':cam.data.lens,'beetle_bounds':projected(meshes)}
    if f==40:check_airborne()
    if f>=52:check_landing()
    if f>=63:check_zoom()
    if f==58:check_dust()
    if f in [40,86,108]:
        bounds=projected(meshes)
        assert bounds[0]>.015 and bounds[1]>.015 and bounds[2]<.985 and bounds[3]<.985, ('Beetle cropped',f,bounds)
s.frame_set(1);rb=projected([bpy.data.objects['kaiju_robot_mesh']]);report['robot_establishing_bounds']=rb
assert rb[3]-rb[1]<.55,'Robot should stand back in the wide establishing shot'
assert all(0<v<1 for v in rb),'Establishing robot must be in frame'
assert all(m.type not in {'ARMATURE','SUBSURF','LATTICE','CLOTH','SOFT_BODY'} for o in meshes for m in o.modifiers),'Beetle must retain rigid solids'
if a.negative_checks:
    # In-memory property copies are restored exactly; no mutated scene is saved.
    def mutation(frame,obj,attr,value,check,label):
        s.frame_set(frame);old=getattr(obj,attr);old=old.copy() if hasattr(old,'copy') else old
        try:
            setattr(obj,attr,value);bpy.context.view_layer.update()
            try:check()
            except AssertionError as exc:report['negative_checks'].append({'mutation':label,'assertion':str(exc)})
            else:raise AssertionError('Mutation was not detected: '+label)
        finally:setattr(obj,attr,old);bpy.context.view_layer.update()
        check()
    s.frame_set(40);loc=root.location.copy();loc.z-=floor()
    mutation(40,root,'location',loc,check_airborne,'Remove leap height')
    s.frame_set(52);loc=root.location.copy();loc.z+=4
    mutation(52,root,'location',loc,check_landing,'Raise landing four units')
    mutation(86,cam.data,'lens',32,check_zoom,'Remove zoom')
    mutation(58,bpy.data.objects['Arrival | powder 00'],'scale',Vector((.001,)*3),check_dust,'Remove impact powder')
report['status']='PASS';a.output.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
