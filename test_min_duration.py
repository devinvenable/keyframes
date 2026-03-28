"""Tests for minimum display duration and MIDI clock tracking."""
import queue
import time
from unittest.mock import patch

import mido
import pytest

from main import MidiClockTracker, NOTE_LENGTHS, process_midi_messages


class TestMidiClockTracker:
    def test_fallback_bpm(self):
        tracker = MidiClockTracker(fallback_bpm=140)
        assert tracker.bpm == 140

    def test_quarter_note_duration_at_120bpm(self):
        tracker = MidiClockTracker(fallback_bpm=120)
        assert tracker.quarter_note_duration() == pytest.approx(0.5)

    def test_note_duration(self):
        tracker = MidiClockTracker(fallback_bpm=120)
        # Quarter note at 120 BPM = 0.5s
        assert tracker.note_duration(1.0) == pytest.approx(0.5)
        # Eighth note = 0.25s
        assert tracker.note_duration(0.5) == pytest.approx(0.25)
        # Whole note = 2.0s
        assert tracker.note_duration(4.0) == pytest.approx(2.0)

    def test_clock_derives_bpm(self):
        tracker = MidiClockTracker(fallback_bpm=120)
        # Simulate 24 clocks at 120 BPM: quarter note = 0.5s, so clock interval = 0.5/24
        interval = 0.5 / 24
        base = time.monotonic()
        with patch('time.monotonic') as mock_time:
            for i in range(25):
                mock_time.return_value = base + i * interval
                tracker.tick()
        assert tracker.bpm == pytest.approx(120, abs=1)

    def test_clock_at_90bpm(self):
        tracker = MidiClockTracker(fallback_bpm=120)
        # 90 BPM: quarter = 60/90 = 0.667s, clock interval = 0.667/24
        interval = (60.0 / 90) / 24
        base = time.monotonic()
        with patch('time.monotonic') as mock_time:
            for i in range(25):
                mock_time.return_value = base + i * interval
                tracker.tick()
        assert tracker.bpm == pytest.approx(90, abs=1)


class TestNoteLengths:
    def test_known_lengths(self):
        assert NOTE_LENGTHS['quarter'] == 1.0
        assert NOTE_LENGTHS['1/4'] == 1.0
        assert NOTE_LENGTHS['eighth'] == 0.5
        assert NOTE_LENGTHS['whole'] == 4.0


class TestMinDurationProcessing:
    def _make_state(self):
        return {'surface': None, 'video_player': None, 'note_active': None,
                'note_on_time': None, 'hold_until': None}

    def test_note_on_off_without_min_duration(self):
        """Without min-note, note-off immediately clears display."""
        q = queue.Queue()
        state = self._make_state()
        note_to_media = {60: {'type': 'image', 'surface': 'fake_surface'}}

        q.put(mido.Message('note_on', note=60, velocity=100))
        state = process_midi_messages(q, 36, 99, note_to_media, (100, 100), state)
        assert state['surface'] == 'fake_surface'
        assert state['note_active'] == 60

        q.put(mido.Message('note_off', note=60, velocity=0))
        state = process_midi_messages(q, 36, 99, note_to_media, (100, 100), state)
        assert state['surface'] is None
        assert state['note_active'] is None

    def test_note_off_deferred_with_min_duration(self):
        """With min-note, short notes keep display until minimum elapses."""
        q = queue.Queue()
        state = self._make_state()
        tracker = MidiClockTracker(fallback_bpm=120)
        note_to_media = {60: {'type': 'image', 'surface': 'fake_surface'}}

        base = time.monotonic()

        # Note on
        with patch('time.monotonic', return_value=base):
            q.put(mido.Message('note_on', note=60, velocity=100))
            state = process_midi_messages(q, 36, 99, note_to_media, (100, 100), state,
                                          clock_tracker=tracker, min_note_beats=1.0)
        assert state['surface'] == 'fake_surface'

        # Note off after 0.1s (quarter note at 120bpm = 0.5s, so should hold)
        with patch('time.monotonic', return_value=base + 0.1):
            q.put(mido.Message('note_off', note=60, velocity=0))
            state = process_midi_messages(q, 36, 99, note_to_media, (100, 100), state,
                                          clock_tracker=tracker, min_note_beats=1.0)
        assert state['surface'] == 'fake_surface'  # Still showing
        assert state['hold_until'] is not None

        # After minimum duration elapses
        with patch('time.monotonic', return_value=base + 0.6):
            state = process_midi_messages(q, 36, 99, note_to_media, (100, 100), state,
                                          clock_tracker=tracker, min_note_beats=1.0)
        assert state['surface'] is None
        assert state['note_active'] is None

    def test_new_note_cancels_hold(self):
        """A new note-on should cancel any pending hold and display the new media."""
        q = queue.Queue()
        state = self._make_state()
        tracker = MidiClockTracker(fallback_bpm=120)
        note_to_media = {
            60: {'type': 'image', 'surface': 'surface_60'},
            62: {'type': 'image', 'surface': 'surface_62'},
        }

        base = time.monotonic()

        with patch('time.monotonic', return_value=base):
            q.put(mido.Message('note_on', note=60, velocity=100))
            state = process_midi_messages(q, 36, 99, note_to_media, (100, 100), state,
                                          clock_tracker=tracker, min_note_beats=1.0)

        # Quick note-off sets hold
        with patch('time.monotonic', return_value=base + 0.1):
            q.put(mido.Message('note_off', note=60, velocity=0))
            state = process_midi_messages(q, 36, 99, note_to_media, (100, 100), state,
                                          clock_tracker=tracker, min_note_beats=1.0)
        assert state['hold_until'] is not None

        # New note cancels hold
        with patch('time.monotonic', return_value=base + 0.2):
            q.put(mido.Message('note_on', note=62, velocity=100))
            state = process_midi_messages(q, 36, 99, note_to_media, (100, 100), state,
                                          clock_tracker=tracker, min_note_beats=1.0)
        assert state['surface'] == 'surface_62'
        assert state['hold_until'] is None
