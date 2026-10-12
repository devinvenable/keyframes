"""Author the review-only liftoff continuation using original Blender assets.
blender -b SOURCE --python-exit-code 1 --python build.py -- --output DIR
"""
import argparse,json,math,random,sys
from pathlib import Path
import bpy
from mathutils import Vector, Matrix, Quaternion
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--camera',type=Path);a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
s=bpy.context.scene;source=bpy.data.filepath
assert 'liftoff' not in Path(source).name,'Build from the original scene, never from a prior output'
# Resolve resources before Save As changes the relative-path base.
for im in bpy.data.images:
 if im.filepath:im.filepath=bpy.path.abspath(im.filepath)
s.frame_set(496)
rig=bpy.data.objects['actor_kaiju_robot'];mesh=bpy.data.objects['kaiju_robot_mesh']
pose={b.name:b.matrix_basis.copy() for b in rig.pose.bones}
rig.animation_data_clear()
for name,matrix in pose.items():rig.pose.bones[name].matrix_basis=matrix
rig.location=(0,80,-2)
# The exported teaser is the authority for the join, even where the saved
# arm pose differs. Fit is from three firing-arm and nine body landmarks.
pose_match=json.loads(Path(__file__).with_name('pose_match.json').read_text())
dx,dz=pose_match['body_offset_xz'];ratio=pose_match['body_scale_ratio']
rig.location=(dx,80,-2+dz);rig.scale=(1.3*ratio,)*3
bpy.context.view_layer.update()
arm=rig.pose.bones['arm_L'];original_arm_q=arm.rotation_quaternion.copy()
pivot=arm.head.copy();delta=Quaternion(pose_match['arm_quaternion_wxyz']).to_matrix().to_4x4()
arm.matrix=Matrix.Translation(pivot) @ delta @ Matrix.Translation(-pivot) @ arm.matrix
bpy.context.view_layer.update()
matched_arm_q=arm.rotation_quaternion.copy()
# Separate parent control makes the original mesh, skin weights and pose reusable.
coll=bpy.data.collections.new('LIFTOFF | articulated dorsal engines');s.collection.children.link(coll)
def link(o):
 for c in list(o.users_collection):c.objects.unlink(o)
 coll.objects.link(o);return o

def empty(name,parent=None,loc=(0,0,0)):
 o=bpy.data.objects.new(name,None);coll.objects.link(o);o.parent=parent;o.location=loc;return o
lift=empty('Flight | lift and recoil');rig.parent=lift

def key(o,path,f,value):
 setattr(o,path,value);o.keyframe_insert(data_path=path,frame=f)

def material(name,color,metal=.0,rough=.4,emission=0):
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
 bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(*color,1);bs.inputs['Metallic'].default_value=metal;bs.inputs['Roughness'].default_value=rough
 if emission:bs.inputs['Emission Color'].default_value=(*color,1);bs.inputs['Emission Strength'].default_value=emission
 return m
armor=mesh.data.materials[0]
steel=material('LF | machined edges',(.20,.23,.25),.85,.28)
dark=material('LF | heat-darkened chambers',(.028,.035,.043),.78,.38)
brass=material('LF | aged fasteners',(.27,.17,.065),.8,.34)
blue=material('LF | pilot plasma',(.08,.46,1.0),.0,.3,5)
white=material('LF | white-hot core',(1,.64,.22),0,.3,16)
orange=material('LF | exhaust sheath',(1,.13,.008),0,.3,7)
# A thin emissive sheath transmits the brighter inner core.
n=orange.node_tree.nodes;links=orange.node_tree.links
mix=n.new('ShaderNodeMixShader');mix.inputs[0].default_value=.18
trans=n.new('ShaderNodeBsdfTransparent');links.new(trans.outputs[0],mix.inputs[1]);links.new(n.get('Principled BSDF').outputs[0],mix.inputs[2]);links.new(mix.outputs[0],n.get('Material Output').inputs['Surface'])

def cube(name,loc,dim,mat,parent=rig,bevel=.12):
 bpy.ops.mesh.primitive_cube_add(size=1);o=link(bpy.context.object);o.name=name;o.parent=parent;o.location=loc
 for v in o.data.vertices:v.co*=Vector(dim)
 o.data.materials.append(mat)
 if bevel:
  mod=o.modifiers.new('Edge radius','BEVEL');mod.width=bevel;mod.segments=2
  o.modifiers.new('Weighted normals','WEIGHTED_NORMAL')
 return o

def cylinder(name,loc,radius,depth,mat,parent=rig,vertices=12,radius2=None):
 if radius2 is None:bpy.ops.mesh.primitive_cylinder_add(vertices=vertices,radius=radius,depth=depth)
 else:bpy.ops.mesh.primitive_cone_add(vertices=vertices,radius1=radius,radius2=radius2,depth=depth)
 o=link(bpy.context.object);o.name=name;o.parent=parent;o.location=loc;o.data.materials.append(mat);return o

# Peel actual upper dorsal faces away from the body, retaining the original
# mesh elsewhere. Two replacement hatch leaves occupy exactly that back plane.
# Original robot uses face-split vertices: remove only the matching back face.
import bmesh
bm=bmesh.new();bm.from_mesh(mesh.data)
faces=[f for f in bm.faces if all(abs(v.co.y-8.8)<.015 and 36.99<=v.co.z<=53.01 for v in f.verts)]
assert len(faces)==2 and abs(sum(f.calc_area() for f in faces)-27.2*16)<.1, 'Dorsal torso topology changed'
bmesh.ops.delete(bm,geom=faces,context='FACES');bm.to_mesh(mesh.data);bm.free()
for sign,side in [(-1,'L'),(1,'R')]:
 hinge=empty('Hatch '+side+' | rear hinge',rig,(sign*13.5,8.8,45))
 door=cube('Hatch '+side+' | original armor',(-sign*6.65,0,0),(13.3,.45,16),armor,hinge,.10)
 for z in [-6,6]:
  for x in [-sign*1.4,-sign*11.9]:
   b=cylinder('Hatch '+side+' | bolt',(x,.36,z),.32,.25,brass,hinge,6);b.rotation_euler.x=math.pi/2
 for f,angle in [(1,0),(22+side.count('R')*4,0),(58+side.count('R')*4,-sign*math.radians(112)),(217,-sign*math.radians(112))]:key(hinge,'rotation_euler',f,(0,0,angle))
 # Engine rises out of the opened dorsal bay, then translates on a lateral rail.
 pod=empty('Booster '+side+' | deployment carriage',rig)
 for f,loc in [(1,(sign*7,3,44)),(42,(sign*7,3,44)),(68,(sign*11,11,61)),(88,(sign*22,-14,68)),(217,(sign*22,-14,68))]:key(pod,'location',f,loc)
 cube('Booster '+side+' | armored casing',(0,0,0),(6.7,7,14),armor,pod,.28)
 cube('Booster '+side+' | top cap',(0,0,7.3),(7.1,7.4,1.2),steel,pod,.18)
 for z in [-5,2,5]:cube('Booster '+side+' | cooling collar',(0,0,z),(7.1,7.5,.55),dark,pod,.07)
 for x in [-2.6,2.6]:
  cube('Booster '+side+' | rib',(x,-3.65,0),(.5,.55,12),steel,pod,.07)
  for z in [-5.3,5.3]:
   bolt=cylinder('Booster '+side+' | hex rivet',(x,-4,z),.28,.25,brass,pod,6);bolt.rotation_euler.x=math.pi/2
 # Downward facing bell with a dark mouth and inset hot throat.
 cylinder('Booster '+side+' | nozzle bell',(0,0,-8.4),3.6,3.0,dark,pod,12,2.3)
 cylinder('Booster '+side+' | nozzle lip',(0,0,-10),3.7,.65,steel,pod,12)
 throat=cylinder('Booster '+side+' | throat',(0,0,-10.36),3.12,.12,blue,pod,16)
 for f,sc in [(1,.001),(86,.001),(92,1),(217,1)]:key(throat,'scale',f,(sc,sc,sc))
 # Long piston and bridge stay attached to the original torso, supporting pods.
 rail=cube('Booster '+side+' | telescoping bridge',(sign*14,8,52),(18,2,2),dark,rig,.15)
 for f,sc in [(1,.001),(55,.001),(88,1),(217,1)]:key(rail,'scale',f,(sc,1,1))
 piston=cylinder('Booster '+side+' | polished ram',(sign*14,7,54),.5,17,steel,rig);piston.rotation_euler.y=math.pi/2
 for f,sc in [(1,.001),(55,.001),(88,1),(217,1)]:key(piston,'scale',f,(1,1,sc))
 # Nested irregular mesh plumes, authored and animated in Blender, no simulation cache.
 def plume(name,radius,length,mat):
  verts=[];faces=[];segments=16
  for row in range(9):
   t=row/8;r=radius*((1-t)**.68)*(.9+.12*math.sin(t*25))+.02
   for j in range(segments):
    ang=j*2*math.pi/segments;rr=r*(1+.07*math.sin(j*3+row*2));verts.append((rr*math.cos(ang),rr*math.sin(ang),-length*t))
  for row in range(8):
   for j in range(segments):
    q=row*segments+j;n=row*segments+(j+1)%segments;faces.append((q,n,n+segments,q+segments))
  faces.append(tuple(range(segments-1,-1,-1)));faces.append(tuple(range(8*segments,9*segments)))
  me=bpy.data.meshes.new(name);me.from_pydata(verts,[],faces);me.materials.append(mat);o=bpy.data.objects.new(name,me);coll.objects.link(o);o.parent=pod;o.location=(0,0,-10.5)
  for f in range(1,218):
   power=0 if f<94 else min(1,(f-94)/17)
   flutter=1+.10*math.sin(f*2.14+sign)+.055*math.sin(f*.77)
   o.scale=(max(.001,power),max(.001,power),max(.001,power*flutter));o.keyframe_insert(data_path='scale',frame=f)
  return o
 plume('Booster '+side+' | amber exhaust',2.8,43,orange)
 plume('Booster '+side+' | incandescent core',2.1,35,white)
 plume('Booster '+side+' | blue throat jet',2.7,5,blue)
 lamp=bpy.data.lights.new('Booster '+side+' | warm spill','POINT');lamp.color=(1,.30,.055);lamp.shadow_soft_size=5
 o=bpy.data.objects.new(lamp.name,lamp);coll.objects.link(o);o.parent=pod;o.location=(0,-1,-13)
 for f,power in [(1,0),(93,0),(98,65000),(111,210000),(217,210000)]:key(lamp,'energy',f,power)

# Original pose remains at the join, then firing arm settles into a flight brace.
for b in rig.pose.bones:
 b.rotation_mode='QUATERNION';q=b.rotation_quaternion.copy()
 for f in [1,28]:key(b,'rotation_quaternion',f,q)
 if b.name=='arm_L':
  target=Quaternion((1,0,0,0));key(b,'rotation_quaternion',89,original_arm_q.slerp(target,.85));key(b,'rotation_quaternion',217,original_arm_q.slerp(target,.85))
 elif b.name=='arm_R':
  target=q@Quaternion((0,0,1),math.radians(-6));key(b,'rotation_quaternion',89,target);key(b,'rotation_quaternion',217,target)
# Heavy anticipation, release, then a gradually accelerating 76-unit climb.
for f,z in [(1,0),(96,0),(110,-.65),(120,0),(144,5),(168,19),(192,43),(217,76)]:key(lift,'location',f,(0,0,z))
# Paired hydraulic yokes visibly carry each deployed engine; no floating pods.
for sign,side in [(-1,'L'),(1,'R')]:
 pod=bpy.data.objects['Booster '+side+' | deployment carriage']
 beams=[]
 for offset in [-1.2,1.2]:
  beam=cylinder('Booster '+side+' | articulated piston', (0,0,0),.65,1,steel,rig)
  beams.append((beam,offset))
 for f in range(1,218):
  s.frame_set(f)
  for beam,offset in beams:
   start=Vector((sign*13+offset,7,52));end=pod.location+Vector((offset,1,-3))
   delta=end-start
   key(beam,'location',f,(start+end)/2)
   beam.rotation_mode='QUATERNION';key(beam,'rotation_quaternion',f,delta.to_track_quat('Z','Y'))
   key(beam,'scale',f,(1,1,delta.length))
# End the existing volley; retain its actual animated reflections during the join.
for o in list(s.objects):
 if o.name.startswith('actor_plasma_ring'):
  o.visible_camera=False  # Last teaser rings have already left the photographed view.
  samples=[]
  for f in range(1,15):
   s.frame_set(495+f);samples.append((o.location.copy(),o.rotation_euler.copy(),o.scale.copy()))
  o.animation_data_clear()
  for f,(loc,rot,sc) in enumerate(samples,1):
   key(o,'location',f,loc);key(o,'rotation_euler',f,rot);key(o,'scale',f,sc)
  key(o,'scale',15,(.001,.001,.001));key(o,'scale',217,(.001,.001,.001))
for mat in bpy.data.materials:
 if mat.name.startswith('PlasmaRing') and mat.node_tree.animation_data and mat.node_tree.animation_data.action:
  act=mat.node_tree.animation_data.action.copy();mat.node_tree.animation_data.action=act
  for layer in act.layers:
   for strip in layer.strips:
    for bag in strip.channelbags:
     for fc in bag.fcurves:
      for k in fc.keyframe_points:
       k.co.x-=495;k.handle_left.x-=495;k.handle_right.x-=495
# Ground dust: noisy volume puffs spread horizontally from under the two engines.
rng=random.Random(305)
dust=bpy.data.materials.new('LF | turbulent sandstone dust');dust.use_nodes=True;n=dust.node_tree.nodes;n.clear();links=dust.node_tree.links
output=n.new('ShaderNodeOutputMaterial');vol=n.new('ShaderNodeVolumePrincipled');vol.inputs['Color'].default_value=(.27,.20,.13,1);vol.inputs['Anisotropy'].default_value=.25
tex=n.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=3.4;tex.inputs['Detail'].default_value=3
coords=n.new('ShaderNodeTexCoord');links.new(coords.outputs['Generated'],tex.inputs['Vector'])
ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.36;ramp.color_ramp.elements[1].position=.73
links.new(tex.outputs['Fac'],ramp.inputs[0]);mult=n.new('ShaderNodeMath');mult.operation='MULTIPLY';mult.inputs[1].default_value=.10;links.new(ramp.outputs[0],mult.inputs[0]);links.new(mult.outputs[0],vol.inputs['Density']);links.new(vol.outputs['Volume'],output.inputs['Volume'])
for i in range(20):
 ang=rng.uniform(0,math.tau);base=Vector((0,83,1));v=Vector((math.cos(ang),math.sin(ang),0));radius=rng.uniform(4,8)
 bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1);o=link(bpy.context.object);o.name=f'Dust | ground roll {i:02}';o.data.materials.append(dust)
 for f,spread,size,height in [(1,12,.001,1),(103+i%9,12,.001,1),(130+i%9,18,.7,2.5),(174,37,1.4,4),(217,65,1.7,3)]:
  key(o,'location',f,base+v*spread+Vector((0,0,height)));key(o,'scale',f,(radius*size,radius*size*.8,radius*size*.38))
# Camera: numerical fit to real reference, continuous low drift before tilting up.
c=s.camera;c.animation_data_clear();c.constraints.clear();c.rotation_mode='QUATERNION'
cm=json.loads((a.camera or Path(__file__).with_name('camera_match.json')).read_text());base=Vector(cm['location']);c.data.lens=cm['lens'];c.data.dof.focus_distance=100;c.data.dof.aperture_fstop=5.6
for f in range(1,218):
 t=(f-1)/24
 loc=base+Vector((1.5*t-0.52*t*t,-2.14*t,0))
 # Camera stays close to the ground. Delayed tilt lets feet clear the arch in frame.
 climb=max(0,(f-120)/97);target=Vector((0,80,45+64*climb**1.8))
 key(c,'location',f,loc);key(c,'rotation_quaternion',f,(target-loc).to_track_quat('-Z','Y'))
# Linear baked channels; mechanical sparse channels ease with clamped handles.
def curves(action):
 return [fc for layer in action.layers for st in layer.strips for bag in st.channelbags for fc in bag.fcurves]
for action in bpy.data.actions:
 for fc in curves(action):
  for k in fc.keyframe_points:
   if len(fc.keyframe_points)>100:k.interpolation='LINEAR'
   else:k.handle_left_type=k.handle_right_type='AUTO_CLAMPED'
# Review scene opens at the beginning; timeline labels make the staging editable.
s.frame_start=1;s.frame_end=217;s.render.fps=24;s.render.resolution_x=1920;s.render.resolution_y=1080;s.render.resolution_percentage=100
for name,f in [('JOIN | teaser2 last frame',1),('DOORS | unlock',22),('DEPLOY | rise then spread',42),('LOCK | ignition',94),('LIFT | release weight',120),('CLIMB | clear arch',192)]:s.timeline_markers.new(name,frame=f)
s.render.engine='CYCLES';s.cycles.samples=64;s.cycles.use_denoising=True;s.render.image_settings.file_format='PNG';s.render.filepath=str(out/'final_frames/frame_')
s['liftoff_source']=source;s['liftoff_note']='Draft choreography. First frame matches teaser2 endpoint. Preview uses frames 2–217, avoiding a duplicated join. No final render approved.'
bpy.ops.file.pack_all();s.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'kaiju_liftoff_shot.blend'),compress=True)
(out/'build_manifest.json').write_text(json.dumps({'source':source,'blend':str(out/'kaiju_liftoff_shot.blend'),'fps':24,'range':[1,217],'extension_range':[2,217],'camera':cm,'original_dorsal_faces_replaced':len(faces),'objects_added':len(coll.objects),'source_ring_start':496,'pose_match':pose_match},indent=2))
print('LIFTOFF_BUILT',out,flush=True)
