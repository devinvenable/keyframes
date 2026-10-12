"""Opt-in footage continuity preparation for NEW shots, not a T305/T306 patch.

The saved mountain-valley scene carries a single reflective rust override on
the robot. Restore the native mesh's ten material assignments and skin weights
on the existing scene rig. Keep the original HDRI for light; camera rays sample
its upper sky so wider views do not expose the photographed hillside. Ground
textures and sandstone assets remain the source assets. This is a documented
continuity reconstruction, not a claim of pixel-identical teaser restoration.
"""
from pathlib import Path
import bpy


DEFAULT_ROBOT = Path('/home/devin/src/2026/voxel-shorts/assets/character-kaiju-robot.blend')


def restore_teaser_state(robot_asset=DEFAULT_ROBOT, film_grade=True):
    s=bpy.context.scene
    robot=bpy.data.objects['kaiju_robot_mesh']
    assert 'teaser_state_restoration' not in s, 'Restore only once, from original scene'
    with bpy.data.libraries.load(str(robot_asset),link=False) as (src,dst):
        assert 'kaiju_robot_mesh' in src.objects
        dst.objects=['kaiju_robot_mesh']
    native=dst.objects[0]
    assert len(native.data.materials)==10, 'Unexpected native robot material contract'
    names=[g.name for g in native.vertex_groups]
    native_mesh=native.data.copy()
    # The vertex group names belong to the object; indices/weights to its mesh.
    # Recreate the original names in their exact order before swapping mesh data.
    robot.vertex_groups.clear()
    for name in names:robot.vertex_groups.new(name=name)
    robot.data=native_mesh
    robot.data.name='Teaser | native robot with original material assignments'
    bpy.data.objects.remove(native,do_unlink=True)
    assert all(g.name in robot.parent.pose.bones for g in robot.vertex_groups)
    eye=next(m for m in robot.data.materials if m.name.split('.')[0]=='eye_lens')
    assert eye.node_tree.nodes.get('Principled BSDF').inputs['Emission Strength'].default_value==0
    # Asset-master red boots/arm insets are not visible as red in the accepted
    # footage. Preserve all ten assignments; grade separate shot copies against
    # liftoff_refs/teaser2_lastframe.png (PM review, 2026-10-11).
    film_palette={'gunmetal':(.042,.050,.058), 'red_boot':(.025,.030,.034),
                  'accent_red':(.030,.032,.035), 'emerald':(.026,.033,.033)}
    if film_grade:
        for i,mat in enumerate(robot.data.materials):
            original_name=mat.name.split('.')[0]
            copy=mat.copy();copy.name='Teaser | '+original_name
            copy['native_material']=original_name
            if original_name in film_palette:
                copy.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=(*film_palette[original_name],1)
            robot.data.materials[i]=copy

    # Retain the original photographic overcast light and sky; remap only the
    # camera's sampling direction above the HDRI's unrelated rural horizon.
    n,l=s.world.node_tree.nodes,s.world.node_tree.links
    env=n.get('Environment Texture');bg=n.get('Background');output=n.get('World Output')
    assert env and bg and output and env.inputs['Vector'].is_linked
    sky=n.new('ShaderNodeTexEnvironment');sky.name='Teaser | upper sky only';sky.image=env.image
    lift=n.new('ShaderNodeVectorMath');lift.operation='ADD';lift.inputs[1].default_value=(0,0,.8)
    l.new(env.inputs['Vector'].links[0].from_socket,lift.inputs[0]);l.new(lift.outputs[0],sky.inputs[0])
    sky_bg=n.new('ShaderNodeBackground');sky_bg.inputs['Strength'].default_value=bg.inputs['Strength'].default_value
    l.new(sky.outputs[0],sky_bg.inputs['Color'])
    ray=n.new('ShaderNodeLightPath');mix=n.new('ShaderNodeMixShader')
    l.new(ray.outputs['Is Camera Ray'],mix.inputs[0]);l.new(bg.outputs[0],mix.inputs[1])
    l.new(sky_bg.outputs[0],mix.inputs[2]);l.new(mix.outputs[0],output.inputs['Surface'])

    # Expand the textured ground past the wide-shot horizon without stretching
    # its texel scale. Its material remains the original aerial-rocks PBR graph.
    ground=bpy.data.objects['GroundPlane']
    for v in ground.data.vertices:v.co*=10
    for uv in ground.data.uv_layers.active.data:uv.uv*=10
    # A height falloff prevents the original constant-density fog box from
    # reading as an opaque white platform when photographed from above its top.
    m=bpy.data.materials['FogMaterial'];n,l=m.node_tree.nodes,m.node_tree.links
    vol=n.get('Volume Scatter');vol.inputs['Color'].default_value=(.60,.66,.72,1)
    for v in bpy.data.objects['FogVolume'].data.vertices:
        v.co.z=(v.co.z+3)*2-3
    coord=n.new('ShaderNodeTexCoord');sep=n.new('ShaderNodeSeparateXYZ')
    l.new(coord.outputs['Generated'],sep.inputs[0])
    falloff=n.new('ShaderNodeMapRange');falloff.clamp=True
    falloff.inputs['From Min'].default_value=.15;falloff.inputs['From Max'].default_value=1
    falloff.inputs['To Min'].default_value=1;falloff.inputs['To Max'].default_value=0
    l.new(sep.outputs['Z'],falloff.inputs['Value'])
    power=n.new('ShaderNodeMath');power.operation='POWER';power.inputs[1].default_value=2
    l.new(falloff.outputs[0],power.inputs[0])
    density=n.new('ShaderNodeMath');density.operation='MULTIPLY';density.inputs[1].default_value=.025
    l.new(power.outputs[0],density.inputs[0]);l.new(density.outputs[0],vol.inputs['Density'])
    report={'robot_asset':str(robot_asset),'robot_materials':[m.name for m in robot.data.materials],
            'robot_vertices':len(robot.data.vertices),'robot_faces':len(robot.data.polygons),
            'sky':'original overcast HDRI; upper-sky remap for camera rays only',
            'ground':'original PBR textures, expanded 10x with matching UV scale',
            'fog':'original volume with quadratic height falloff',
            'film_grade':film_grade,'film_palette_linear_rgb':film_palette if film_grade else {}}
    s['teaser_state_restoration']=str(report)
    return report


if __name__=='__main__':
    import argparse,json,sys
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--robot-asset',type=Path,default=DEFAULT_ROBOT)
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    assert a.output.resolve()!=Path(bpy.data.filepath).resolve(), 'Never overwrite source scene'
    for im in bpy.data.images:
        if im.filepath:im.filepath=bpy.path.abspath(im.filepath)
    report=restore_teaser_state(a.robot_asset)
    bpy.ops.file.pack_all();a.output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(a.output))
    a.output.with_suffix('.restoration.json').write_text(json.dumps(report,indent=2)+'\n')
