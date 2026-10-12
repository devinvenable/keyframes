"""Higher-detail, ballistic powder bursts for the final miniature-set landing.

Procedural volumes, not a buoyant gas sim: individual lobes launch unevenly from
both soles, break up, sink and dilute. Angular particulate supplies falling mass.
"""
import math
import random
import bpy
from mathutils import Vector, noise


def build(interp,key):
    rng=random.Random(31160);s=bpy.context.scene;s.frame_set(52);bpy.context.view_layer.update()
    feet=[bpy.data.objects['BK | sole '+side].matrix_world.translation.copy() for side in ('L','R')]
    materials=[]
    for j in range(5):
        m=bpy.data.materials.new(f'Arrival | fullers earth {j}');m.use_nodes=True
        n,l=m.node_tree.nodes,m.node_tree.links;n.clear()
        out=n.new('ShaderNodeOutputMaterial');vol=n.new('ShaderNodeVolumeScatter')
        vol.inputs['Color'].default_value=(.52+j*.025,.385+j*.023,.235+j*.020,1)
        vol.inputs['Anisotropy'].default_value=.18
        coord=n.new('ShaderNodeTexCoord')
        offset=n.new('ShaderNodeVectorMath');offset.operation='ADD';offset.inputs[1].default_value=(j*2.17,j*.71,j*1.31)
        l.new(coord.outputs['Generated'],offset.inputs[0])
        broad=n.new('ShaderNodeTexNoise');broad.inputs['Scale'].default_value=4.5;broad.inputs['Detail'].default_value=4
        l.new(offset.outputs[0],broad.inputs['Vector'])
        ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.36;ramp.color_ramp.elements[0].color=(0,0,0,1)
        ramp.color_ramp.elements[1].position=.64;ramp.color_ramp.elements[1].color=(1,1,1,1)
        l.new(broad.outputs['Fac'],ramp.inputs[0])
        fine=n.new('ShaderNodeTexNoise');fine.inputs['Scale'].default_value=23;fine.inputs['Detail'].default_value=3
        l.new(offset.outputs[0],fine.inputs['Vector'])
        grain=n.new('ShaderNodeMath');grain.operation='MULTIPLY';l.new(ramp.outputs[0],grain.inputs[0]);l.new(fine.outputs['Fac'],grain.inputs[1])
        distance=n.new('ShaderNodeVectorMath');distance.operation='DISTANCE';distance.inputs[1].default_value=(.5,.5,.5)
        l.new(coord.outputs['Generated'],distance.inputs[0])
        edge=n.new('ShaderNodeMapRange');edge.clamp=True;edge.inputs['From Min'].default_value=.12;edge.inputs['From Max'].default_value=.51
        edge.inputs['To Min'].default_value=1;edge.inputs['To Max'].default_value=0;l.new(distance.outputs['Value'],edge.inputs[0])
        shape=n.new('ShaderNodeMath');shape.operation='MULTIPLY';l.new(grain.outputs[0],shape.inputs[0]);l.new(edge.outputs[0],shape.inputs[1])
        den=n.new('ShaderNodeMath');den.name='Powder settling density';den.operation='MULTIPLY';l.new(shape.outputs[0],den.inputs[0])
        for f,value in [(1,.9),(52,.9),(56,.8),(62,.53),(70,.22),(80,.065),(92,.015),(108,.002)]:
            den.inputs[1].default_value=value*(.8+j*.10);den.inputs[1].keyframe_insert(data_path='default_value',frame=f)
        l.new(den.outputs[0],vol.inputs['Density']);l.new(vol.outputs[0],out.inputs['Volume']);materials.append(m)
    # Clustered side jets, not evenly spaced points on a circular smoke ring.
    for i in range(44):
        side=i%2;origin=feet[side].copy();origin.z=.6
        angle=rng.choice([-.6,.35,2.5,3.8])+rng.gauss(0,.38)
        direction=Vector((math.cos(angle),math.sin(angle),0))
        origin+=Vector((rng.uniform(-5,5),rng.uniform(-4,4),0))
        speed=rng.uniform(19,62);vz=rng.uniform(6,19);size=10 if i==0 else rng.uniform(4,10)
        birth=52 if i<12 else rng.choice([52,53,54])
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3,radius=1)
        o=bpy.context.object;o.name=f'Arrival | powder {i:02}';o.data.materials.append(materials[i%5])
        seed=Vector((i*.73,i*1.19,i*.31))
        for v in o.data.vertices:v.co*=.88+.26*noise.noise_vector(v.co*3.7+seed).x
        o.rotation_euler=(rng.uniform(-.3,.3),rng.uniform(-.2,.2),angle)
        o['birth_frame']=birth;o['dust_role']='ballistic irregular powder lobe'
        flatten=rng.uniform(.30,.62);width=rng.uniform(.58,1.05)
        for f in range(1,109):
            t=max(0,(f-birth)/24)
            o.location=origin+direction*(speed*(1-math.exp(-t*2.6))/2.6)
            o.location.z=.6+max(0,vz*t-14*t*t)
            grow=.001 if f<birth else interp(f-birth,[(0,.32),(3,.85),(8,1.25),(18,1.5),(56,1.9)])
            # Powders settle into a thin irregular ground veil, not a rising wall.
            settling=max(.22,1-t*.48)
            o.scale=(size*grow,size*grow*width,size*grow*flatten*settling)
            key(o,['location','scale'],f)
    dirt_materials=[]
    for j in range(4):
        mat=bpy.data.materials.new(f'Arrival | particulate earth {j}');mat.use_nodes=True
        bs=mat.node_tree.nodes['Principled BSDF'];bs.inputs['Base Color'].default_value=(.11+j*.05,.067+j*.032,.026+j*.017,1)
        bs.inputs['Roughness'].default_value=.97;dirt_materials.append(mat)
    for i in range(360):
        angle=rng.uniform(0,math.tau);speed=rng.uniform(14,64);vz=rng.uniform(10,39)
        origin=feet[i%2].copy()+Vector((rng.uniform(-6,6),rng.uniform(-5,5),0));origin.z=.2
        radius=rng.uniform(.10,.48) if i<300 else rng.uniform(.45,1.15)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,radius=radius)
        o=bpy.context.object;o.name=f'Arrival | thrown grit {i:03}';o.data.materials.append(dirt_materials[i%4])
        for f in range(1,109):
            t=max(0,(f-52)/24);landing=2*vz/105;u=min(t,landing)
            o.location=origin+Vector((math.cos(angle)*speed*u,math.sin(angle)*speed*u,max(0,vz*u-52.5*u*u)))
            o.rotation_euler=(u*(i%7),u*4,u*5);o.scale=(.001,)*3 if f<52 else (1,.6,.7)
            key(o,['location','rotation_euler','scale'],f)
    s['dust_method']='44 displaced volumetric lobes; two-frequency density erosion; 360 ballistic clumps; no buoyancy; rapid settling.'
    s['dust_spatial_detail']='ico subdivision 3; noise scales 4.5 and 23; Cycles volume step 0.5 (draft 2.0)'
