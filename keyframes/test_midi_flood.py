"""MIDI flood containment (task 266) — the per-frame drain must be bounded.

mido's iter_pending() yields for as long as messages keep arriving and its
rtmidi queue is unbounded, so a MIDI loop/flood (the I51 TBOX-wedge class:
KeyStep echoing USB-in clock to DIN OUT, returning via the thru box) could
trap the single render/event thread in the drain loop forever — frozen
visuals, dead input, process alive. These tests pin the containment: a
bounded pull per frame, flood-class traffic (clock) discarded first with
notes/cues/transport preserved, and the discard recorded as evidence
(stderr warning + 'midi_flood' sidecar event)."""
import os
import queue

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

import mido

from main import (MIDI_FLOOD_PROCESS_CAP, MIDI_FLOOD_READ_CAP,
                  note_midi_flood, process_midi_messages, read_midi_messages)


class FloodPort:
    """An input port that always has another message pending — the shape of
    a sustained MIDI loop. An unbounded drain would iterate this forever."""

    def __init__(self, msg_factory, limit=10 ** 6):
        self.msg_factory = msg_factory
        self.limit = limit  # backstop so a REGRESSION fails, not hangs
        self.served = 0

    def iter_pending(self):
        while self.served < self.limit:
            self.served += 1
            yield self.msg_factory(self.served)


def clock(_i=0):
    return mido.Message('clock')


def note_on(note):
    return mido.Message('note_on', note=note, velocity=100)


def test_flood_pull_is_bounded_per_call():
    port = FloodPort(clock)
    messages, dropped = read_midi_messages(port)
    # The source was left mid-flood: never drained past the read cap.
    assert port.served == MIDI_FLOOD_READ_CAP
    assert len(messages) <= MIDI_FLOOD_PROCESS_CAP
    assert sum(dropped.values()) == MIDI_FLOOD_READ_CAP - len(messages)


def test_flood_drops_clock_first_and_preserves_notes_and_cues():
    # A realistic loop frame: mostly clock, with a performer's notes and a
    # ShowSync cue interleaved. The clock is expendable; eating a note-off
    # or a cue mid-set would be its own stage bug.
    preserved = [note_on(60), mido.Message('note_off', note=60, velocity=0),
                 mido.Message('control_change', control=102, value=1),
                 mido.Message('program_change', program=2),
                 mido.Message('stop')]
    flood = [clock() for _ in range(MIDI_FLOOD_READ_CAP)]
    batch = flood[:100] + preserved + flood[100:]

    def factory(i):
        return batch[i - 1]

    messages, dropped = read_midi_messages(FloodPort(factory, limit=len(batch)))
    assert messages == preserved
    assert dropped == {'clock': MIDI_FLOOD_READ_CAP - len(preserved)}


def test_normal_traffic_is_untouched():
    msgs = [note_on(60), clock(), mido.Message('note_off', note=60, velocity=0)]
    port = FloodPort(lambda i: msgs[i - 1], limit=len(msgs))
    messages, dropped = read_midi_messages(port)
    assert messages == msgs
    assert dropped == {}


def test_queue_source_is_bounded_too():
    q = queue.Queue()
    for _ in range(MIDI_FLOOD_READ_CAP + 500):
        q.put(clock())
    messages, dropped = read_midi_messages(q)
    assert len(messages) <= MIDI_FLOOD_PROCESS_CAP
    assert q.qsize() == 500  # backlog stays queued, shed next frame


def test_process_midi_messages_survives_a_flood_and_still_triggers():
    # End to end: a flood frame with one real note-on buried in it still
    # triggers its media, and the flood is recorded on current_state.
    surface = object()
    media = {60: {'type': 'image', 'surface': surface, 'name': 'x.png'}}
    batch = [clock() for _ in range(MIDI_FLOOD_READ_CAP - 1)]
    batch.insert(1000, note_on(60))
    port = FloodPort(lambda i: batch[i - 1], limit=len(batch))
    state = {'surface': None, 'video_player': None, 'note_active': None,
             'note_on_time': None, 'hold_until': None, 'zoom_scale': 1.0,
             'last_note': None, 'active_scene': None}
    state = process_midi_messages(port, 36, 99, media, (64, 48), state,
                                  scenes_config={'enabled': False},
                                  midi_source='flood-port')
    assert state['note_active'] == 60
    assert state['surface'] is surface
    assert state['midi_flood']['dropped']['clock'] == MIDI_FLOOD_READ_CAP - 1


class FakeLogger:
    def __init__(self):
        self.events = []

    def log_event(self, event, **fields):
        self.events.append((event, fields))

    def log_message(self, msg, port, mapped=None):
        pass


def test_flood_evidence_event_and_rate_limited_warning(capsys):
    state = {}
    logger = FakeLogger()
    note_midi_flood(state, {'clock': 1000}, 'TBOX In 1', logger, now=100.0)
    note_midi_flood(state, {'clock': 500}, 'TBOX In 1', logger, now=101.0)
    # Every batch lands in the sidecar (the evidence trail)...
    assert logger.events == [('midi_flood', {'port': 'TBOX In 1',
                                             'dropped': {'clock': 1000}}),
                             ('midi_flood', {'port': 'TBOX In 1',
                                             'dropped': {'clock': 500}})]
    # ...but the console warning is rate-limited to one per window.
    out = capsys.readouterr().out
    assert out.count('MIDI flood') == 1
    assert state['midi_flood']['total'] == 1500
    # The next window warns again, with cumulative counts.
    note_midi_flood(state, {'clock': 1}, 'TBOX In 1', logger, now=106.0)
    assert 'discarded 1501' in capsys.readouterr().out


def test_no_flood_records_nothing():
    state = {}
    note_midi_flood(state, {}, 'TBOX In 1', FakeLogger(), now=100.0)
    assert 'midi_flood' not in state
