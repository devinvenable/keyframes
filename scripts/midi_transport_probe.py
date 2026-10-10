#!/usr/bin/env python3
"""Passively capture transport at MIDI input callbacks, without a renderer.

No output ports are opened. Clock traffic is summarized per port, flushing
each second or before another message; CC and SysEx/MMC are recorded in full.
Use a fresh output path per take: existing evidence is never overwritten.
"""
import argparse
from contextlib import ExitStack
import json
import threading
import time


class Recorder:
    def __init__(self, stream, *, now=time.monotonic, epoch=time.time):
        self.stream, self.now, self.epoch = stream, now, epoch
        self.lock = threading.Lock()
        self.clocks = {}

    def _write(self, **fields):
        self.stream.write(json.dumps(dict(epoch=self.epoch(),
                                          monotonic=self.now(), **fields)) + '\n')
        self.stream.flush()

    def event(self, event, **fields):
        with self.lock:
            self._write(event=event, **fields)

    def receive(self, port, message):
        with self.lock:
            if message.type == 'clock':
                now = self.now()
                stats = self.clocks.setdefault(port, dict(count=0, first=now, last=now))
                stats['count'] += 1
                stats['last'] = now
                if now - stats['first'] >= 1:
                    self._flush_clock(port)
            elif message.type != 'active_sensing':
                # Flush preceding clocks before a Stop so their timestamps
                # cannot be mistaken for clocks received after the press.
                self._flush_clock(port)
                fields = message.dict()
                fields.pop('time', None)
                self._write(port=port, **fields)

    def _flush_clock(self, port):
        stats = self.clocks.pop(port, None)
        if stats:
            self._write(event='clock_summary', port=port, **stats)

    def close(self):
        with self.lock:
            for port in list(self.clocks):
                self._flush_clock(port)
            self._write(event='probe_close')


def select_ports(ports, selectors):
    selected = []
    for selector in selectors:
        matches = ([selector] if selector in ports else
                   [p for p in ports if selector.lower() in p.lower()])
        if len(matches) != 1:
            raise ValueError(f'{selector!r} must match exactly one input; '
                             f'matches={matches!r}, available={ports!r}')
        if matches[0] not in selected:
            selected.append(matches[0])
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--list', action='store_true', help='list inputs and exit')
    parser.add_argument('--port', action='append', help='exact name or unique substring; repeatable')
    parser.add_argument('--seconds', type=float, default=90)
    parser.add_argument('--output', help='new JSONL file (required unless --list)')
    args = parser.parse_args(argv)
    if not args.list and (not args.output or args.seconds <= 0):
        parser.error('--output and a positive --seconds are required')
    import mido
    ports = mido.get_input_names()
    if args.list:
        print('\n'.join(ports))
        return 0
    try:
        selected = select_ports(ports, args.port or ['KeyStep', 'Midi Out 1'])
    except ValueError as exc:
        parser.error(str(exc))
    with open(args.output, 'x', encoding='utf-8') as stream:
        recorder = Recorder(stream)
        recorder.event('probe_open', ports=selected, seconds=args.seconds)
        try:
            with ExitStack() as stack:
                for port in selected:
                    stack.enter_context(mido.open_input(
                        port, callback=lambda msg, name=port: recorder.receive(name, msg)))
                recorder.event('probe_ready')
                print(f'Listening for {args.seconds:g}s: {selected}. Output: {args.output}', flush=True)
                try:
                    threading.Event().wait(args.seconds)
                except KeyboardInterrupt:
                    pass
        finally:
            recorder.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
