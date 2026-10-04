#!/usr/bin/env python3
"""Convert a Keyframes take MIDI sidecar (<take>.midi.jsonl) to a standard
MIDI file for DAW/Blender import.

Usage: midi_log_to_mid.py <sidecar.jsonl> <out.mid> [--t0 EPOCH]

The output is a type-0 SMF at a FIXED arbitrary tempo of 120 BPM with 480
ticks per beat, so one tick is exactly 1/960 s: event tick = round((epoch -
t0) * 960). Real timing lives in the wall-clock epochs; the tempo exists
only so DAWs place events at the right absolute seconds.

t0 defaults to the sidecar's own log_open epoch (self-contained import);
perform.sh passes --t0 <recording_start epoch> so tick 0 is the recorded
video's t=0 and the imported notes line up with the footage. Events before
t0 clamp to tick 0.

Only channel messages that can live in a MIDI file are converted (notes,
control/program change, pitchwheel, aftertouch). Realtime traffic — clock
ticks especially, which can dominate a sequenced take's sidecar — and the
log_open reference line are skipped. The sidecar stays the ground truth;
this file is a best-effort derivative.
"""
import argparse
import json
import sys

import mido

TICKS_PER_BEAT = 480
TEMPO = 500000  # 120 BPM, fixed — see module docstring
TICKS_PER_SECOND = 960  # TICKS_PER_BEAT * (1e6 / TEMPO)

# Channel messages representable in an SMF track. Everything else in the
# sidecar (clock/start/stop/sysex-fragments/log_open) is skipped.
FILE_TYPES = ('note_on', 'note_off', 'control_change', 'program_change',
              'pitchwheel', 'aftertouch', 'polytouch')

# Message parameters per type, straight from the mido message specs; any
# extra sidecar fields (port, monotonic, mapped) are dropped.
PARAMS = {t: set(mido.messages.specs.SPEC_BY_TYPE[t]['value_names'])
          for t in FILE_TYPES}


def convert(records, t0=None):
    """Build a type-0 mido.MidiFile from parsed sidecar records.
    t0 (epoch seconds) is the tick-0 reference; defaults to the first
    record's epoch (normally the log_open line)."""
    events = [r for r in records
              if r.get('type') in FILE_TYPES and 'epoch' in r]
    events.sort(key=lambda r: r['epoch'])
    if t0 is None:
        t0 = records[0]['epoch'] if records else 0.0

    mid = mido.MidiFile(type=0, ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=TEMPO, time=0))
    prev_tick = 0
    for rec in events:
        tick = max(0, round((rec['epoch'] - t0) * TICKS_PER_SECOND))
        params = {k: rec[k] for k in PARAMS[rec['type']] if k in rec}
        track.append(mido.Message(rec['type'], time=tick - prev_tick,
                                  **params))
        prev_tick = tick
    return mid


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('sidecar', help="input <take>.midi.jsonl")
    parser.add_argument('outfile', help="output .mid path")
    parser.add_argument('--t0', type=float, default=None, metavar='EPOCH',
                        help="epoch seconds mapped to tick 0 (default: the "
                             "sidecar's log_open epoch)")
    args = parser.parse_args(argv)

    records = []
    with open(args.sidecar, encoding='utf-8') as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # A kill mid-write can truncate the final line — never the
                # earlier ones (each event is flushed whole). Skip, keep going.
                print(f"WARNING: skipping unparseable line {n}", file=sys.stderr)

    mid = convert(records, t0=args.t0)
    mid.save(args.outfile)
    notes = sum(1 for m in mid.tracks[0]
                if m.type == 'note_on' and m.velocity > 0)
    print(f"Wrote {args.outfile}: {notes} note-on(s), "
          f"{len(mid.tracks[0])} event(s), 120 BPM fixed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
