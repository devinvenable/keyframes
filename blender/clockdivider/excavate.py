"""Read curve datablocks without opening or changing any workshop scene."""
import bpy
import json
from pathlib import Path

root = Path.home() / 'src/blender'
records = []
for path in sorted(root.rglob('*.blend')):
    try:
        with bpy.data.libraries.load(str(path), link=False) as (source, dest):
            dest.curves = source.curves
        texts = []
        for curve in dest.curves:
            if isinstance(curve, bpy.types.TextCurve):
                texts.append({'name': curve.name, 'body': curve.body,
                              'font': curve.font.filepath,
                              'font_name': curve.font.name})
        records.append({'path': str(path), 'texts': texts})
        for curve in dest.curves:
            if curve:
                bpy.data.curves.remove(curve)
    except Exception as exc:
        records.append({'path': str(path), 'error': str(exc)})
    print('EXCAVATED', path, texts if 'texts' in locals() else [], flush=True)
Path('generated/clockdivider/excavation.json').write_text(json.dumps(records, indent=2))
