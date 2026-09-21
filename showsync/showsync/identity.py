"""Desktop identity shared by direct launches and embedded Qt windows."""
from pathlib import Path
import sys

from PySide6.QtGui import QGuiApplication, QIcon

APP_NAME = 'showsync'


def application_arguments():
    # XCB derives WM_CLASS from argv[0] and -name, before any window exists.
    return [APP_NAME, '-name', APP_NAME] if sys.platform.startswith('linux') else [APP_NAME]


def configure_identity():
    QGuiApplication.setApplicationName(APP_NAME)
    QGuiApplication.setApplicationDisplayName(APP_NAME)
    QGuiApplication.setDesktopFileName(APP_NAME)
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addFile(str(Path(__file__).parent / 'icons' / f'showsync-{size}.png'))
    QGuiApplication.setWindowIcon(icon)
    return icon
