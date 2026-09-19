#!/usr/bin/env python3
"""Real MIDI loopback + real audio, with raw timing evidence and explicit gates.

Auto creates a private virtual input on ALSA/CoreMIDI. On Windows provide an
existing loopMIDI/hardware loop with --input-port and --output-port. No simulated
transport is substituted if a device cannot be opened.
"""
import argparse
import json
from pathlib import Path
import platform
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import rtmidi
import soundfile as sf

from showsync.audio import AudioEngine
from showsync.clock import CLOCK, ClockEngine
from showsync.setlist import Setlist, Song
from showsync.tempomap import TempoEvent


def port_index(selection, ports):
    if str(selection).isdecimal() and int(selection) < len(ports):
        return int(selection)
    if selection in ports:
        return ports.index(selection)
    raise ValueError(f'Port {selection!r} not found; available: {list(enumerate(ports))}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=15)
    parser.add_argument('--audio-device', type=lambda s: int(s) if s.isdecimal() else s)
    parser.add_argument('--input-port')
    parser.add_argument('--output-port')
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    if args.seconds < 3:
        parser.error('--seconds must be at least 3')
    midi_in = midi_out = audio = clock = None
    received, sent = [], []
    result = {'platform': platform.platform(), 'python': sys.version.split()[0]}
    status = 1
    try:
        midi_in, midi_out = rtmidi.MidiIn(), rtmidi.MidiOut()
        midi_in.ignore_types(sysex=True, timing=False, active_sense=True)
        midi_in.set_callback(lambda event, data: received.append(time.monotonic()) if event[0] == [CLOCK] else None)
        if args.input_port is None and args.output_port is None:
            token = 'showsync-jitter-' + uuid.uuid4().hex[:8]
            midi_in.open_virtual_port(token)
            ports = midi_out.get_ports()
            matches = [i for i, name in enumerate(ports) if token in name]
            if len(matches) != 1:
                raise RuntimeError(f'Virtual input not visible: {ports}')
            midi_out.open_port(matches[0])
            result['midi_route'] = ports[matches[0]]
        elif args.input_port is not None and args.output_port is not None:
            midi_in.open_port(port_index(args.input_port, midi_in.get_ports()))
            midi_out.open_port(port_index(args.output_port, midi_out.get_ports()))
            result['midi_route'] = f'{args.output_port} -> {args.input_port}'
        else:
            raise ValueError('Both --input-port and --output-port are required for a physical loop')
        with tempfile.TemporaryDirectory(prefix='showsync-jitter-') as directory:
            path = Path(directory) / 'probe.wav'
            # Low-level original tone; real output stream stays active throughout.
            rate = 44100
            data = (.005 * np.sin(2 * np.pi * 440 * np.arange(round(args.seconds * rate)) / rate)).astype('float32')
            sf.write(path, data, rate)
            song = Song('jitter probe', path, 120, tempo=(TempoEvent(1, 160, args.seconds - 2),))
            audio = AudioEngine(Setlist('jitter probe', (song,)), device=args.audio_device)
            def send(byte):
                if byte == CLOCK:
                    p = audio.position()
                    stamp = time.monotonic()
                    ideal = stamp + audio.maps[p.song_index].T(clock._tick / 24) - p.song_time
                    sent.append((ideal, stamp, clock._tick))
                midi_out.send_message([byte])
            clock = ClockEngine(audio.maps, audio.position, send)
            clock.start()
            audio.start()
            deadline = time.monotonic() + args.seconds + 15
            while not audio.position().ended and time.monotonic() < deadline:
                if audio.error or clock.error:
                    raise RuntimeError(audio.error or clock.error)
                time.sleep(.02)
            if not audio.position().ended:
                raise RuntimeError('audio did not complete')
            clock.close()
            time.sleep(.1)  # Drain in-flight loopback messages, outside measurement.
            result.update(sent_ticks=len(sent), received_ticks=len(received),
                          audio_underruns=audio.underruns, dropped_ticks=clock.dropped_ticks,
                          priority_raised=clock.priority_raised,
                          audio_device=str(audio.stream.device), audio_latency=audio.stream.latency)
            if len(received) != len(sent) or len(sent) < 24:
                raise RuntimeError('loopback tick count mismatch or insufficient samples')
            expected = np.array([row[0] for row in sent])
            received_array = np.array(received)
            interval_error = (np.diff(received_array) - np.diff(expected)) * 1000
            phase_error = (received_array - expected) * 1000
            result.update(interval_sigma_ms=float(np.std(interval_error)),
                          interval_p99_abs_ms=float(np.percentile(np.abs(interval_error), 99)),
                          interval_worst_abs_ms=float(np.max(np.abs(interval_error))),
                          phase_mean_ms=float(np.mean(phase_error)),
                          phase_p99_abs_ms=float(np.percentile(np.abs(phase_error), 99)),
                          samples=[{'tick': row[2], 'ideal': row[0], 'sent': row[1], 'received': rx}
                                   for row, rx in zip(sent, received)])
            result['passed'] = (result['interval_sigma_ms'] < .5 and
                                result['interval_worst_abs_ms'] < 2 and
                                clock.dropped_ticks == 0 and audio.underruns == 0)
            status = 0 if result['passed'] else 2
    except Exception as exc:
        result.update(passed=False, unavailable_or_error=str(exc))
    finally:
        if clock:
            clock.close()
        if audio:
            audio.close()
        if midi_in:
            midi_in.close_port()
        if midi_out:
            midi_out.close_port()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'samples'}, indent=2))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
