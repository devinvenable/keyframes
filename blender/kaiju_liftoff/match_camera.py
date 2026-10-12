"""Recover camera from SIFT correspondences and ray-cast world anchors.
Run normal Python for match/solve, Blender for rays (see README).
"""
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('mode',choices=['match','rays','solve']);p.add_argument('--directory',type=Path,required=True)
import sys
a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)
d=a.directory
if a.mode=='match':
 import cv2
 im=cv2.imread(str(d/'probe.png'));ref=cv2.imread(str(d.parent/'liftoff_refs/teaser2_lastframe.png'))
 ref=cv2.resize(ref,(im.shape[1],im.shape[0]))
 sift=cv2.SIFT_create(nfeatures=12000,contrastThreshold=.012)
 k1,x1=sift.detectAndCompute(im,None);k2,x2=sift.detectAndCompute(ref,None)
 matches=[m for m,n in cv2.BFMatcher().knnMatch(x1,x2,k=2) if m.distance<.72*n.distance]
 points=[{'probe':k1[m.queryIdx].pt,'reference':k2[m.trainIdx].pt} for m in matches]
 (d/'matches.json').write_text(json.dumps({'size':[im.shape[1],im.shape[0]],'points':points},indent=2))
 print('matches',len(points))
elif a.mode=='rays':
 import bpy
 from mathutils import Vector
 s=bpy.context.scene;s.frame_set(488);c=s.camera;c.animation_data_clear();c.constraints.clear();c.location=(40,-18,1.5);c.rotation_mode='XYZ';c.rotation_euler=(Vector((0,80,45))-c.location).to_track_quat('-Z','Y').to_euler();c.data.lens=16
 bpy.data.objects["FogVolume"].hide_viewport=True
 bpy.context.view_layer.update()
 m=json.loads((d/'matches.json').read_text());w,h=m['size'];f=w*c.data.lens/c.data.sensor_width
 points=[]
 for x in m['points']:
  u,v=x['probe'];direction=c.matrix_world.to_quaternion()@Vector(((u-w/2)/f,(h/2-v)/f,-1)).normalized()
  hit,loc,normal,index,obj,matrix=s.ray_cast(bpy.context.evaluated_depsgraph_get(),c.location,direction)
  # Fog box is not a photographic surface; temporarily disable it from raycasts below.
  if hit:
   x.update(world=list(loc),object=obj.name);points.append(x)
 (d/'anchors.json').write_text(json.dumps({'size':[w,h],'focal':f,'points':points},indent=2))
 print('anchors',len(points))
else:
 import cv2,numpy as np
 m=json.loads((d/'anchors.json').read_text());w,h=m['size'];f=w*12/36
 points=[x for x in m['points'] if x['object']!='FogVolume']
 world=np.float64([x['world'] for x in points]);uv=np.float64([x['reference'] for x in points]);K=np.float64([[f,0,w/2],[0,f,h/2],[0,0,1]])
 ok,r,t,ids=cv2.solvePnPRansac(world,uv,K,None,iterationsCount=1000,reprojectionError=3,flags=cv2.SOLVEPNP_EPNP)
 if not ok or len(ids)<12:raise RuntimeError('No reliable camera solve (need 12 inliers)')
 r,t=cv2.solvePnPRefineLM(world[ids[:,0]],uv[ids[:,0]],K,None,r,t)
 R=cv2.Rodrigues(r)[0];center=-R.T@t;blender_R=R.T@np.diag([1,-1,-1]);M=np.eye(4);M[:3,:3]=blender_R;M[:3,3]=center[:,0]
 proj=cv2.projectPoints(world[ids[:,0]],r,t,K,None)[0][:,0,:];err=np.linalg.norm(proj-uv[ids[:,0]],axis=1)
 result={'matrix':M.tolist(),'lens':12,'inliers':len(ids),'total':len(points),'rms_pixels':float(np.sqrt(np.mean(err**2))),'location':center[:,0].tolist()}
 (d/'camera_free_match.json').write_text(json.dumps(result,indent=2))
 from scipy.optimize import minimize_scalar
 # Constrain the final fit to the historical 12mm camera rail: fixed height,
 # level horizon and the original aim point. This avoids noisy roll/height.
 keep=ids[:,0]
 def rail(x):
  center=np.array([x,32-(x-5)*50/35,1.5])
  z=center-np.array([0,80,45]);z/=np.linalg.norm(z)
  right=np.cross([0,0,1],z);right/=np.linalg.norm(right)
  rotation=np.array([right,np.cross(z,right),z]).T
  local=(world-center)@rotation
  projection=np.stack([w/2-f*local[:,0]/local[:,2],h/2+f*local[:,1]/local[:,2]],1)
  return center,rotation,projection
 fit=minimize_scalar(lambda x:np.mean((rail(x)[2][keep]-uv[keep])**2),bounds=(25,40),method='bounded')
 center,rotation,projection=rail(fit.x)
 matrix=np.eye(4);matrix[:3,:3]=rotation;matrix[:3,3]=center
 result.update(matrix=matrix.tolist(),location=center.tolist(),rms_pixels=float(np.sqrt(np.mean(np.sum((projection[keep]-uv[keep])**2,axis=1)))),method='SIFT + raycast + RANSAC, constrained to historical camera rail')
 if result['rms_pixels']>3:raise RuntimeError('Camera match exceeds 3 pixels RMS')
 (d/'camera_path_match.json').write_text(json.dumps(result,indent=2));print(result)
