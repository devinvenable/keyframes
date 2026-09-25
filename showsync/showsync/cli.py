"""CLI wiring, shared by the console script and source entry point."""
import argparse
import gc
import logging
import math

from .appstate import last_setlist, remember_setlist, clock_offset_ms, remember_clock_offset
from .audio import AudioEngine
from .bundle import BundleError, export_bundle, import_bundle
from .clock import ClockEngine, open_midi_port
from .document import Document
from .devices import Devices
from .gui import main_loop
from .midifile import MidiEventsView, load_setlist_events
from .setlist import SetlistError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Audio-master backing tracks and MIDI clock')
    parser.add_argument('setlist', nargs='?',
                        help='open setlist YAML in the editor; omitted = reopen the last-used set (or start a new one)')
    parser.add_argument('--audio-device', type=lambda s: int(s) if s.isdecimal() else s)
    parser.add_argument('--midi-port', help='MIDI output index or exact name')
    parser.add_argument('--list-devices', action='store_true')
    parser.add_argument('--freeze-gc', action='store_true', help='Freeze startup objects to reduce GC timing pauses')
    parser.add_argument('--editor-screen', metavar='NAME|INDEX',
                        help='open the editor window on this screen (xrandr-style name '
                             'like HDMI-0, or index); the video projector keeps its own '
                             'remembered screen')
    parser.add_argument('--midi-transport', action='store_true',
                        help='listen for MIDI realtime Start/Continue/Stop on the MIDI '
                             'input and drive the set like the GUI controls')
    parser.add_argument('--clock-offset', type=float, metavar='MS',
                        help='MIDI clock offset (-250..250 ms); positive = earlier ticks; this run only')
    parser.add_argument('--export-bundle', metavar='ZIP',
                        help='write a portable show bundle (setlist + audio) to ZIP and exit')
    parser.add_argument('--import-bundle', nargs='+', metavar=('ZIP', 'DEST'),
                        help='unpack a show bundle ZIP into DEST '
                             '(default: a folder named after the zip, beside it) and exit')
    args = parser.parse_args(argv)
    if args.import_bundle:
        if len(args.import_bundle) > 2:
            parser.error('--import-bundle takes ZIP and at most one DEST')
        if args.setlist or args.export_bundle:
            parser.error('--import-bundle cannot be combined with a setlist or --export-bundle')
        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
        try:
            setlist = import_bundle(*args.import_bundle)
        except BundleError as exc:
            logging.error('%s', exc)
            return 1
        print(f'Extracted to {setlist.parent} — open {setlist}')
        return 0
    if args.export_bundle:
        if not args.setlist:
            parser.error('--export-bundle needs a setlist argument')
        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
        try:
            manifest = export_bundle(args.setlist, args.export_bundle)
        except BundleError as exc:
            logging.error('%s', exc)
            return 1
        print(f'Wrote {args.export_bundle} ({len(manifest)} songs)')
        return 0
    if args.clock_offset is not None and (not math.isfinite(args.clock_offset) or
                                          not -250 <= args.clock_offset <= 250):
        parser.error('--clock-offset must be between -250 and 250 ms')
    offset = clock_offset_ms() if args.clock_offset is None else args.clock_offset

    def change_offset(value):
        nonlocal offset
        offset = value
        if args.clock_offset is None:
            remember_clock_offset(value)

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    if args.list_devices:
        import sounddevice as sd
        import rtmidi
        print(sd.query_devices())
        output = rtmidi.MidiOut()
        print('MIDI outputs:', list(enumerate(output.get_ports())))
        return 0

    devices = Devices(args.midi_port, args.audio_device)
    frozen = False

    def start_engines(setlist):
        nonlocal frozen
        audio = midi = clock = None
        try:
            audio = AudioEngine(setlist, device=devices.audio_index)
            try:
                midi = open_midi_port(devices.midi_name) if devices.midi_name is not None else None
            except Exception:
                devices.midi_name = None
                devices.notice = 'MIDI output disconnected — playing audio only.'
            if args.freeze_gc:
                audio.prepare()
                gc.freeze()
                frozen = True
            events = MidiEventsView(audio, load_setlist_events(setlist)) if setlist is not None else None
            clock = ClockEngine(audio.maps, audio.position,
                                lambda message: midi.send_message([message] if isinstance(message, int) else message) if midi is not None else None,
                                clock_offset_ms=offset, send_transport=devices.send_transport,
                                events=events)
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
        except SetlistError as exc:
            action = 'OPEN SETLIST' if args.setlist else 'REOPEN LAST SETLIST'
            notice = f'COULD NOT {action}: {exc}'
    problem = document.first_problem()
    if args.setlist and not notice and problem:
        row, message = problem
        notice = f"NOT PLAYABLE YET — {f'{row.name}: ' if row else ''}{message}"
    try:
        return main_loop(document, start_engines=start_engines,
                         remember=remember_setlist,
                         notice=notice, clock_offset_ms=offset,
                         offset_changed=change_offset, devices=devices,
                         editor_screen=args.editor_screen,
                         midi_transport=args.midi_transport)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logging.error('%s', exc)
        return 1
