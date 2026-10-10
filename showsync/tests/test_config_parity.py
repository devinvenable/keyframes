"""Configuration additions need a real UI exposure or an explicit exception."""
import ast
from pathlib import Path
import re

from showsync import config_exposure as exposure
from showsync.cli import build_parser
from showsync.config_dialog import OutputEditor, SetSettingsDialog, SongSettingsDialog
from showsync.device_dialog import DeviceDialog
from showsync.devices import Devices
from showsync.setlist import YAML_FIELDS
from test_devices import rig
from test_gui import document

ROOT = Path(__file__).resolve().parents[2]


def assert_covered(declared, registered):
    assert set(declared) == set(registered), (
        f'Unregistered config: {set(declared) - set(registered)}; '
        f'stale registrations: {set(registered) - set(declared)}')


def test_configuration_surface_has_explicit_exposure(window_factory, tmp_path, qtbot, rig):
    assert_covered([action.dest for action in build_parser()._actions], exposure.CLI)
    assert_covered(YAML_FIELDS, exposure.YAML)
    for section, fields in YAML_FIELDS.items():
        assert_covered(fields, exposure.YAML[section])
    identity = ast.parse((ROOT / 'showsync/showsync/identity.py').read_text())
    assert_covered({node.value for node in ast.walk(identity)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value.startswith('-')}, exposure.QT_IDENTITY)

    # Companion options: AST inspection avoids importing/starting pygame.
    tree = ast.parse((ROOT / 'keyframes/main.py').read_text())
    options = [node.args[0].value for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == 'add_argument']
    assert_covered(options, exposure.KEYFRAMES_CLI)
    launcher_env = set()
    for script, registrations in exposure.LAUNCHER_FLAGS.items():
        source = (ROOT / 'scripts' / script).read_text()
        # Case arms are the shell launcher's declared option surface.
        flags = re.findall(r'^\s*(?:-h\|)?(--[\w-]+)(?:=\*)?\)', source, re.M)
        assert_covered(flags, registrations)
        launcher_env.update(re.findall(r'\$\{?((?:LIVE_|PERFORM_)[A-Z_]+)', source))
    assert_covered(launcher_env | {'DISPLAY', 'TMPDIR'}, exposure.LAUNCHER_ENV)
    qt_keys = set()
    for source in ('gui.py', 'video_window.py'):
        tree = ast.parse((ROOT / 'showsync/showsync' / source).read_text())
        qt_keys.update(node.args[0].value for node in ast.walk(tree)
                       if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                       and node.func.attr in ('value', 'setValue') and node.args
                       and isinstance(node.args[0], ast.Constant)
                       and isinstance(node.args[0].value, str))
    assert_covered(qt_keys, exposure.QT_SETTINGS)

    doc = document(tmp_path)
    instances = {'MainWindow': window_factory(doc), 'DeviceDialog': DeviceDialog(Devices()),
                 'SetSettingsDialog': SetSettingsDialog(doc),
                 'SongSettingsDialog': SongSettingsDialog(doc.rows[0], ()),
                 'OutputEditor': OutputEditor()}
    for name, widget in instances.items():
        if name != 'MainWindow':
            qtbot.addWidget(widget)
    registries = [exposure.CLI, *exposure.YAML.values(), *exposure.LAUNCHER_FLAGS.values(),
                  exposure.LAUNCHER_ENV, exposure.KEYFRAMES_CLI, exposure.QT_SETTINGS,
                  exposure.APP_STATE, exposure.PERFORM_CONF, exposure.PROCESS_ENV,
                  exposure.QT_IDENTITY]
    for registry in registries:
        for name, entry in registry.items():
            assert bool(entry.gui) != bool(entry.cli_only), name
            if entry.gui:
                owner, attribute = entry.gui.split('.')
                assert getattr(instances[owner], attribute) is not None, entry.gui
            else:
                assert len(entry.cli_only.strip()) > 15, name
