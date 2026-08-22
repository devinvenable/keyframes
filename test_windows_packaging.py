from pathlib import Path

import main


def test_frozen_application_dir_uses_the_executable_parent(monkeypatch, tmp_path):
    executable = tmp_path / 'Keyframes.exe'
    monkeypatch.setattr(main.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(main.sys, 'executable', str(executable))

    assert main.get_application_dir() == tmp_path


def test_windows_build_scripts_keep_media_external_and_verify_runtime_dependencies():
    root = Path(__file__).parent
    powershell = (root / 'scripts' / 'build_windows.ps1').read_text()
    driver = (root / 'scripts' / 'build-windows.sh').read_text()
    verifier = (root / 'scripts' / 'verify-windows-build.sh').read_text()
    spec = (root / 'keyframes.spec').read_text()

    assert "Copy-Item (Join-Path $repoRoot 'images')" in powershell
    assert 'mapping.json' in powershell
    assert 'Keyframes_Windows.zip' in powershell
    assert '--packaging-smoke-test' in verifier
    assert 'verify-windows-build.sh' in driver
    assert "'mido.backends.rtmidi'" in spec
    assert "for package in ('pygame', 'cv2', 'mido', 'numpy', 'rtmidi')" in spec
    assert 'collect_dynamic_libs(package)' in spec
