"""Independent evaluated-mesh solidity and close fly-with framing contracts."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def mesh(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    data = evaluated.to_mesh()
    vertices = [evaluated.matrix_world @ v.co for v in data.vertices]
    faces = [tuple(p.vertices) for p in data.polygons]
    evaluated.to_mesh_clear()
    return vertices, BVHTree.FromPolygons(vertices, faces)


def parts():
    return [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.name.startswith('BK |')]


def rocks():
    return [o for o in bpy.context.scene.objects if o.type == 'MESH' and
            (o.name.startswith('Reaction | stack') or o.name.startswith('model.'))]


def inside(tree, point):
    # Majority parity in three oblique directions, independent of mesh normals
    # and of the front-envelope rays used by the motion solver.
    votes = 0
    for direction in ((.83,.37,.41),(-.29,.91,.31),(.23,-.41,.88)):
        ray = Vector(direction).normalized(); origin = point.copy(); count = 0
        for _ in range(100):
            hit, _, _, _ = tree.ray_cast(origin, ray, 5000)
            if hit is None: break
            count += 1; origin = hit+ray*.001
        else: raise AssertionError('Collision parity ray did not terminate')
        votes += count % 2
    return votes >= 2


def solidity():
    s = bpy.context.scene; collision = []
    for rock in rocks():
        vertices, tree = mesh(rock)
        lo = [min(v[i] for v in vertices) for i in range(3)]
        hi = [max(v[i] for v in vertices) for i in range(3)]
        collision.append((rock.name, tree, lo, hi))
    rows = []
    # Whole meshes, including legs/feet, against ALL three sandstone objects.
    # Include the strike and every following frame, beyond the review excerpt.
    for f in range(124, 193):
        s.frame_set(f); tested = 0; closest = float('inf')
        for obj in parts():
            vertices, body = mesh(obj); tested += len(vertices)
            for name, rock, lo, hi in collision:
                intersections = rock.overlap(body)
                assert not intersections, f'Rock interpenetration at f{f}: {obj.name} / {name} ({len(intersections)} triangle pairs)'
                for v in vertices:
                    if all(lo[i] <= v[i] <= hi[i] for i in range(3)):
                        assert not inside(rock, v), f'Rock volume contains beetle at f{f}: {obj.name} / {name}'
                    closest = min(closest, rock.find_nearest(v)[3])
        rows.append({'frame': f, 'evaluated_vertices': tested, 'intersections': 0, 'contained_vertices': 0, 'nearest_surface': closest})
    assert rows[0]['nearest_surface'] < .5, 'Beetle misses rock at f124'
    return rows


def framing():
    s = bpy.context.scene; root = bpy.data.objects['BK | ROOT | placement']; rows = []
    reference = None
    for f in range(106, 125):
        s.frame_set(f)
        projected = [world_to_camera_view(s, s.camera, v) for obj in parts() for v in mesh(obj)[0]]
        assert min(v.z for v in projected) > 0, f'Beetle behind camera at f{f}'
        x0,x1 = min(v.x for v in projected), max(v.x for v in projected)
        y0,y1 = min(v.y for v in projected), max(v.y for v in projected)
        height = y1-y0; crop = max(0,-y0)/height
        offset = s.camera.location-root.location
        if reference is None: reference = offset.copy()
        drift = (offset-reference).length
        assert .95 <= height <= 1.3, f'Beetle too small or oversized at f{f}: screen height {height:.3f}'
        assert .04 <= crop <= .20, f'Bottom crop outside close framing at f{f}: {crop:.3f}'
        assert .83 <= y1 <= 1.01 and x0 >= 0 and x1 <= 1, f'Head/side cropped at f{f}'
        assert drift < .002, f'Camera does not fly with beetle at f{f}: relative drift {drift:.3f}'
        rows.append({'frame':f,'height':height,'bottom_crop_fraction':crop,'bounds':[x0,y0,x1,y1],'relative_camera_drift':drift})
    return rows


def flight():
    s = bpy.context.scene; root = bpy.data.objects['BK | ROOT | placement']; points=[]
    for f in range(112,125):
        s.frame_set(f); points.append(root.location.copy())
    speeds = [(b-a).length for a,b in zip(points, points[1:])]
    assert min(speeds)>6.8, 'Airborne collision path loses speed'
    assert max(speeds)-min(speeds)<.002, 'Airborne collision path eases into hit'
    return speeds


def preserved(source):
    s=bpy.context.scene
    def snapshot():
        result={}
        for f in (106,112):
            s.frame_set(f)
            result[f]={o.name:tuple(v for row in o.matrix_world for v in row) for o in s.objects
                       if o.name.startswith(('BK |','Hatch ','Booster ')) or o.name in ('actor_kaiju_robot','kaiju_robot_mesh')}
        return result
    current=snapshot(); saved=bpy.data.filepath
    bpy.ops.wm.open_mainfile(filepath=str(source)); s=bpy.context.scene; original=snapshot()
    error=max(abs(a-b) for f in current for name in current[f] for a,b in zip(current[f][name],original[f][name]))
    assert error < .0002, 'Approved contact or launch pose changed'
    bpy.ops.wm.open_mainfile(filepath=saved)
    return error


def main(a):
    result={'status':'PASS','solidity':solidity(),'framing':framing(),'airborne_speeds':flight(),
            'preserved_contact_launch_error':preserved(a.baseline)}
    if a.negative_checks:
        saved=bpy.data.filepath; bpy.ops.wm.open_mainfile(filepath=str(a.baseline))
        failures={}
        for name, check, expected in [('actual_round_04_solidity',solidity,'Rock interpenetration'),
                                      ('actual_round_04_framing',framing,'Beetle too small')]:
            try: check()
            except AssertionError as error:
                assert str(error).startswith(expected), f'Wrong negative assertion: {error}'
                failures[name]=str(error)
            else: raise AssertionError(f'Actual round_04 passed {name}')
        result['negative_controls']=failures
        result['negative_scene_sha256']=hashlib.sha256(a.baseline.read_bytes()).hexdigest()
        bpy.ops.wm.open_mainfile(filepath=saved)
    (a.directory/'revision_qa.json').write_text(json.dumps(result,indent=2)+'\n')
    print('REVISION_QA',json.dumps({k:v for k,v in result.items() if k not in ('solidity','framing')}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True); p.add_argument('--negative-checks',action='store_true')
    main(p.parse_args(sys.argv[sys.argv.index('--')+1:]))
