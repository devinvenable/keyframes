"""Native Qt file dialogs, parented to the application's main window."""
from pathlib import Path
from PySide6.QtWidgets import QFileDialog


class Dialogs:
    def __init__(self, parent):
        self.parent = parent

    def audio_files(self):
        names, _ = QFileDialog.getOpenFileNames(
            self.parent, 'Add Songs', '',
            'Audio files (*.wav *.aif *.aiff *.flac *.mp3 *.m4a);;All files (*)')
        return [Path(name) for name in names]

    def replacement_file(self, current):
        name, _ = QFileDialog.getOpenFileName(
            self.parent, 'Replace file', str(current.parent),
            'Audio files (*.wav *.aif *.aiff *.flac *.mp3 *.m4a);;All files (*)')
        return Path(name) if name else None

    def setlist_path(self):
        name, _ = QFileDialog.getOpenFileName(
            self.parent, 'Open Set', '', 'Setlists (*.yaml *.yml);;All files (*)')
        return Path(name) if name else None

    def bundle_path(self, directory, stem):
        name, _ = QFileDialog.getSaveFileName(
            self.parent, 'Export Show Bundle', str(Path(directory) / f'{stem}-bundle.zip'),
            'Zip archives (*.zip)')
        if not name:
            return None
        path = Path(name)
        return path if path.suffix else path.with_suffix('.zip')

    def import_bundle_path(self):
        name, _ = QFileDialog.getOpenFileName(
            self.parent, 'Import Show Bundle', '', 'Zip archives (*.zip);;All files (*)')
        return Path(name) if name else None

    def import_destination(self, default):
        # A save dialog doubles as a "name the new folder" picker; overwrite
        # confirmation is off because import never clobbers — an occupied
        # destination extracts into a fresh sibling instead.
        name, _ = QFileDialog.getSaveFileName(
            self.parent, 'Extract Bundle To Folder', str(default), '', '',
            QFileDialog.Option.DontConfirmOverwrite)
        return Path(name) if name else None

    def save_path(self, directory):
        name, _ = QFileDialog.getSaveFileName(
            self.parent, 'Save Set', str(Path(directory) / 'setlist.yaml'),
            'Setlists (*.yaml *.yml)')
        if not name:
            return None
        path = Path(name)
        return path if path.suffix else path.with_suffix('.yaml')
