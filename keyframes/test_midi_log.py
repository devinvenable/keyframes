"""MIDI take sidecar (task 234) — every incoming event is appended to a
JSONL log with epoch+monotonic timestamps, port name and a mapped flag on
note-ons; crash-safe via per-event flush; the .mid derivative round-trips
through mido at a fixed 120 BPM."""
import importlib.util
import json
import os
import queue
from pathlib import Path

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

import mido
import pytest

import main
from main import MidiEventLogger, process_midi_messages, resolve_midi_log_path

CONVERTER = Path(__file__).resolve().parents[1] / 'scripts' / 'midi_log_to_mid.py'
_spec = importlib.util.spec_from_file_location('midi_log_to_mid', CONVERTER)
midi_log_to_mid = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(midi_log_to_mid)


def read_log(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def run_messages(msgs, logger, note_to_media=None, channel=None,
                 start_note=36, end_note=51, source='TestPort'):
    """Feed messages through the real process_midi_messages path."""
    q = queue.Queue()
    for m in msgs:
        q.put(m)
    state = {'surface': None, 'video_player': None, 'note_active': None,
             'note_on_time': None, 'hold_until': None, 'zoom_scale': 1.0,
             'bend_zoom': 1.0, 'pan': 0.0, 'pan_cc_time': None,
             'pan_ease': None, 'inverted': False, 'surface_media': None,
             'last_note': None, 'active_scene': None}
    return process_midi_messages(
        q, start_note, end_note, note_to_media or {}, (64, 64), state,
        channel=channel, scenes_config={'enabled': False},
        midi_logger=logger, midi_source=source)


# --- activation ------------------------------------------------------------

def test_resolve_prefers_cli_then_env_then_off(tmp_path):
    assert resolve_midi_log_path('/cli.jsonl', {'KEYFRAMES_MIDI_LOG': '/env'}) == '/cli.jsonl'
    assert resolve_midi_log_path(None, {'KEYFRAMES_MIDI_LOG': '/env'}) == '/env'
    assert resolve_midi_log_path(None, {}) is None
    assert resolve_midi_log_path(None, {'KEYFRAMES_MIDI_LOG': ''}) is None


def test_no_logger_means_no_file(tmp_path):
    # midi_logger defaults to None: processing events must create nothing.
    run_messages([mido.Message('note_on', note=40, velocity=100)], None)
    assert list(tmp_path.iterdir()) == []


# --- event records ---------------------------------------------------------

def test_log_opens_with_reference_line(tmp_path):
    log = tmp_path / 'take.midi.jsonl'
    MidiEventLogger(str(log))
    (ref,) = read_log(log)
    assert ref['event'] == 'log_open'
    assert isinstance(ref['epoch'], float) and isinstance(ref['monotonic'], float)


def test_events_logged_with_required_fields(tmp_path):
    log = tmp_path / 'take.midi.jsonl'
    logger = MidiEventLogger(str(log))
    run_messages([
        mido.Message('note_on', note=40, velocity=100, channel=2),
        mido.Message('note_off', note=40, velocity=0, channel=2),
        mido.Message('control_change', control=1, value=64),
        mido.Message('program_change', program=7),
        mido.Message('pitchwheel', pitch=1024),
    ], logger, source='KeyStep 32')
    records = read_log(log)[1:]
    types = [r['type'] for r in records]
    assert types == ['note_on', 'note_off', 'control_change',
                     'program_change', 'pitchwheel']
    for r in records:
        assert r['port'] == 'KeyStep 32'
        assert isinstance(r['epoch'], float) and isinstance(r['monotonic'], float)
    on, off, cc, pc, pw = records
    assert (on['note'], on['velocity'], on['channel']) == (40, 100, 2)
    assert off['note'] == 40
    assert (cc['control'], cc['value']) == (1, 64)
    assert pc['program'] == 7
    assert pw['pitch'] == 1024


def test_other_types_logged_with_type(tmp_path):
    # "log type for anything else": clock and transport still get a line.
    log = tmp_path / 'take.midi.jsonl'
    logger = MidiEventLogger(str(log))
    run_messages([mido.Message('clock'), mido.Message('start')], logger)
    logger.close()
    assert [r['type'] for r in read_log(log)[1:]] == ['clock', 'start']


def test_events_logged_before_any_filtering(tmp_path):
    # Off-channel and out-of-range events never trigger media, but they DID
    # arrive — the log is ground truth of the stream, so they appear.
    log = tmp_path / 'take.midi.jsonl'
    logger = MidiEventLogger(str(log))
    run_messages([mido.Message('note_on', note=40, velocity=100, channel=5),
                  mido.Message('note_on', note=100, velocity=100, channel=0)],
                 logger, channel=0)
    assert len(read_log(log)[1:]) == 2


# --- mapped flag (post task-231 semantics) ----------------------------------

def test_mapped_flag_on_note_ons(tmp_path):
    log = tmp_path / 'take.midi.jsonl'
    logger = MidiEventLogger(str(log))
    media = {40: {'type': 'image', 'surface': None, 'name': 'a.png'}}
    run_messages([
        mido.Message('note_on', note=40, velocity=100),   # mapped
        mido.Message('note_on', note=41, velocity=100),   # in range, unmapped
        mido.Message('note_on', note=100, velocity=100),  # out of range
        mido.Message('note_on', note=40, velocity=0),     # note-off form
        mido.Message('note_off', note=40),
    ], logger, note_to_media=media)
    records = read_log(log)[1:]
    assert [r.get('mapped') for r in records] == [True, False, False, None, None]


def test_mapped_false_for_filtered_channel(tmp_path):
    log = tmp_path / 'take.midi.jsonl'
    logger = MidiEventLogger(str(log))
    media = {40: {'type': 'image', 'surface': None, 'name': 'a.png'}}
    run_messages([mido.Message('note_on', note=40, velocity=100, channel=5)],
                 logger, note_to_media=media, channel=0)
    (rec,) = read_log(log)[1:]
    assert rec['mapped'] is False


# --- crash safety ----------------------------------------------------------

def test_performance_events_flushed_per_line(tmp_path):
    # Without close(), a reader must already see every note event whole —
    # this is what keeps the jsonl intact when the process is killed.
    log = tmp_path / 'take.midi.jsonl'
    logger = MidiEventLogger(str(log))
    logger.log_message(mido.Message('note_on', note=40, velocity=9), 'p')
    records = read_log(log)
    assert records[-1]['type'] == 'note_on' and records[-1]['velocity'] == 9


def test_clock_ticks_may_ride_the_buffer_but_flush_with_next_event(tmp_path):
    log = tmp_path / 'take.midi.jsonl'
    logger = MidiEventLogger(str(log))
    for _ in range(3):
        logger.log_message(mido.Message('clock'), 'p')
    logger.log_message(mido.Message('note_on', note=40, velocity=9), 'p')
    types = [r['type'] for r in read_log(log)[1:]]
    assert types == ['clock', 'clock', 'clock', 'note_on']


def test_write_failure_never_raises(tmp_path, capsys):
    log = tmp_path / 'take.midi.jsonl'
    logger = MidiEventLogger(str(log))
    logger._file.close()  # simulate the disk/file going away mid-take
    logger.log_message(mido.Message('note_on', note=40, velocity=9), 'p')
    logger.log_message(mido.Message('note_on', note=41, velocity=9), 'p')
    assert capsys.readouterr().out.count('WARNING') == 1  # warn once, not spam
    logger.close()  # close after failure must not raise either


def test_drain_startup_midi_never_logs(tmp_path):
    # Stale pre-launch events are discarded before the logger even exists in
    # main(); drain_startup_midi takes no logger at all. Guard the contract:
    # a drained port's events must not be loggable through the drain path.
    import inspect
    params = inspect.signature(main.drain_startup_midi).parameters
    assert 'midi_logger' not in params and 'logger' not in params


# --- .mid derivative ---------------------------------------------------------

def sample_records(t0=1000.0):
    return [
        {'event': 'log_open', 'epoch': t0, 'monotonic': 1.0},
        {'epoch': t0 + 0.5, 'monotonic': 1.5, 'port': 'p', 'type': 'clock'},
        {'epoch': t0 + 1.0, 'monotonic': 2.0, 'port': 'p', 'type': 'note_on',
         'channel': 0, 'note': 60, 'velocity': 100, 'mapped': True},
        {'epoch': t0 + 1.5, 'monotonic': 2.5, 'port': 'p',
         'type': 'control_change', 'channel': 0, 'control': 1, 'value': 64},
        {'epoch': t0 + 2.0, 'monotonic': 3.0, 'port': 'p', 'type': 'note_off',
         'channel': 0, 'note': 60, 'velocity': 0},
    ]


def test_mid_roundtrips_through_mido(tmp_path):
    out = tmp_path / 'take.mid'
    mid = midi_log_to_mid.convert(sample_records())
    mid.save(str(out))
    loaded = mido.MidiFile(str(out))
    assert loaded.type == 0 and loaded.ticks_per_beat == 480
    msgs = list(loaded.tracks[0])
    assert msgs[0].type == 'set_tempo' and msgs[0].tempo == 500000
    # log_open and clock are skipped; absolute ticks from epoch at 960/s.
    body = [(m.type, m.time) for m in msgs[1:] if not m.is_meta]
    assert body == [('note_on', 960), ('control_change', 480),
                    ('note_off', 480)]
    on = [m for m in msgs if m.type == 'note_on'][0]
    assert on.note == 60 and on.velocity == 100


def test_mid_t0_override_sets_tick_zero_at_recording_start(tmp_path):
    # perform.sh passes --t0 rec_epoch: events shift onto the video timeline;
    # anything logged before recording start clamps to tick 0.
    mid = midi_log_to_mid.convert(sample_records(t0=1000.0), t0=1001.5)
    body = [(m.type, m.time) for m in mid.tracks[0] if not m.is_meta]
    assert body == [('note_on', 0), ('control_change', 0), ('note_off', 480)]


def test_mid_empty_or_clock_only_log_is_valid(tmp_path):
    mid = midi_log_to_mid.convert(
        [{'event': 'log_open', 'epoch': 1.0, 'monotonic': 0.0},
         {'epoch': 1.1, 'monotonic': 0.1, 'port': 'p', 'type': 'clock'}])
    out = tmp_path / 'empty.mid'
    mid.save(str(out))
    assert all(m.is_meta for m in mido.MidiFile(str(out)).tracks[0])


def test_mid_cli_survives_truncated_final_line(tmp_path, capsys):
    log = tmp_path / 'take.midi.jsonl'
    lines = [json.dumps(r) for r in sample_records()]
    log.write_text('\n'.join(lines) + '\n{"epoch": 123')  # kill mid-write
    out = tmp_path / 'take.mid'
    assert midi_log_to_mid.main([str(log), str(out), '--t0', '1000.0']) == 0
    loaded = mido.MidiFile(str(out))
    assert sum(1 for m in loaded.tracks[0] if m.type == 'note_on') == 1
