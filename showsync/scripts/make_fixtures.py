"""Regenerate the checked-in, original 1-second 440 Hz audio fixtures."""
from pathlib import Path
from fractions import Fraction
import av
import numpy as np
import soundfile as sf

root = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures'
for ext, rate, channels in [('wav', 44100, 1), ('aiff', 48000, 2), ('flac', 32000, 2), ('mp3', 44100, 2)]:
    mono = (.1 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)).astype('float32')
    data = mono if channels == 1 else np.column_stack((mono, mono))
    sf.write(root / f'tone.{ext}', data, rate)
rate = 44100
with av.open(str(root / 'tone.m4a'), 'w') as output:
    stream = output.add_stream('aac', rate=rate)
    stream.layout = 'stereo'
    data = np.tile((.1 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)).astype('float32'), (2, 1))
    frame = av.AudioFrame.from_ndarray(data, format='fltp', layout='stereo')
    frame.sample_rate = rate
    frame.pts = 0
    frame.time_base = Fraction(1, rate)
    for packet in stream.encode(frame):
        output.mux(packet)
    for packet in stream.encode(None):
        output.mux(packet)
