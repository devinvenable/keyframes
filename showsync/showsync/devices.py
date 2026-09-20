"""Run-local device choices, resolved afresh before opening a show."""
from . import appstate


def midi_outputs():
    import rtmidi
    output = rtmidi.MidiOut()
    try:
        return output.get_ports()
    finally:
        output.delete()


def audio_outputs():
    import sounddevice as sd
    hosts = sd.query_hostapis()
    return [(index, f"{device['name']} ({hosts[device['hostapi']]['name']})")
            for index, device in enumerate(sd.query_devices())
            if device['max_output_channels'] > 0]


class Devices:
    def __init__(self, midi=None, audio=None):
        saved = appstate.device_choices()
        self.midi_override = midi is not None
        self.audio_override = audio is not None
        self.midi = midi if self.midi_override else saved['midi']
        self.audio = audio if self.audio_override else saved['audio']
        self.midi_name = None
        self.audio_index = None

    def resolve(self, ports, outputs):
        self.notice = ''
        midi = self.midi
        if self.midi_override and str(midi).isdecimal():
            index = int(midi)
            midi = ports[index] if index < len(ports) else midi
        if midi not in ports:
            if midi is not None:
                self.notice = f'Previously used MIDI output “{midi}” is not connected. Using an available output.'
            hardware = [name for name in ports
                        if not any(word in name.lower() for word in ('through', 'virtual', 'loopback'))]
            midi = next(iter(hardware or ports), None)
        self.midi_name = midi
        if midi is None:
            self.notice = 'No MIDI output connected — playing audio only.'
        audio = self.audio
        matches = [index for index, name in outputs if name == audio]
        if self.audio_override:
            # Preserve sounddevice's CLI index/name support, but only output devices.
            matches = [index for index, name in outputs
                       if index == audio or (isinstance(audio, str) and audio.lower() in name.lower())]
        self.audio_index = matches[0] if len(matches) == 1 else None
        if audio is not None and self.audio_index is None:
            self.notice += f' Audio output “{audio}” is unavailable; using system default.'

    def choose(self, midi, audio):
        self.midi, self.audio = midi, audio
        values = {}
        if not self.midi_override:
            values['midi'] = midi
        if not self.audio_override:
            values['audio'] = audio
        appstate.remember_devices(**values)
