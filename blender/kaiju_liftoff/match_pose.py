"""Fit body placement and the firing arm to measured teaser image landmarks.
The original .blend provides geometry, but the exported frame is authoritative.
Run with ordinary Python (NumPy and SciPy), not Blender.
"""
import json
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

base=Path(__file__).parent
landmarks=json.loads((base/'pose_landmarks.json').read_text())
camera=json.loads((base/'camera_match.json').read_text())
matrix=np.array(camera['matrix']);width,height=landmarks['resolution']
focal=width*camera['lens']/36
origin=np.array([0,80,-2]);pivot=np.array([-22.1,80,63])


def project(points):
    local=(points-matrix[:3,3])@matrix[:3,:3]
    return np.stack([width/2-focal*local[:,0]/local[:,2],
                     height/2+focal*local[:,1]/local[:,2]],axis=1)


def transform(points,parameters):
    dx,dz,scale=parameters
    return (points-origin)*scale+origin+[dx,0,dz]


def inputs(name):
    return (np.array([p['world'] for p in landmarks[name]]),
            np.array([p['reference'] for p in landmarks[name]]))


def rms(projected,reference):
    return float(np.sqrt(np.mean(np.sum((projected-reference)**2,axis=1))))


body,body_reference=inputs('body')
body_fit=least_squares(lambda p:(project(transform(body,p))-body_reference).flatten(),
    [0,0,1],bounds=([-1.5,-2,.98],[1.5,2,1.02]),loss='soft_l1',f_scale=1)
arm,arm_reference=inputs('arm')


def arm_transform(v):
    rotated=Rotation.from_rotvec(v).apply(arm-pivot)+pivot
    return transform(rotated,body_fit.x)


arm_fit=least_squares(lambda v:(project(arm_transform(v))-arm_reference).flatten(),
    [.1,0,-.1],loss='soft_l1',f_scale=.7,max_nfev=2000)
fit=dict(body_offset_xz=body_fit.x[:2].tolist(),body_scale_ratio=float(body_fit.x[2]),
    arm_world_rotation_vector=arm_fit.x.tolist(),
    arm_quaternion_wxyz=np.roll(Rotation.from_rotvec(arm_fit.x).as_quat(),1).tolist(),
    arm_rms_pixels=rms(project(arm_transform(arm_fit.x)),arm_reference),
    body_rms_pixels=rms(project(transform(body,body_fit.x)),body_reference),
    resolution=landmarks['resolution'],reference_sha256=landmarks['reference_sha256'])
if fit['arm_rms_pixels']>2 or fit['body_rms_pixels']>2:
    raise RuntimeError('Join pose fit exceeds two preview pixels')
(base/'pose_match.json').write_text(json.dumps(fit,indent=2))
print(json.dumps(fit,indent=2))
