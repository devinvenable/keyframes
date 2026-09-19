#!/usr/bin/env python3
"""Real MIDI loopback + real audio, with raw timing evidence and explicit gates.

Auto creates a private virtual input on ALSA/CoreMIDI. On Windows provide an
existing loopMIDI/hardware loop with --input-port and --output-port. No simulated
transport is substituted if a device cannot be opened.
"""
import argparse
import gc
import json
import multiprocessing
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


def receive_process(pipe, selection, token):
    """Separate interpreter so the sender's spin cannot hold the receiver's GIL."""
    midi = None
    received = []
    try:
        midi = rtmidi.MidiIn()
        midi.ignore_types(sysex=True, timing=False, active_sense=True)
        midi.set_callback(lambda event, data: received.append(time.monotonic()) if event[0] == [CLOCK] else None)
        if selection is None:
            midi.open_virtual_port(token)
        else:
            midi.open_port(port_index(selection, midi.get_ports()))
        pipe.send({'ready': True})
        pipe.recv()
        midi.cancel_callback()
        pipe.send(received)
    except Exception as exc:
        pipe.send({'error': str(exc)})
    finally:
        if midi:
            midi.close_port()
        pipe.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=15)
    parser.add_argument('--audio-device', type=lambda s: int(s) if s.isdecimal() else s)
    parser.add_argument('--input-port')
    parser.add_argument('--output-port')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--freeze-gc', action='store_true', help='Freeze startup objects before playback (optional timing hardening)')
    args = parser.parse_args()
    if args.seconds < 3:
        parser.error('--seconds must be at least 3')
    midi_out = audio = clock = receiver = pipe = None
    received, sent = [], []
    result = {'platform': platform.platform(), 'python': sys.version.split()[0]}
    status = 1
    try:
        if (args.input_port is None) != (args.output_port is None):
            raise ValueError('Both --input-port and --output-port are required for a physical loop')
        token = 'showsync-jitter-' + uuid.uuid4().hex[:8]
        context = multiprocessing.get_context('spawn')
        pipe, child = context.Pipe()
        receiver = context.Process(target=receive_process, args=(child, args.input_port, token), daemon=True)
        receiver.start()
        child.close()
        if not pipe.poll(20):
            raise RuntimeError('MIDI receiver startup timed out')
        ready = pipe.recv()
        if not ready.get('ready'):
            raise RuntimeError(ready['error'])
        midi_out = rtmidi.MidiOut()
        result['receiver'] = 'separate process (independent GIL)'
        if args.input_port is None and args.output_port is None:
            ports = midi_out.get_ports()
            matches = [i for i, name in enumerate(ports) if token in name]
            if len(matches) != 1:
                raise RuntimeError(f'Virtual input not visible: {ports}')
            midi_out.open_port(matches[0])
            result['midi_route'] = ports[matches[0]]
        elif args.input_port is not None and args.output_port is not None:
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
            if args.freeze_gc:
                import sounddevice  # Finish native backend imports before freezing.
                audio.prepare()
                gc.freeze()
                result['gc_frozen'] = True
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
            pipe.send('stop')
            if not pipe.poll(5):
                raise RuntimeError('MIDI receiver drain timed out')
            received = pipe.recv()
            if isinstance(received, dict):
                raise RuntimeError(received['error'])
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
        if midi_out:
            midi_out.close_port()
        if receiver:
            receiver.join(timeout=.2)
            if receiver.is_alive():
                receiver.terminate()
                receiver.join(timeout=2)
        if pipe:
            pipe.close()
        if args.freeze_gc:
            gc.unfreeze()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'samples'}, indent=2))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
