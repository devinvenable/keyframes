"""Check physical continuity, motion, packing and the sub-second ring tail."""
import argparse,json,sys
from pathlib import Path
import bpy
from mathutils import Vector, Matrix, Quaternion
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
bpy.ops.wm.open_mainfile(filepath=str(a.source),load_ui=False,use_scripts=False)
s=bpy.context.scene;s.frame_set(496);bpy.context.view_layer.update()
rig=bpy.data.objects['actor_kaiju_robot'];source_pose={b.name:[list(row) for row in b.matrix] for b in rig.pose.bones}
fit=json.loads(Path(__file__).with_name('pose_match.json').read_text())
arm=rig.pose.bones['arm_L'];pivot=arm.head.copy();delta=Quaternion(fit['arm_quaternion_wxyz']).to_matrix().to_4x4()
source_pose['arm_L']=[list(row) for row in Matrix.Translation(pivot) @ delta @ Matrix.Translation(-pivot) @ arm.matrix]
source_vertices={tuple(round(c,5) for c in v.co) for v in bpy.data.objects['kaiju_robot_mesh'].data.vertices}
bpy.ops.wm.open_mainfile(filepath=str(a.candidate),load_ui=False,use_scripts=False)
s=bpy.context.scene;s.frame_set(1);bpy.context.view_layer.update();rig=bpy.data.objects['actor_kaiju_robot']
pose_error=max(abs(b.matrix[i][j]-source_pose[b.name][i][j]) for b in rig.pose.bones for i in range(4) for j in range(4))
assert pose_error<1e-4, f'Join pose changed from teaser-matched target: {pose_error}'
dx,dz=fit['body_offset_xz']
assert (rig.location-Vector((dx,80,-2+dz))).length<1e-4,'Robot placement does not match footage fit'
assert max(abs(x-1.3*fit['body_scale_ratio']) for x in rig.scale)<1e-5,'Robot scale does not match footage fit'
assert all(tuple(round(c,5) for c in v.co) in source_vertices for v in bpy.data.objects['kaiju_robot_mesh'].data.vertices),'Original body vertices changed'
positions=[];heights=[];ring_tail=[]
for f in range(1,218):
 s.frame_set(f);bpy.context.view_layer.update();positions.append(s.camera.matrix_world.translation.copy());heights.append(rig.matrix_world.translation.z)
 if f>=15:
  assert all(max(o.scale)<=.00101 for o in s.objects if o.name.startswith('actor_plasma_ring')),f'Ring survives at {f}'
steps=[(b-a).length for a,b in zip(positions,positions[1:])]
assert min(steps)>.02,'Camera freezes during the continuation'
assert max(steps)<1,'Camera makes an abrupt spatial jump'
assert abs(heights[-1]-heights[0]-76)<.001,'Robot does not complete the authored climb'
assert max(abs(z-heights[0]) for z in heights[:95])<.001,'Robot rises before ignition'
assert s.render.fps==24 and (s.frame_start,s.frame_end)==(1,217),'Incorrect timeline'
missing=[im.name for im in bpy.data.images if im.source=='FILE' and not im.packed_file and (not im.filepath or not Path(bpy.path.abspath(im.filepath)).exists())]
assert not missing,f'Missing image dependencies: {missing}'
report={'status':'PASS','join_pose_max_error':pose_error,'join_target':'exported teaser reference','arm_landmark_rms_pixels':fit['arm_rms_pixels'],'body_landmark_rms_pixels':fit['body_rms_pixels'],'body_vertices_unchanged':True,'camera_min_step':min(steps),'camera_max_step':max(steps),'climb_world_units':heights[-1]-heights[0],'ring_reflections_end_frame':15,'missing_images':missing,'fps':24,'extension_frames':216,'extension_seconds':9,'checks':'All 217 evaluated frames checked for camera motion, lift timing and ring cutoff; teaser-matched pose/placement/scale and original body vertices checked at join.'}
a.output.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
