"""Rigid bronze beetle-knight kit. Blender Python; +Z up, face toward -Y."""
import math
import bpy
from mathutils import Vector

COLLECTION = 'BEETLE | bronze knight'


def build():
    coll = bpy.data.collections.new(COLLECTION)
    bpy.context.scene.collection.children.link(coll)

    def link(o, name, parent=None, loc=(0, 0, 0)):
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
        o.name = 'BK | ' + name
        o.parent = parent
        o.location = loc
        return o

    def material(name, color, metal=0.8, rough=0.35, glow=0, weather=False):
        m = bpy.data.materials.new('BK | ' + name)
        m.diffuse_color = (*color, 1)
        m.use_nodes = True
        n, l = m.node_tree.nodes, m.node_tree.links
        bs = n.get('Principled BSDF')
        bs.inputs['Base Color'].default_value = (*color, 1)
        bs.inputs['Metallic'].default_value = metal
        bs.inputs['Roughness'].default_value = rough
        if glow:
            bs.inputs['Emission Color'].default_value = (*color, 1)
            bs.inputs['Emission Strength'].default_value = glow
        if weather:
            tex = n.new('ShaderNodeTexNoise')
            tex.inputs['Scale'].default_value = 2.2
            tex.inputs['Detail'].default_value = 3
            coord = n.new('ShaderNodeTexCoord')
            l.new(coord.outputs['Object'], tex.inputs['Vector'])
            ramp = n.new('ShaderNodeValToRGB')
            ramp.color_ramp.elements[0].position = .23
            ramp.color_ramp.elements[0].color = (*(v * .24 for v in color), 1)
            ramp.color_ramp.elements[1].position = .78
            ramp.color_ramp.elements[1].color = (*color, 1)
            l.new(tex.outputs['Fac'], ramp.inputs[0])
            l.new(ramp.outputs[0], bs.inputs['Base Color'])
            bump = n.new('ShaderNodeBump')
            bump.inputs['Strength'].default_value = .16
            bump.inputs['Distance'].default_value = .045
            l.new(tex.outputs['Fac'], bump.inputs['Height'])
            l.new(bump.outputs[0], bs.inputs['Normal'])
        return m

    bronze = material('cast bronze plates', (.40, .205, .075), weather=True)
    edge = material('worn brass edges', (.60, .35, .135), .82, .3)
    dark = material('dark joint iron', (.032, .038, .039), .72, .4)
    inset = material('recessed oxidized bronze', (.105, .069, .034), weather=True)
    amber = material('amber reactor glass', (1, .42, .045), .1, .24, 4)

    def empty(name, parent=None, loc=(0, 0, 0), axis='XYZ', limits=''):
        o = link(bpy.data.objects.new(name, None), name, parent, loc)
        o.empty_display_type = 'ARROWS'
        o.empty_display_size = 3
        o['joint_axes'] = axis
        o['recommended_limits_degrees'] = limits
        return o

    def finish(o, mat, bevel=0):
        o.data.materials.append(mat)
        if bevel:
            mod = o.modifiers.new('Machined edge', 'BEVEL')
            mod.width, mod.segments = bevel, 1
            o.modifiers.new('Face weighted normals', 'WEIGHTED_NORMAL')
        return o

    def cube(name, loc, dims, mat, parent, bevel=.18):
        bpy.ops.mesh.primitive_cube_add(size=1)
        o = link(bpy.context.object, name, parent, loc)
        for v in o.data.vertices:
            v.co *= Vector(dims)
        return finish(o, mat, bevel)

    def cone(name, loc, r1, r2, depth, mat, parent, sides=8, axis='Z'):
        bpy.ops.mesh.primitive_cone_add(vertices=sides, radius1=r1, radius2=r2, depth=depth)
        o = link(bpy.context.object, name, parent, loc)
        if axis == 'Y':
            o.rotation_euler.x = math.pi / 2
        elif axis == 'X':
            o.rotation_euler.y = math.pi / 2
        return finish(o, mat, .06)

    def mesh(name, verts, faces, mat, parent, loc=(0, 0, 0), bevel=.10):
        me = bpy.data.meshes.new(name)
        me.from_pydata(verts, [], faces)
        me.update()
        o = link(bpy.data.objects.new(name, me), name, parent, loc)
        return finish(o, mat, bevel)

    def plaque(name, points, y, thick, mat, parent):
        # Extruded XZ polygon: every panel is a closed rigid solid.
        verts = [(x, y + d, z) for d in (0, thick) for x, z in points]
        k = len(points)
        faces = [tuple(range(k - 1, -1, -1)), tuple(range(k, 2 * k))]
        faces += [(i, (i + 1) % k, (i + 1) % k + k, i + k) for i in range(k)]
        return mesh(name, verts, faces, mat, parent)

    def rivet(name, loc, parent, axis='Y', radius=.32):
        return cone(name + ' | hex rivet', loc, radius, radius, .23, edge, parent, 6, axis)

    def band(name, z, height, rx0, ry0, rx1, ry1, start, end, parent, mat=bronze, steps=4):
        # A thick, faceted strip of shell; radial seams remain real gaps.
        verts = []
        for inner in (False, True):
            for zz, rx, ry in ((z, rx0, ry0), (z + height, rx1, ry1)):
                for j in range(steps + 1):
                    ang = start + (end - start) * j / steps
                    verts.append(((rx - .8 * inner) * math.sin(ang),
                                  -(ry - .8 * inner) * math.cos(ang), zz))
        row = steps + 1
        faces = []
        for j in range(steps):
            faces += [(j, j + 1, row + j + 1, row + j),
                      (2 * row + j, 3 * row + j, 3 * row + j + 1, 2 * row + j + 1),
                      (j, 2 * row + j, 2 * row + j + 1, j + 1),
                      (row + j, row + j + 1, 3 * row + j + 1, 3 * row + j)]
        faces += [(0, row, 3 * row, 2 * row),
                  (steps, 2 * row + steps, 3 * row + steps, row + steps)]
        return mesh(name, verts, faces, mat, parent, bevel=.13)

    root = empty('ROOT | placement', limits='Uniform scale only')
    root['design_reference'] = 'kaiju_beetle_voxel.png'
    root['construction'] = 'Rigid faceted solids; no armature, skinning or subdivision'
    pelvis = empty('pelvis', root, (0, 0, 34), limits='Body translate / actor crouch')
    waist = empty('waist', pelvis, (0, 0, 4), limits='X +/-20; Y +/-12; Z +/-25')
    cube('hip chassis', (0, 0, 0), (22, 14, 7), dark, pelvis, 1)
    for sign, side in [(-1, 'L'), (1, 'R')]:
        pts = [(sign*x, z) for x, z in [(1, 4), (11, 6), (16, 2), (14, -7), (5, -5)]]
        plaque('hip tasset ' + side, pts, -9, 2.6, bronze, pelvis)
        for x, z in [(6, 2), (12, 1)]:
            rivet('hip ' + side, (sign*x, -9.18, z), pelvis)
    cone('waist rotary bearing', (0, 0, 0), 10, 10, 4, dark, waist, 12)
    # Five abdominal courses: each side is an independent curved armor plate.
    for i, (rx, ry) in enumerate([(13, 9), (15, 10.5), (17, 12), (18.5, 12.8), (18, 12.5)]):
        z = i * 5
        for sign, side in [(-1, 'L'), (1, 'R')]:
            lo, hi = ((-1.49, -.025) if sign < 0 else (.025, 1.49))
            band(f'abdomen {i+1:02} {side}', z, 4.6, rx, ry, rx+.4, ry+.2, lo, hi, waist)
            for ang in [sign*.16, sign*1.23]:
                rivet(f'abdomen {i+1} {side}', (rx*math.sin(ang), -ry*math.cos(ang)-.24, z+2.2), waist)
    # Split beetle elytra are faceted shells on real dorsal hinge axes.
    for sign, side in [(-1, 'L'), (1, 'R')]:
        wing = empty('elytron hinge ' + side, waist, axis='Z', limits='Z outward 0..25')
        for i in range(4):
            lo, hi = ((math.pi+.025, math.tau-1.60) if sign < 0 else (1.60, math.pi-.025))
            band(f'elytron {side} course {i+1}', -1+i*6.3, 5.95,
                 15+i*.8, 12.5, 16+i*.6, 13.3, lo, hi, wing, steps=4)
        cube('dorsal seam ' + side, (sign*.7, 13, 10), (.65, .8, 24), edge, wing)
    plaque('chest reactor bezel', [(-7, 21), (7, 21), (0, 13)], -13.65, 1.5, dark, waist)
    plaque('chest amber triangle', [(-5.6, 20.2), (5.6, 20.2), (0, 14.25)], -13.82, .22, amber, waist)
    neck = empty('neck', waist, (0, 0, 26), limits='X -25..15; Z +/-30')
    cone('neck swivel', (0, 0, 0), 8, 8, 4, dark, neck, 12)
    # Helmet dome made from six latitudinally faceted solid wedges.
    for j in range(6):
        lo = -math.pi + j*math.tau/6 + .016
        hi = lo + math.tau/6 - .032
        for z, h, a, b, c, d in [(2, 8, 15, 12, 14, 11.5),
                                  (10, 6, 14, 11.5, 10, 8.8),
                                  (16, 3.5, 10, 8.8, 2.2, 2.2)]:
            band(f'helmet wedge {j+1} z{z}', z, h, a, b, c, d, lo, hi, neck, steps=2)
    cube('face underplate', (0, -10.6, 6.8), (23, 3, 9), dark, neck, 1)
    for sign, side in [(-1, 'L'), (1, 'R')]:
        pts = [(sign*x, z) for x, z in [(1.6, 10), (11.3, 11.3), (10, 6.7), (4, 7.2)]]
        plaque('eye socket ' + side, pts, -12.8, .8, edge, neck)
        pts = [(sign*x, z) for x, z in [(2.8, 9.4), (10, 10.3), (9.1, 7.65), (4.4, 8)]]
        plaque('amber eye ' + side, pts, -12.98, .18, amber, neck)
        plaque('mandible ' + side, [(sign*x,z) for x,z in [(2,0), (10,1), (12,4), (8,4.6), (5,2.3), (2,3)]], -13.2, 2, bronze, neck)
        for z in [-2.2, -.8]:
            cube('jaw grille ' + side, (sign*5, -10.5, z), (9, 1.2, .55), edge, neck, .06)
        rivet('temple '+side, (sign*12, -8.7, 13), neck)
    # A short crown spike plus the defining stacked, spiral-ridged drill horn.
    cone('crown spur', (0, 4.5, 22), 2.6, .05, 11, bronze, neck)
    drill = empty('drill spindle', neck, (0, -10, 11.5), axis='Z', limits='Z continuous; fixed 22 degree rake')
    drill.rotation_euler.x = math.radians(22)
    drill.scale=(1.42,1.42,.90)
    cone('horn socket', (0, 0, 1), 5.1, 4.8, 3, dark, drill, 10)
    for i in range(7):
        r = 4.7*(1-i/7)
        cone(f'drill cone {i+1:02}', (0, 0, 3+i*3.6), r, max(.08,r-.85), 4.1, bronze, drill, 8)
    # Continuous angular flight around the stacked cones, with finite thickness.
    verts, faces = [], []
    count = 112
    for i in range(count+1):
        t=i/count; ang=t*math.tau*3.3; radius=4.55*(1-t)+.10; z=1.3+26.7*t
        for dr,dz in [(0,-.34),(.60,-.24),(.60,.24),(0,.34)]:
            verts.append(((radius+dr)*math.cos(ang),(radius+dr)*math.sin(ang),z+dz))
    for i in range(count):
        for j in range(4): faces.append((i*4+j,i*4+(j+1)%4,(i+1)*4+(j+1)%4,(i+1)*4+j))
    faces.extend([(3,2,1,0),tuple(range(count*4,count*4+4))])
    mesh('drill | continuous helical cutting ridge', verts, faces, edge, drill, bevel=.035)

    for sign, side in [(-1, 'L'), (1, 'R')]:
        shoulder = empty('shoulder '+side, waist, (sign*20, 0, 21), limits='X -100..35; Y +/-35; Z +/-25')
        cone('shoulder axle '+side, (0,0,0), 4,4,8,dark,shoulder,10,'X')
        cube('pauldron '+side, (sign*1.2,0,0), (11,17,10), bronze,shoulder,2)
        cube('pauldron crest '+side, (sign*1.2,-.5,4.7), (10,15,1),edge,shoulder,.3)
        for x in [-3,3]:
            rivet('pauldron '+side,(x,-8.65,0),shoulder,radius=.45)
        cube('upper arm chassis '+side, (0,0,-8), (5,6,12),dark,shoulder,.6)
        for i in range(2):
            cube('upper arm plate '+side+str(i), (0,-1,-6-i*4.7),(8,9,4.3),bronze,shoulder,.65)
        elbow = empty('elbow '+side,shoulder,(0,0,-15),axis='X',limits='X -110..0')
        cone('elbow hinge '+side,(0,0,0),3.4,3.4,8.5,dark,elbow,10,'X')
        cone('elbow cap '+side,(sign*4.5,0,0),2.7,2.7,.7,edge,elbow,8,'X')
        for i in range(3):
            cube('gauntlet plate '+side+str(i),(0,-.2,-3.5-i*3.5),(8.6-i*.7,9-i*.6,3.2),bronze,elbow,.7)
            rivet('gauntlet '+side,(sign*2,-4.85+i*.3,-3.5-i*3.5),elbow)
        wrist = empty('wrist '+side,elbow,(0,0,-13),axis='XYZ',limits='XYZ +/-20')
        cube('palm '+side,(0,0,-1.2),(7,6,5),dark,wrist,.6)
        for k,x in enumerate([-2.4,0,2.4]):
            finger=empty(f'claw {side}{k+1}',wrist,(x,-1,-3),axis='X',limits='X -55..10')
            cube(f'claw knuckle {side}{k+1}',(0,0,-1.9),(1.8,3,4.2),bronze,finger,.35)
            plaque(f'claw hook {side}{k+1}',[(-.75,-3.5),(.75,-3.5),(.6,-6.5),(0,-7.2),(-.8,-5.5)],-1.5,2,edge,finger)
        hip=empty('hip '+side,pelvis,(sign*10,0,-1),limits='X +/-35; Y +/-15; Z +/-15')
        cone('hip bearing '+side,(0,0,0),4,4,10,dark,hip,10,'X')
        cube('thigh chassis '+side,(0,0,-6),(7,8,12),dark,hip,.8)
        for i in range(2):
            cube('thigh armor '+side+str(i),(0,-1,-4-i*5.5),(11,12,5),bronze,hip,1)
            for x in [-3.8,3.8]:rivet('thigh '+side,(x,-7.15,-4-i*5.5),hip)
        knee=empty('knee '+side,hip,(0,0,-13),axis='X',limits='X 0..75')
        cone('knee axle '+side,(0,0,0),3.8,3.8,12,dark,knee,10,'X')
        cube('kneecap '+side,(0,-5.5,0),(10,4,7),edge,knee,1)
        cube('shin chassis '+side,(0,0,-8),(7,8,15),dark,knee,.6)
        for i in range(3):
            cube('greave '+side+str(i),(0,-1,-4-i*4.2),(11.8-i*.6,12-i*.2,3.9),bronze,knee,.7)
            for x in [-4,4]:rivet('greave '+side,(x,-7.2+i*.1,-4-i*4.2),knee)
        ankle=empty('ankle '+side,knee,(0,0,-16),limits='X +/-25; Y +/-12')
        cube('foot '+side,(0,-3,-1),(13,19,6),bronze,ankle,1)
        for x in [-3.7,0,3.7]:
            cube('toe armor '+side,(x,-11.2,-1.2),(3.4,4.2,3.5),edge,ankle,.4)
        cube('sole '+side,(0,-3,-3.65),(13.3,19.3,1),dark,ankle,.22)
    # Origin at floor in neutral stance (sole z = -0.15).
    pelvis.location.z += .15
    for o in coll.objects:
        if o.type == 'MESH':
            o['rigid_part'] = True
    bpy.context.view_layer.update()
    return root, coll
