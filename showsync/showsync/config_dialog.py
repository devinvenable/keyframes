"""Editors for existing setlist configuration; no ports are opened here."""
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .setlist import (EGRESS_CLASSES, VIDEO_SUFFIXES, check_keyframes_bank,
                      parse_keyframes_cue, parse_keyframes_setup, parse_midi_outputs,
                      string)
from .visuals import KEYFRAMES_SCENES


def decimal(value, maximum=86400):
    spin = QDoubleSpinBox()
    spin.setRange(0, max(maximum, value))
    spin.setDecimals(6)
    spin.setValue(value)
    return spin


class OutputEditor(QWidget):
    """Ordered port selectors with per-port class filters (empty = fallback)."""
    def __init__(self, outputs=(), parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Port name / substring / index', 'Clock', 'Transport', 'Cues'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 260)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.add_button = QPushButton('Add output')
        self.add_button.clicked.connect(lambda: self.add_output(''))
        self.remove_button = QPushButton('Remove output')
        self.remove_button.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        layout.addLayout(buttons)
        for entry in outputs:
            self.add_output(entry)

    def add_output(self, entry):
        row = self.table.rowCount()
        self.table.insertRow(row)
        port = entry.port if hasattr(entry, 'send') else entry
        # Keep integer indices distinct from numeric string port names.
        item = QTableWidgetItem(str(port))
        item.setData(Qt.UserRole, port)
        self.table.setItem(row, 0, item)
        classes = entry.send if hasattr(entry, 'send') else EGRESS_CLASSES
        for column, name in enumerate(EGRESS_CLASSES, 1):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            check.setCheckState(Qt.Checked if name in classes else Qt.Unchecked)
            self.table.setItem(row, column, check)

    def outputs(self):
        raw = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            text = item.text().strip()
            original = item.data(Qt.UserRole)
            port = original if text == str(original) else int(text) if text.isdecimal() else text
            classes = [name for column, name in enumerate(EGRESS_CLASSES, 1)
                       if self.table.item(row, column).checkState() == Qt.Checked]
            raw.append(port if tuple(classes) == EGRESS_CLASSES else {'port': port, 'send': classes})
        return parse_midi_outputs({'midi_outputs': raw}) if raw else ()


class ConfigDialog(QDialog):
    def finish_layout(self, layout):
        self.error = QLabel()
        self.error.setTextFormat(Qt.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        try:
            self.apply()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        super().accept()


class SetSettingsDialog(ConfigDialog):
    def __init__(self, document, parent=None, *, overridden=False):
        super().__init__(parent)
        self.document = document
        self.setWindowTitle('Set settings')
        self.setMinimumWidth(630)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit(document.display_title)
        form.addRow('Set title', self.title)
        self.banks = QLineEdit(', '.join(document.keyframes[0]))
        self.banks.setToolTip('All Keyframes banks/ folder names, comma-separated and alphabetically sorted. Exclude default.')
        form.addRow('Keyframes banks', self.banks)
        self.channel = QSpinBox()
        self.channel.setRange(1, 16)
        self.channel.setValue(document.keyframes[1])
        form.addRow('Visual cue MIDI channel', self.channel)
        layout.addLayout(form)
        layout.addWidget(QLabel('MIDI outputs saved in this set (empty = Preferences single output).'))
        self.outputs = OutputEditor(document.midi_outputs)
        layout.addWidget(self.outputs)
        note = ('A run-only output override is active in Preferences; it takes precedence over this list.\n'
                if overridden else '')
        label = QLabel(note + 'ShowSync Cues is always created when supported and carries full egress.\n'
                       'Send MIDI Start/Stop in Preferences also gates outgoing transport.\n'
                       'Changes apply to the next playback. Save the complete bank list to keep program numbers aligned.')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.finish_layout(layout)

    def apply(self):
        title = string(self.title.text().strip(), 'title')
        setup = parse_keyframes_setup({'keyframes': {
            'banks': [part.strip() for part in self.banks.text().split(',') if part.strip()],
            'channel': self.channel.value()}})
        outputs = self.outputs.outputs()
        for row in self.document.rows:
            check_keyframes_bank(row.keyframes, setup[0])
        self.document.title, self.document.keyframes, self.document.midi_outputs = title, setup, outputs


class SongSettingsDialog(ConfigDialog):
    def __init__(self, row, banks, parent=None):
        super().__init__(parent)
        self.row, self.banks = row, banks
        self.setWindowTitle(f'Song settings — {row.name}')
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.gap = decimal(row.gap)
        form.addRow('Gap after song (seconds)', self.gap)
        video_line = QHBoxLayout()
        self.video = QLineEdit(str(row.video or ''))
        self.video.setPlaceholderText('No separate video (use embedded video when available)')
        video_line.addWidget(self.video)
        self.browse_video = QPushButton('Browse…')
        self.browse_video.clicked.connect(self.choose_video)
        video_line.addWidget(self.browse_video)
        form.addRow('Separate video', video_line)
        self.mute = QCheckBox('Mute embedded video audio')
        self.mute.setChecked(row.mute)
        self.mute.setEnabled(row.file.suffix.lower() in VIDEO_SUFFIXES)
        form.addRow(self.mute)
        self.midi_beats = decimal(row.midi_beats or 0)
        self.midi_beats.setSpecialValueText('Automatic (MIDI file length)')
        self.midi_beats.setEnabled(row.midi is not None)
        form.addRow('MIDI loop length (beats; 4 per bar)', self.midi_beats)
        cue = row.keyframes
        self.cue = QCheckBox('Send visual cue at song start')
        self.cue.setChecked(cue is not None)
        self.cue.setToolTip('Off: keep the previous song’s visual settings. On: reset to bank defaults, then apply these overrides.')
        form.addRow(self.cue)
        self.bank = QComboBox()
        self.bank.addItem('Keep current bank', None)
        for bank in ('default', *banks):
            self.bank.addItem(bank, bank)
        self.bank.setCurrentIndex(max(0, self.bank.findData(cue.bank if cue else None)))
        form.addRow('Visual bank', self.bank)
        self.scenes = QComboBox()
        for label, value in (('Bank default', None), ('Enabled', True), ('Disabled', False)):
            self.scenes.addItem(label, value)
        enabled = cue.enabled if cue else None
        self.scenes.setCurrentIndex(0 if enabled is None else 1 if enabled else 2)
        form.addRow('Scenes', self.scenes)
        self.probability_override = QCheckBox('Override scene probability')
        self.probability_override.setChecked(cue is not None and cue.probability is not None)
        form.addRow(self.probability_override)
        self.probability = decimal(cue.probability if cue and cue.probability is not None else 0, 1)
        form.addRow('Probability (0–1)', self.probability)
        self.allow_override = QCheckBox('Limit allowed scenes')
        self.allow_override.setChecked(cue is not None and cue.allow is not None)
        form.addRow(self.allow_override)
        self.allow = {}
        for name in KEYFRAMES_SCENES:
            check = QCheckBox(name)
            check.setChecked(cue is not None and name in (cue.allow or ()))
            self.allow[name] = check
            form.addRow(check)
        layout.addLayout(form)
        for check in (self.cue, self.probability_override, self.allow_override):
            check.toggled.connect(self.refresh_controls)
        self.refresh_controls()
        self.finish_layout(layout)

    def refresh_controls(self):
        enabled = self.cue.isChecked()
        for control in (self.bank, self.scenes, self.probability_override, self.allow_override):
            control.setEnabled(enabled)
        self.probability.setEnabled(enabled and self.probability_override.isChecked())
        for check in self.allow.values():
            check.setEnabled(enabled and self.allow_override.isChecked())

    def choose_video(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Separate video', str(self.row.file.parent),
                                            'Video (*.mp4 *.m4v *.mpg *.mpeg *.mov)')
        if path:
            self.video.setText(path)

    def apply(self):
        video = Path(self.video.text().strip()).expanduser().resolve() if self.video.text().strip() else None
        if video is not None and (video.suffix.lower() not in VIDEO_SUFFIXES or not video.is_file()):
            raise ValueError('Choose an existing MP4, M4V, MPG, MPEG, or MOV video file.')
        cue = None
        if self.cue.isChecked():
            raw = {}
            if self.bank.currentData() is not None:
                raw['bank'] = self.bank.currentData()
            scenes = {}
            if self.scenes.currentData() is not None:
                scenes['enabled'] = self.scenes.currentData()
            if self.probability_override.isChecked():
                scenes['probability'] = self.probability.value()
            if self.allow_override.isChecked():
                scenes['allow'] = [name for name, check in self.allow.items() if check.isChecked()]
            raw['scenes'] = scenes
            cue = parse_keyframes_cue({'keyframes': raw})
            check_keyframes_bank(cue, self.banks)
        candidate = replace(self.row, video=video, mute=self.mute.isChecked(), gap=self.gap.value(),
                            midi_beats=self.midi_beats.value() or None, keyframes=cue)
        for name in ('video', 'mute', 'gap', 'midi_beats', 'keyframes'):
            setattr(self.row, name, getattr(candidate, name))
        if self.row.file_error and self.row.file_error.startswith('video file not found:'):
            self.row.file_error = None
