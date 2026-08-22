"""PyInstaller recipe for the Windows one-folder Keyframes release."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


PROJECT_ROOT = Path(SPECPATH)
datas = []
binaries = []
hiddenimports = []

# mido selects its backend dynamically.  pygame, OpenCV, NumPy, and
# python-rtmidi load native modules/data at runtime, so collect their runtime
# packages rather than relying on PyInstaller's static import scan.  Exclude
# development examples and tests; they dramatically inflate the release.
def include_runtime_module(name):
    return not any(part in name for part in ('.tests', '.examples', '.conftest'))


for package in ('pygame', 'cv2', 'mido', 'numpy', 'rtmidi'):
    datas += collect_data_files(package)
    binaries += collect_dynamic_libs(package)
    hiddenimports += collect_submodules(package, filter=include_runtime_module)

hiddenimports += ['mido.backends.rtmidi', 'rtmidi._rtmidi']

a = Analysis(
    ['main.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    name='Keyframes',
    exclude_binaries=True,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='Keyframes_Windows',
)
