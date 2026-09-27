"""Optional MIDI references survive editor actions and comment-preserving saves."""
from pathlib import PureWindowsPath

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from conftest import TONE
from showsync.dialogs import Dialogs
from showsync.document import Document, Row
from showsync.gui import FIELDS
from showsync.tempomap import TempoEvent


@pytest.mark.parametrize('outside', [False, True])
def test_midi_round_trip_add_replace_clear(tmp_path, outside):
    root = tmp_path / 'media'
    root.mkdir()
    target = tmp_path / 'set.yaml'
    original = f'''# Show notes
title: "Keep quotes"
audio_root: media
songs:
  - name: 'Song'  # keep name
    file: {TONE}  # keep audio
    bpm: 120.0  # keep bpm
    gap: 2  # keep gap
    tempo:
      - at: '0:00.5'  # keep map
        bpm: 140
        ramp: 0.25
'''
    target.write_text(original)
    doc = Document.load(target)
    midi = (tmp_path if outside else root) / 'parts' / 'song.MIDI'
    doc.set_midi(doc.rows[0], midi)
    doc.save()
    saved = target.read_text()
    expected = str(midi) if outside else 'parts/song.MIDI'
    assert f'midi: {expected}' in saved
    assert ''.join(line for line in saved.splitlines(keepends=True)
                   if 'midi:' not in line) == original
    reopened = Document.load(target)
    assert reopened.rows[0].midi == midi
    assert reopened.setlist().songs[0].midi == midi
    reopened.save()
    assert target.read_text() == saved
    replacement = root / 'new.mid'
    reopened.set_midi(reopened.rows[0], replacement)
    reopened.save()
    assert Document.load(target).rows[0].midi == replacement
    reopened.set_midi(reopened.rows[0], None)
    reopened.save()
    assert target.read_text() == original
    assert Document.load(target).rows[0].midi is None


def test_existing_quoted_midi_reference_is_byte_stable(tmp_path):
    target = tmp_path / 'set.yaml'
    original = f'''title: Show
songs:
  - name: Song
    file: {TONE}
    bpm: 120
    midi: "./parts/old.mid"  # keep MIDI comment
'''
    target.write_text(original)
    doc = Document.load(target)
    doc.save()
    assert target.read_text() == original
    doc.set_midi(doc.rows[0], tmp_path / 'parts' / 'new.mid')
    doc.save()
    assert target.read_text() == original.replace('"./parts/old.mid"', '"parts/new.mid"  ')


def test_midi_picker_summary_selection_validation_and_clear(qtbot, window_factory, tmp_path, monkeypatch):
    rows = [Row('First', TONE, 120, duration=1),
            Row('Custom', TONE, 120, tempo=(TempoEvent(.5, 140),), duration=1)]
    doc = Document(tmp_path / 'set.yaml', rows=rows)
    w = window_factory(doc)
    w.dialogs = Dialogs(w)
    w.table.clearSelection()
    w.table.setCurrentIndex(w.model.index(-1, -1))
    w.show_row_problem()
    assert not w.midi_browse_button.isEnabled()
    w.table.selectRow(1)
    midi = tmp_path / 'parts' / 'keys.mid'
    calls = []
    chosen = [str(midi)]
    def picker(*args):
        calls.append(args)
        return chosen[0], ''
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', picker)
    qtbot.mouseClick(w.midi_browse_button, Qt.LeftButton)
    assert calls[0][0] is w
    assert calls[0][3] == 'MIDI files (*.mid *.midi)'
    assert rows[0].midi is None and rows[1].midi == midi
    assert Document.load(doc.path).rows[1].midi == midi
    column = w.model.index(1, FIELDS.index('midi'))
    assert column.data() == 'keys.mid'
    assert column.data(Qt.ToolTipRole) == str(midi)
    assert not w.model.flags(column) & Qt.ItemIsEditable
    assert w.midi_entry.text() == 'keys.mid'
    assert w.midi_entry.toolTip() == str(midi)
    assert rows[1].problem() is None
    before = doc.path.read_text()
    chosen[0] = ''
    qtbot.mouseClick(w.midi_browse_button, Qt.LeftButton)
    assert doc.path.read_text() == before and rows[1].midi == midi
    chosen[0] = str(tmp_path / 'invalid.wav')
    qtbot.mouseClick(w.midi_browse_button, Qt.LeftButton)
    assert '.mid or .midi' in w.statusBar().currentMessage()
    assert rows[1].midi == midi and doc.path.read_text() == before
    w.table.selectRow(0)
    assert w.midi_entry.text() == '' and not w.midi_clear_button.isEnabled()
    w.table.selectRow(1)
    qtbot.mouseClick(w.midi_clear_button, Qt.LeftButton)
    assert rows[1].midi is None and 'midi:' not in doc.path.read_text()
    assert column.data() == '' and w.midi_entry.text() == ''
    assert not w.midi_clear_button.isEnabled()
    w.play()
    assert w.audio is not None
    assert not w.set_midi_path(midi)
    assert rows[1].midi is None


def test_windows_portable_paths():
    root = PureWindowsPath('C:/Show/media')
    assert Document._portable(PureWindowsPath('C:/Show/media/parts/song.mid'), root) == 'parts/song.mid'
    assert Document._portable(PureWindowsPath('D:/parts/song.mid'), root) == str(PureWindowsPath('D:/parts/song.mid'))


@pytest.mark.parametrize('length', ['bars: 3', 'beats: 7.5'])
def test_extended_midi_editor_roundtrip_and_controls(length, tmp_path, window_factory, qtbot, monkeypatch):
    monkeypatch.setattr('showsync.devices.midi_outputs', lambda: ['Synth A', 'Synth B'])
    path = tmp_path / 'show.yaml'
    original = f'''title: Show
songs:
  - name: Song
    file: {TONE}
    bpm: 120
    midi: {{file: "./old.mid", loop: true, {length}, port: 'Disconnected'}} # keep MIDI
'''
    path.write_text(original)
    doc = Document.load(path)
    doc.save()
    assert path.read_text() == original
    w = window_factory(doc)
    w.table.selectRow(0)
    assert w.midi_loop.isChecked()
    assert w.midi_port.currentData() == 'Disconnected'
    assert w.midi_port.findText('Synth B') >= 0
    qtbot.mouseClick(w.midi_loop, Qt.LeftButton)
    w.midi_port.setCurrentIndex(w.midi_port.findData('Synth B'))
    assert w.set_midi_path(tmp_path / 'replacement.mid')
    reopened = Document.load(path)
    row = reopened.rows[0]
    song = reopened.setlist().songs[0]
    assert row.midi == tmp_path / 'replacement.mid'
    assert (song.midi_loop, song.midi_port) == (False, 'Synth B')
    assert song.midi_beats == (12 if length.startswith('bars') else 7.5)
    assert '# keep MIDI' in path.read_text() and length in path.read_text()
    w.midi_port.setCurrentIndex(0)
    assert Document.load(path).rows[0].midi_port is None
    qtbot.mouseClick(w.midi_clear_button, Qt.LeftButton)
    assert 'midi:' not in path.read_text()
    assert not w.midi_loop.isEnabled() and not w.midi_port.isEnabled()


def test_plain_midi_promotes_to_mapping_on_option_edit(tmp_path, window_factory, qtbot, monkeypatch):
    monkeypatch.setattr('showsync.devices.midi_outputs', lambda: ['Synth'])
    doc = Document(tmp_path / 'show.yaml', rows=[Row('Song', TONE, 120, midi=tmp_path / 'part.mid')])
    w = window_factory(doc)
    w.table.selectRow(0)
    qtbot.mouseClick(w.midi_loop, Qt.LeftButton)
    w.midi_port.setCurrentIndex(1)
    song = Document.load(doc.path).setlist().songs[0]
    assert song.midi_loop and song.midi_port == 'Synth'
    w.play()
    assert not w.midi_loop.isEnabled() and not w.midi_port.isEnabled()
