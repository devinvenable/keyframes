"""Read-only compositor/VSE inventory, including nested grade node groups.

blender -b --python inspect_grade.py -- OUTPUT.json INPUT.blend ...
"""
import json
from pathlib import Path
import sys

import bpy


def simple(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return list(value)
    except TypeError:
        return str(value)


def properties(item):
    return {p.identifier: simple(getattr(item, p.identifier))
            for p in item.bl_rna.properties
            if not p.is_readonly and p.type in {'BOOLEAN', 'INT', 'FLOAT', 'STRING', 'ENUM'}}


def tree_report(tree):
    if tree is None:
        return None
    nodes = []
    for n in tree.nodes:
        data = dict(name=n.name, type=n.bl_idname, properties=properties(n),
                    inputs=[dict(name=i.name, value=simple(i.default_value))
                            for i in n.inputs if hasattr(i, 'default_value')])
        if getattr(n, 'node_tree', None):
            data['group'] = tree_report(n.node_tree)
        if getattr(n, 'image', None):
            data['image'] = dict(name=n.image.name, filepath=bpy.path.abspath(n.image.filepath),
                                 source=n.image.source)
        if hasattr(n, 'mapping'):
            data['curves'] = [[list(p.location) for p in c.points] for c in n.mapping.curves]
        if hasattr(n, 'color_ramp'):
            data['ramp'] = [(e.position, list(e.color)) for e in n.color_ramp.elements]
        nodes.append(data)
    return dict(name=tree.name, nodes=nodes,
                links=[(l.from_node.name, l.from_socket.name, l.to_node.name, l.to_socket.name)
                       for l in tree.links])


out, *paths = sys.argv[sys.argv.index('--') + 1:]
report = []
for path in paths:
    bpy.ops.wm.open_mainfile(filepath=path, load_ui=False, use_scripts=False)
    scenes = []
    for s in bpy.data.scenes:
        tree = getattr(s, 'compositing_node_group', None) or getattr(s, 'node_tree', None)
        strips = []
        if s.sequence_editor:
            seqs = getattr(s.sequence_editor, 'strips_all', None)
            if seqs is None:
                seqs = s.sequence_editor.sequences_all
            for strip in seqs:
                entry = properties(strip)
                entry['modifiers'] = [properties(m) for m in strip.modifiers]
                if hasattr(strip, 'elements'):
                    entry['elements'] = [e.filename for e in strip.elements]
                if hasattr(strip, 'color_balance'):
                    entry['color_balance'] = properties(strip.color_balance)
                strips.append(entry)
        scenes.append(dict(name=s.name, use_nodes=getattr(s, 'use_nodes', None),
                           use_compositing=s.render.use_compositing,
                           use_sequencer=s.render.use_sequencer,
                           output=s.render.filepath, range=[s.frame_start, s.frame_end],
                           color=properties(s.view_settings), tree=tree_report(tree), strips=strips))
    report.append(dict(path=path, scenes=scenes))
Path(out).write_text(json.dumps(report, indent=2))
print('GRADE_INVENTORY', out)
