"""Measure animation/foot-contact contracts and mutation-check their assertions."""
import argparse
import json
import sys
from pathlib import Path
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--negative-checks',action='store_true')
p.add_argument('--entry-reveal-through',type=int,default=0,help='Explicit partial-entry framing allowance; never extends to contact')
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);s=bpy.context.scene
assert 0 <= a.entry_reveal_through < 52, 'Entry framing allowance must end before contact'
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
def check_preimpact():assert bpy.data.objects['Arrival | powder 00'].scale.x<.03,'Powder must stay invisible before contact'
def check_birth():assert bpy.data.objects['Arrival | powder 00'].scale.x>2,'Powder must be born on the exact contact frame'
def check_dust():assert bpy.data.objects['Arrival | powder 00'].scale.x>2,'Dust must expand after impact'
def check_settled():assert bpy.data.objects['Arrival | powder 00'].location.z<1,'Powder must return to ground height after impact'
def check_diluted():assert bpy.data.materials['Arrival | fullers earth 0'].node_tree.nodes['Powder settling density'].inputs[1].default_value<.06,'Powder must dilute after its short impact burst'
def projected(objects):
    points=[world_to_camera_view(s,cam,o.matrix_world@Vector(c)) for o in objects for c in o.bound_box]
    return [min(p.x for p in points),min(p.y for p in points),max(p.x for p in points),max(p.y for p in points)]

report={'shot':bpy.data.filepath,'samples':{},'negative_checks':[],'render_settings':{'resolution':[s.render.resolution_x,s.render.resolution_y],'samples':s.cycles.samples,'volume_step_rate':s.cycles.volume_step_rate,'volume_max_steps':s.cycles.volume_max_steps},'dust_counts':{'lobes':sum(o.name.startswith('Arrival | powder') for o in s.objects),'clumps':sum(o.name.startswith('Arrival | thrown grit') for o in s.objects)}}
report['entry_reveal_through']=a.entry_reveal_through
for f in [1,29,40,51,52,54,58,63,86,108]:
    s.frame_set(f);bpy.context.view_layer.update()
    report['samples'][str(f)]={'floor':floor(),'lens':cam.data.lens,'beetle_bounds':projected(meshes)}
    if f==40:check_airborne()
    if f==51:check_preimpact()
    if f==52:check_birth()
    if f>=52:check_landing()
    if f>=63:check_zoom()
    if f==58:check_dust()
    if f==86 and s.get('quality')=='final':check_settled();check_diluted()
    if f in [40,86,108] and f>a.entry_reveal_through:
        bounds=projected(meshes)
        assert bounds[0]>.015 and bounds[1]>.015 and bounds[2]<.985 and bounds[3]<.985, ('Beetle cropped',f,bounds)
if a.entry_reveal_through:
    # Use the actual rigid mesh rather than rotated box corners for the tight
    # approved contact pose. No part may leave the image after the entry reveal.
    report['post_entry_mesh_bounds']={}
    for f in range(a.entry_reveal_through+1,109):
        s.frame_set(f);bpy.context.view_layer.update()
        points=[world_to_camera_view(s,cam,o.matrix_world@v.co) for o in meshes for v in o.data.vertices]
        bounds=[min(p.x for p in points),min(p.y for p in points),max(p.x for p in points),max(p.y for p in points)]
        assert min(p.z for p in points)>0 and min(bounds[:2])>0 and max(bounds[2:])<1, ('Post-entry beetle cropped',f,bounds)
        report['post_entry_mesh_bounds'][str(f)]=bounds
for f in range(52,109):
    s.frame_set(f);check_landing()
rig=bpy.data.objects['actor_kaiju_robot'];robot=bpy.data.objects['kaiju_robot_mesh']
assert not robot.hide_render,'Robot must remain present for reverse-shot continuity'
assert (rig.location-Vector((-45,75,.15))).length>600,'Opponents must be far apart'
report['robot_staging']={'location':list(rig.location),'distance':(rig.location-Vector((-45,75,.15))).length}
def check_robot_outside():
    points=[world_to_camera_view(s,cam,robot.matrix_world@Vector(c)) for c in robot.bound_box]
    assert all(p.z<0 for p in points),'Robot must stay entirely behind the arrival camera'
for f in range(1,109):
    s.frame_set(f);bpy.context.view_layer.update();check_robot_outside()
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
    mutation(1,rig,'location',Vector((80,180,.15)),check_robot_outside,'Restore superseded visible robot placement')
    s.frame_set(40);loc=root.location.copy();loc.z-=floor()
    mutation(40,root,'location',loc,check_airborne,'Remove leap height')
    s.frame_set(52);loc=root.location.copy();loc.z+=4
    mutation(52,root,'location',loc,check_landing,'Raise landing four units')
    mutation(86,cam.data,'lens',32,check_zoom,'Remove zoom')
    mutation(51,bpy.data.objects['Arrival | powder 00'],'scale',Vector((5,)*3),check_preimpact,'Start powder before foot contact')
    mutation(52,bpy.data.objects['Arrival | powder 00'],'scale',Vector((.001,)*3),check_birth,'Delay powder birth beyond contact')
    mutation(58,bpy.data.objects['Arrival | powder 00'],'scale',Vector((.001,)*3),check_dust,'Remove impact powder')
    if s.get('quality')=='final':
        s.frame_set(86);powder=bpy.data.objects['Arrival | powder 00'];loc=powder.location.copy();loc.z+=10
        mutation(86,powder,'location',loc,check_settled,'Keep powder aloft like buoyant smoke')
        density=bpy.data.materials['Arrival | fullers earth 0'].node_tree.nodes['Powder settling density'].inputs[1]
        mutation(86,density,'default_value',.9,check_diluted,'Remove post-impact dust dilution')
report['status']='PASS';a.output.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
