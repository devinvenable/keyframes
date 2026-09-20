"""CLI wiring, shared by the console script and source entry point."""
import argparse
import gc
import logging

from .appstate import last_setlist, remember_setlist
from .audio import AudioEngine
from .clock import ClockEngine, open_midi_port
from .document import Document
from .gui import main_loop
from .setlist import SetlistError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Audio-master backing tracks and MIDI clock')
    parser.add_argument('setlist', nargs='?',
                        help='setlist YAML; omitted = reopen the last-used set (or start a new one)')
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

    frozen = False

    def start_engines(setlist):
        nonlocal frozen
        audio = midi = clock = None
        try:
            audio = AudioEngine(setlist, device=args.audio_device)
            midi = open_midi_port(args.midi_port)
            if args.freeze_gc:
                audio.prepare()
                gc.freeze()
                frozen = True
            clock = ClockEngine(audio.maps, audio.position, lambda byte: midi.send_message([byte]))
            clock.start()
            audio.start()
        except Exception:
            close(audio, clock, midi)
            raise
        return audio, clock, lambda: close(audio, clock, midi)

    def close(audio, clock, midi):
        nonlocal frozen
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
                if frozen:
                    gc.unfreeze()
                    frozen = False

    notice = ''
    path = args.setlist or last_setlist()
    document = Document()
    if path:
        try:
            document = Document.load(path)
            remember_setlist(document.path)
        except SetlistError as exc:
            if args.setlist:
                logging.error('%s', exc)
                return 1
            notice = f'COULD NOT REOPEN LAST SETLIST: {exc}'
    # An explicit, fully playable setlist starts the show immediately, as
    # before; anything else opens quietly in the editor.
    autoplay = bool(args.setlist) and not document.first_problem()
    if args.setlist and not autoplay:
        row, message = document.first_problem()
        notice = f"NOT PLAYABLE YET — {f'{row.name}: ' if row else ''}{message}"
    try:
        return main_loop(document, start_engines=start_engines,
                         remember=remember_setlist, autoplay=autoplay,
                         notice=notice)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logging.error('%s', exc)
        return 1
