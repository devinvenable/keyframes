"""CLI wiring, shared by the console script and source entry point."""
import argparse
import gc
import logging

from .audio import AudioEngine
from .clock import ClockEngine, open_midi_port
from .gui import run
from .setlist import load_setlist, save_song_order


def main(argv=None):
    parser = argparse.ArgumentParser(description='Audio-master backing tracks and MIDI clock')
    parser.add_argument('setlist', nargs='?')
    parser.add_argument('--audio-device', type=lambda s: int(s) if s.isdecimal() else s)
    parser.add_argument('--midi-port', help='MIDI output index or exact name')
    parser.add_argument('--list-devices', action='store_true')
    parser.add_argument('--freeze-gc', action='store_true', help='Freeze startup objects to reduce GC timing pauses')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    if args.list_devices:
        import sounddevice as sd
        import rtmidi
        print(sd.query_devices())
        output = rtmidi.MidiOut()
        print('MIDI outputs:', list(enumerate(output.get_ports())))
        return 0
    if not args.setlist:
        parser.error('a setlist path is required')
    audio = clock = midi = None
    try:
        audio = AudioEngine(load_setlist(args.setlist), device=args.audio_device)
        midi = open_midi_port(args.midi_port)
        if args.freeze_gc:
            import sounddevice
            audio.prepare()
            gc.freeze()
        clock = ClockEngine(audio.maps, audio.position, lambda byte: midi.send_message([byte]))
        clock.start()
        audio.start()
        run(audio, clock, persist=lambda order: save_song_order(args.setlist, order))
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logging.error('%s', exc)
        return 1
    finally:
        try:
            if clock:
                clock.close()
        finally:
            try:
                if audio:
                    audio.close()
            finally:
                if midi:
                    midi.close_port()
                if args.freeze_gc:
                    gc.unfreeze()
