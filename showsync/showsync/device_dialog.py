"""Native playback device preferences."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QPushButton, QVBoxLayout,
)
from . import devices as hardware


class DeviceDialog(QDialog):
    def __init__(self, devices, parent=None):
        super().__init__(parent)
        self.devices = devices
        self.setWindowTitle('Preferences — Playback devices')
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        self.message = QLabel()
        self.message.setTextFormat(Qt.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        form = QFormLayout()
        self.midi = QComboBox()
        self.audio = QComboBox()
        form.addRow('MIDI output', self.midi)
        form.addRow('Audio output', self.audio)
        layout.addLayout(form)
        self.refresh_button = QPushButton('Refresh devices')
        self.refresh_button.clicked.connect(self.refresh_devices)
        layout.addWidget(self.refresh_button)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.midi.currentIndexChanged.connect(self.validate)
        self.audio.currentIndexChanged.connect(self.validate)
        self.refresh_devices()

    def validate(self):
        valid = self.midi.currentIndex() >= 0
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(valid and self.audio.currentIndex() >= 0)

    def refresh_devices(self):
        initial = not self.midi.count()
        midi = self.midi.currentData() if self.midi.count() else self.devices.midi
        audio = self.audio.currentData() if self.audio.count() else self.devices.audio
        self.midi.clear()
        self.audio.clear()
        try:
            ports, outputs = hardware.midi_outputs(), hardware.audio_outputs()
        except Exception:
            self.message.setText('Could not list devices. Check the connections and try Refresh devices.')
            self.validate()
            return
        self.midi.addItem('Automatic (prefer hardware)', None)
        for name in ports:
            self.midi.addItem(name, name)
        self.audio.addItem('System default', None)
        for index, name in outputs:
            self.audio.addItem(name, name)
        self.devices.resolve(ports, outputs)
        selected_midi = self.devices.midi_name if initial and self.devices.midi_override else midi
        selected_audio = (next((name for index, name in outputs if index == self.devices.audio_index), audio)
                          if initial and self.devices.audio_override else audio)
        self.midi.setCurrentIndex(max(0, self.midi.findData(selected_midi)))
        self.audio.setCurrentIndex(max(0, self.audio.findData(selected_audio)))
        messages = [f'Automatic MIDI output: {self.devices.midi_name or "None (audio only)"}'] if midi is None else []
        if midi is not None and midi not in ports:
            messages.append(f'Previously used MIDI output “{midi}” is not connected. Using an available output.')
        if not ports:
            messages.append('No MIDI outputs are connected. Connect one, then refresh.')
        if audio is not None and self.devices.audio_index is None:
            messages.append(f'Previously used audio output “{audio}” is not connected. Choose an output or System default.')
        if self.devices.midi_override or self.devices.audio_override:
            messages.append('Command-line device choices apply to this run only.')
        self.message.setText('\n'.join(messages) or 'Device changes apply to the next playback.')
        self.validate()

    def accept(self):
        self.devices.choose(self.midi.currentData(), self.audio.currentData())
        super().accept()
