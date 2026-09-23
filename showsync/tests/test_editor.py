from pathlib import Path
import threading

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from showsync.bpmdetect import BeatGrid
from showsync.document import Document, Row
from showsync.gui import bpm_cell, bpm_label
from showsync.setlist import Song, load_setlist
from showsync.tempomap import TempoEvent
from conftest import Dialogs, FIXTURES, TONE


def edit(qtbot, window, row, column, value):
    index = window.model.index(row, column)
    window.table.setCurrentIndex(index)
    window.table.edit(index)
    QApplication.processEvents()
    editor = window.table.findChild(QLineEdit)
    assert editor is not None
    editor.selectAll()
    qtbot.keyClicks(editor, value)
    if not value:
        qtbot.keyClick(editor, Qt.Key_Backspace)
    qtbot.keyClick(editor, Qt.Key_Return)
    QApplication.processEvents()


@pytest.mark.parametrize('legacy', ['true', 'false'])
def test_legacy_restart_is_inert_and_roundtrips_without_checkbox(window_factory, tmp_path, legacy):
    target = tmp_path / 'legacy.yaml'
    text = (f'title: "Keep quotes"\nsongs:\n  - name: Pattern\n    file: {TONE}\n'
            f'    bpm: 120\n    restart: {legacy}  # old choice\n'
            '    tempo:\n      - at: 0.1  # custom jump\n        bpm: 140\n')
    target.write_text(text)
    doc = Document.load(target)
    doc.save()
    assert target.read_text() == text
    w = window_factory(doc)
    assert w.model.columnCount() == 7
    assert not hasattr(doc.rows[0], 'restart')
    assert not hasattr(doc.setlist().songs[0], 'restart')
    assert not hasattr(load_setlist(target).songs[0], 'restart')
    assert all(not w.model.flags(w.model.index(0, c)) & Qt.ItemIsUserCheckable
               for c in range(w.model.columnCount()))


def drop(window, paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p.resolve())) for p in paths])
    enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(window, enter)
    assert enter.isAccepted()
    event = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(window, event)
    assert event.isAccepted()


def test_build_a_set_from_nothing_and_start_it(qtbot, window_factory, tmp_path):
    target = tmp_path / 'my-set.yaml'
    dialogs = Dialogs(save=target)
    remembered = []
    w = window_factory(dialogs=dialogs, remember=remembered.append)
    assert w.empty_hint.isVisible()
    drop(w, [TONE, FIXTURES / 'tone.flac', FIXTURES / 'fall2026.yaml'])
    assert 'Skipped fall2026.yaml' in w.statusBar().currentMessage()
    qtbot.mouseClick(w.play_button, Qt.LeftButton)
    assert w.audio is None
    assert 'tone: BPM not set' in w.statusBar().currentMessage()
    edit(qtbot, w, 0, 2, '120')
    edit(qtbot, w, 1, 2, '90.5')
    edit(qtbot, w, 1, 3, '0.25')
    qtbot.mouseClick(w.play_button, Qt.LeftButton)
    assert w.stack.currentWidget() is w.playback
    assert dialogs.save_dirs == [TONE.parent]
    assert remembered[-1] == target
    saved = load_setlist(target)
    assert [(s.name, s.bpm, s.offset) for s in saved.songs] == [('tone', 120, 0), ('tone', 90.5, .25)]


def test_rename_move_delete_and_declined_save(qtbot, window_factory, monkeypatch, tmp_path):
    target = tmp_path / 'set.yaml'
    class Flaky(Dialogs):
        def save_path(self, directory):
            self.save_dirs.append(directory)
            return None if len(self.save_dirs) == 1 else target
    dialogs = Flaky(files=[TONE, TONE])
    w = window_factory(dialogs=dialogs)
    qtbot.mouseClick(w.add_button, Qt.LeftButton)
    edit(qtbot, w, 0, 0, '!Intro')
    w.table.selectRow(1)
    qtbot.mouseClick(w.up_button, Qt.LeftButton)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.No)
    qtbot.mouseClick(w.remove_button, Qt.LeftButton)
    assert len(w.document.rows) == 2
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Yes)
    qtbot.mouseClick(w.remove_button, Qt.LeftButton)
    assert [r.name for r in w.document.rows] == ['!Intro']
    assert len(dialogs.save_dirs) == 1
    assert w.save(explicit=True)
    assert len(dialogs.save_dirs) == 2
    assert Document.load(target).rows[0].problem() == 'BPM not set'


@pytest.mark.parametrize('source', ['load', 'drop', 'picker'])
def test_async_bpm_suggestion_is_rendered_saved_and_confirmed(qtbot, window_factory, tmp_path, source):
    target = tmp_path / 'suggestions.yaml'
    target.write_text(f'songs:\n  - name: Existing\n    file: {TONE}\n    bpm: 99\n')
    if source == 'load':
        target.write_text(target.read_text() + f'  - name: Blank\n    file: {TONE}\n')
    release = threading.Event()
    calls = []
    def estimator(path, *, cancelled):
        calls.append(path)
        while not release.wait(.005):
            if cancelled():
                return None
        return 118.5
    w = window_factory(Document.load(target), estimator=estimator, dialogs=Dialogs(files=[TONE]))
    if source == 'drop':
        drop(w, [TONE])
    elif source == 'picker':
        qtbot.mouseClick(w.add_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(calls))
    assert w.model.index(1, 2).data().startswith('Analyzing')
    release.set()
    qtbot.waitUntil(lambda: w.model.index(1, 2).data() == '~118.5')
    assert Document.load(target).rows[1].bpm == 118.5
    edit(qtbot, w, 1, 2, '118.5')
    assert w.model.index(1, 2).data() == '118.5'
    assert w.document.rows[0].bpm == 99
    assert calls == [TONE.resolve()]


def test_pending_suggestion_cannot_overwrite_manual_edit(qtbot, window_factory, tmp_path):
    release = threading.Event()
    def estimator(path, *, cancelled):
        while not release.wait(.005):
            if cancelled():
                return None
        return 118.5
    doc = Document(tmp_path / 'set.yaml')
    doc.add_files([TONE, TONE])
    w = window_factory(doc, estimator=estimator)
    assert w.model.index(0, 2).data().startswith('Analyzing')
    assert w.model.index(1, 2).data() == 'Queued'
    edit(qtbot, w, 0, 2, '123')
    release.set()
    qtbot.waitUntil(lambda: w.document.rows[1].bpm == 118.5)
    assert w.document.rows[0].bpm == 123
    qtbot.mouseClick(w.play_button, Qt.LeftButton)
    assert w.suggestions.halt.is_set()
    assert not w.suggestions.worker.is_alive()


def test_timer_does_not_overwrite_text_while_editing(qtbot, window_factory):
    doc = Document(rows=[Row('Song', TONE, 120, duration=1)])
    w = window_factory(doc)
    index = w.model.index(0, 0)
    w.table.edit(index)
    editor = w.table.findChild(QLineEdit)
    editor.selectAll()
    qtbot.keyClicks(editor, 'New name')
    w.refresh()
    assert editor.text() == 'New name'
    qtbot.keyClick(editor, Qt.Key_Return)
    QApplication.processEvents()
    assert doc.rows[0].name == 'New name'


def test_inconclusive_and_invalid_values_stay_unplayable(qtbot, window_factory, tmp_path):
    doc = Document(tmp_path / 'set.yaml')
    doc.add_files([TONE])
    w = window_factory(doc)
    qtbot.waitUntil(lambda: w.model.index(0, 2).data() == 'No estimate')
    w.table.selectRow(0)
    w.refresh()
    assert 'No estimate' in w.row_notice.text()
    qtbot.mouseClick(w.play_button, Qt.LeftButton)
    assert w.audio is None
    assert 'tone: BPM not set' in w.statusBar().currentMessage()
    for col, value in ((2, '0'), (2, 'nan'), (2, 'inf'), (2, '1000'), (3, '-1'), (3, '1'), (0, '')):
        assert not w.model.setData(w.model.index(0, col), value)
    assert doc.rows[0].bpm is None
    assert doc.rows[0].offset == 0


def test_ramp_controls_recreate_the_demo_ramp_up_song(qtbot, window_factory, tmp_path):
    row = Row('Ramp Up', TONE, 120, duration=40)
    doc = Document(tmp_path / 'set.yaml', rows=[row])
    w = window_factory(doc)
    assert not w.model.setData(w.model.index(0, 4), '0')
    edit(qtbot, w, 0, 4, '140')
    edit(qtbot, w, 0, 5, '10')
    edit(qtbot, w, 0, 6, '20')
    saved = load_setlist(doc.path, duration_probe=lambda _: 40)
    demo = load_setlist(FIXTURES / 'demo_ramp_reference.yaml', check_files=False)
    hand_written = demo.songs[1]
    assert hand_written.name == 'Ramp Up'
    assert saved.songs[0].bpm == hand_written.bpm == 120
    assert saved.songs[0].tempo == hand_written.tempo
    ours, theirs = saved.songs[0].tempo_map(40), hand_written.tempo_map(40)
    for t in (0, 5, 10, 15, 20, 30, 40):
        assert ours.B(t) == pytest.approx(theirs.B(t), abs=1e-12)
        assert ours.bpm_at(t) == theirs.bpm_at(t)


def test_ramp_defaults_track_offset_and_run_to_end(qtbot, window_factory, tmp_path):
    row = Row('Ramp', TONE, 120, duration=60, offset=5)
    w = window_factory(Document(tmp_path / 'set.yaml', rows=[row]))
    edit(qtbot, w, 0, 4, '140')
    assert row.tempo == (TempoEvent(5, 140, 55),)
    assert row.problem() is None
    edit(qtbot, w, 0, 5, '10')
    assert row.tempo == (TempoEvent(10, 140, 50),)
    edit(qtbot, w, 0, 6, '20')
    assert row.tempo == (TempoEvent(10, 140, 20),)
    edit(qtbot, w, 0, 6, '')
    assert row.tempo == (TempoEvent(10, 140, 50),)
    edit(qtbot, w, 0, 5, '2')
    assert row.tempo == (TempoEvent(2, 140, 58),)
    qtbot.mouseClick(w.play_button, Qt.LeftButton)
    assert 'first-beat offset' in w.statusBar().currentMessage()
    edit(qtbot, w, 0, 4, '')
    assert row.tempo == ()


def test_start_and_duration_require_end_bpm_and_custom_map_is_readonly(window_factory):
    row = Row('Ramp', TONE, 120, duration=60)
    w = window_factory(Document(rows=[row]))
    assert not w.model.setData(w.model.index(0, 5), '5')
    assert not w.model.setData(w.model.index(0, 6), '5')
    assert 'Set an end BPM first' in w.statusBar().currentMessage()
    row.tempo = (TempoEvent(10, 126, 0), TempoEvent(30, 120, 0))
    original = row.tempo
    for col in (4, 5, 6):
        assert not w.model.flags(w.model.index(0, col)) & Qt.ItemIsEditable
        assert not w.model.setData(w.model.index(0, col), '140')
    assert row.tempo == original
    assert w.model.index(0, 4).data() == 'Custom'


def test_open_new_recents_and_save_as_keep_audio_paths(window_factory, tmp_path):
    source_dir = tmp_path / 'original'
    source_dir.mkdir()
    source = source_dir / 'source.yaml'
    tone = source_dir / 'tone.wav'
    tone.write_bytes(TONE.read_bytes())
    source.write_text('songs:\n  - name: Song  # keep this comment\n    file: tone.wav\n    bpm: 120\n')
    dest_dir = tmp_path / 'elsewhere'
    dest_dir.mkdir()
    target = dest_dir / 'copy.yaml'
    w = window_factory(dialogs=Dialogs(open_=source, save=target))
    w.open_action.trigger()
    row = w.document.rows[0]
    w.save_as()
    assert w.document.rows[0] is row
    assert Document.load(target).rows[0].file == tone
    assert '# keep this comment' in target.read_text()
    assert w.settings.value('recentSets', type=list) == [str(target), str(source)]
    w.new_action.trigger()
    assert not w.document.rows and w.document.path is None
    w.populate_recents()
    w.recent_menu.actions()[0].trigger()
    assert w.document.path == target


def test_unsaved_new_cancel_and_failed_save_as_preserve_document(window_factory, monkeypatch, tmp_path):
    doc = Document(rows=[Row('Keep', TONE, 120, duration=1)])
    w = window_factory(doc, dialogs=Dialogs(save=tmp_path / 'missing' / 'set.yaml'))
    w.dirty = True
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: QMessageBox.Cancel)
    w.new_action.trigger()
    assert w.document is doc
    w.save_as()
    assert w.document is doc and doc.path is None
    assert 'Save failed' in w.statusBar().currentMessage()


def test_bpm_label_shows_ramp_range():
    assert bpm_label(Song('A', TONE, 120)) == '120'
    assert bpm_label(Song('B', TONE, 120, tempo=(TempoEvent(10, 140, 20),))) == '120->140'
    assert bpm_label(Song('C', TONE, 120, tempo=(TempoEvent(10, 126, 0), TempoEvent(50, 120, 0)))) == '120'
    assert bpm_cell(Row('A', TONE, 123), 'manual') == '123'
    assert bpm_cell(Row('B', TONE, 106), 'estimated') == '~106'
    assert bpm_cell(Row('C', TONE, 106), 'partial') == '~106?'


def test_partial_estimate_marker_notice_and_manual_override(qtbot, window_factory, tmp_path):
    doc = Document(tmp_path / 'set.yaml')
    doc.add_files([TONE])
    w = window_factory(doc, estimator=lambda path, **kw: BeatGrid(106.0, .3, partial=True))
    qtbot.waitUntil(lambda: w.model.index(0, 2).data() == '~106?')
    row = doc.rows[0]
    assert row.bpm == 106.0 and row.bpm_estimated and row.offset == .3
    tooltip = w.model.data(w.model.index(0, 2), Qt.ToolTipRole)
    assert 'steady section' in tooltip
    w.table.selectRow(0)
    w.refresh()
    assert 'steady section' in w.row_notice.text()
    # A manual value overrides a partial estimate exactly like a full one.
    assert w.model.setData(w.model.index(0, 2), '110')
    assert w.model.index(0, 2).data() == '110'
    assert not row.bpm_estimated


@pytest.mark.parametrize('source', ['load', 'drop'])
def test_precise_grid_is_saved_and_drives_playback(qtbot, window_factory, tmp_path, source):
    target = tmp_path / 'grid.yaml'
    target.write_text(f'songs:\n  - name: Blank\n    file: {TONE}\n')
    grid = BeatGrid(112.371234567, .237891234)
    doc = Document.load(target) if source == 'load' else Document(target)
    w = window_factory(doc, estimator=lambda *a, **kw: grid)
    if source == 'drop':
        drop(w, [TONE])
    qtbot.waitUntil(lambda: w.document.rows[0].bpm is not None)
    row = w.document.rows[0]
    assert row.bpm == grid.bpm and row.offset == grid.offset
    assert w.model.index(0, 3).data().startswith('~')
    saved = Document.load(target).rows[0]
    assert saved.bpm == grid.bpm and saved.offset == grid.offset
    playback = doc.setlist().songs[0].tempo_map(1)
    assert playback.T(0) == grid.offset
    assert playback.T(1) == pytest.approx(grid.offset + 60 / grid.bpm)
    edit(qtbot, w, 0, 3, '0.2')
    assert w.model.index(0, 3).data() == '0.2'


@pytest.mark.parametrize('source', ['loaded', 'editing'])
def test_explicit_zero_offset_survives_pending_analysis(qtbot, window_factory, tmp_path, source):
    target = tmp_path / 'zero.yaml'
    target.write_text(f'songs:\n  - name: Song\n    file: {TONE}\n    offset: 0\n')
    doc = Document.load(target) if source == 'loaded' else Document(target)
    if source == 'editing':
        doc.add_files([TONE])
    release = threading.Event()
    def estimator(*args, cancelled):
        while not release.wait(.005):
            if cancelled():
                return None
        return BeatGrid(112.371234567, .237891234)
    w = window_factory(doc, estimator=estimator)
    if source == 'editing':
        # Entering the cell itself protects an unfinished edit from the worker.
        w.table.edit(w.model.index(0, 3))
        QApplication.processEvents()
    # Saving an explicit zero must not erase intent before the result arrives.
    doc.save()
    assert Document.load(target).rows[0].offset_explicit
    release.set()
    qtbot.waitUntil(lambda: doc.rows[0].bpm is not None)
    assert doc.rows[0].bpm == 112.371234567
    assert doc.rows[0].offset == 0


def test_pending_grid_cannot_overwrite_bpm_or_tempo_map(qtbot, window_factory, tmp_path):
    doc = Document(tmp_path / 'intent.yaml')
    doc.add_files([TONE, TONE])
    release = threading.Event()
    def estimator(*args, cancelled):
        while not release.wait(.005):
            if cancelled():
                return None
        return BeatGrid(112.371234567, .237891234)
    w = window_factory(doc, estimator=estimator)
    edit(qtbot, w, 0, 2, '123')
    edit(qtbot, w, 1, 4, '140')
    original = doc.rows[1].tempo
    release.set()
    w.suggestions.worker.join(2)
    w.refresh()
    assert doc.rows[0].bpm == 123 and doc.rows[0].offset == 0
    assert doc.rows[1].bpm is None and doc.rows[1].offset == 0
    assert doc.rows[1].tempo == original
    assert w.suggestions.state(doc.rows[1]) == 'manual'
