"""Replacement exercises native picker routing, viewport drops and persisted gates."""
import threading
import wave

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QFileDialog

from showsync.bpmdetect import BeatGrid, estimate_grid
from showsync.dialogs import Dialogs
from showsync.document import Document, Row
from showsync.setlist import SetlistError, load_setlist
from showsync.tempomap import TempoEvent
from conftest import TONE


def viewport_drop(w, path, row=None):
    point = (w.table.visualRect(w.model.index(row, 0)).center() if row is not None
             else w.table.viewport().rect().bottomLeft() + w.table.viewport().rect().topLeft())
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in (path if isinstance(path, list) else [path])])
    enter = QDragEnterEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(w.table.viewport(), enter)
    move = QDragMoveEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(w.table.viewport(), move)
    assert w.table.drop_row == (-1 if row is None else row)
    assert ('append' if row is None else 'replace') in w.statusBar().currentMessage()
    event = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(w.table.viewport(), event)
    return event.isAccepted()


@pytest.fixture
def replacement(tmp_path):
    path = tmp_path / 'new-take.wav'
    path.write_bytes(TONE.read_bytes())
    return path


@pytest.mark.parametrize('source', ['picker', 'drop'])
def test_replace_preserves_row_and_yaml(qtbot, window_factory, tmp_path, replacement, monkeypatch, source):
    target = tmp_path / 'set.yaml'
    target.write_text(f'''title: "Keep quotes"
songs:
  - name: Before
    file: {TONE}
    bpm: 100
  - name: Custom name  # keep name
    file: {TONE}  # keep file
    bpm: 120
    offset: 0.1
    gap: 2  # keep gap
    restart: true  # keep restart
    tempo:
      - at: 0.4  # keep ramp
        bpm: 140
        ramp: 0.5
    editor:
      bpm_estimated: true
      offset_estimated: true
  - name: After
    file: {TONE}
    bpm: 100
''')
    grid = BeatGrid(112.371234567, .237891234)
    calls = []
    def estimate(path, **kw):
        calls.append(path)
        return grid
    doc = Document.load(target)
    row = doc.rows[1]
    w = window_factory(doc, estimator=estimate)
    w.table.selectRow(1)
    if source == 'picker':
        w.dialogs = Dialogs(w)
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(replacement), ''))
        qtbot.mouseClick(w.replace_button, Qt.LeftButton)
    else:
        assert viewport_drop(w, replacement, 1)
    qtbot.waitUntil(lambda: not row.timing_review)
    assert doc.rows[1] is row and [r.name for r in doc.rows] == ['Before', 'Custom name', 'After']
    assert row.file == replacement and row.duration == 1
    assert row.tempo == (TempoEvent(.4, 140, .5),) and row.gap == 2
    assert calls == [replacement]
    assert row.bpm == grid.bpm and row.offset == grid.offset
    loaded = Document.load(target).rows[1]
    assert loaded.file == replacement and loaded.bpm == grid.bpm and loaded.offset == grid.offset
    assert loaded.bpm_estimated and not loaded.offset_explicit
    assert load_setlist(target).songs[1].file == replacement
    saved = target.read_text()
    assert all(text in saved for text in ('"Keep quotes"', '# keep name', '# keep file', '# keep gap', '# keep restart', '# keep ramp'))
    assert 'file: new-take.wav' in saved
    assert viewport_drop(w, replacement)
    assert len(doc.rows) == 4 and doc.rows[1] is row


@pytest.mark.parametrize('resolution', ['keep', 'detected', 'inconclusive'])
def test_confirmed_timing_requires_review_after_reopen(qtbot, window_factory, tmp_path, replacement, resolution):
    target = tmp_path / 'set.yaml'
    row = Row('tone', TONE, 123, offset=.1, offset_explicit=True, duration=1)
    doc = Document(target, rows=[row])
    grid = None if resolution == 'inconclusive' else BeatGrid(112.371234567, .237891234)
    w = window_factory(doc, estimator=lambda *a, **kw: grid)
    assert w.replace_path(0, replacement)
    qtbot.waitUntil(lambda: row.timing_review != 'pending')
    assert row.name == 'new-take' and row.bpm == 123 and row.offset == .1
    assert row.problem() == 'Replacement audio needs timing review'
    assert ('No estimate' if grid is None else '112.371') in w.row_notice.text()
    w.play()
    assert w.audio is None and 'new-take: Replacement audio needs timing review' in w.statusBar().currentMessage()
    with pytest.raises(SetlistError, match='new-take.*Replacement audio needs timing review'):
        load_setlist(target)
    reopened = Document.load(target)
    assert reopened.rows[0].problem() == row.problem()
    other = window_factory(reopened, estimator=lambda *a, **kw: grid)
    other.table.selectRow(0)
    qtbot.waitUntil(lambda: other.keep_timing_button.isVisible())
    if resolution == 'detected':
        qtbot.waitUntil(lambda: other.use_timing_button.isVisible())
        qtbot.mouseClick(other.use_timing_button, Qt.LeftButton)
    else:
        qtbot.mouseClick(other.keep_timing_button, Qt.LeftButton)
    saved = Document.load(target).rows[0]
    assert saved.problem() is None
    assert (saved.bpm, saved.offset) == ((grid.bpm, grid.offset) if resolution == 'detected' else (123, .1))
    assert not saved.bpm_estimated and saved.offset_explicit
    assert load_setlist(target).songs[0].bpm == saved.bpm


def test_playback_guard_rejects_replacement(window_factory, tmp_path, replacement):
    row = Row('Song', TONE, 120, duration=1)
    w = window_factory(Document(tmp_path / 'set.yaml', rows=[row]))
    w.play()
    assert w.audio is not None
    assert not w.replace_path(0, replacement)
    assert row.file == TONE and row.bpm == 120 and not row.timing_review


def test_invalid_and_ambiguous_drop_leave_row_unchanged(window_factory, tmp_path, replacement):
    row = Row('Song', TONE, 120, duration=1)
    w = window_factory(Document(tmp_path / 'set.yaml', rows=[row]))
    bad = tmp_path / 'bad.wav'
    bad.write_text('not audio')
    assert not w.replace_path(0, bad)
    assert not viewport_drop(w, [replacement, TONE], 0)
    assert row.file == TONE and row.bpm == 120 and not row.timing_review


def test_late_result_cannot_apply_to_replaced_file(qtbot, window_factory, tmp_path, replacement):
    release = threading.Event()
    calls = []
    def estimator(path, *, cancelled):
        calls.append(path)
        if len(calls) == 1:
            while not release.wait(.005):
                if cancelled():
                    return None
            return BeatGrid(99, .1)
        return BeatGrid(112.371234567, .237891234)
    doc = Document(tmp_path / 'set.yaml')
    doc.add_files([TONE])
    w = window_factory(doc, estimator=estimator)
    qtbot.waitUntil(lambda: len(calls) == 1)
    assert w.replace_path(0, replacement)
    release.set()
    qtbot.waitUntil(lambda: not doc.rows[0].timing_review)
    assert calls == [TONE.resolve(), replacement]
    assert doc.rows[0].bpm == 112.371234567 and doc.rows[0].offset == .237891234


def test_cancel_picker_is_noop(qtbot, window_factory, tmp_path, monkeypatch):
    row = Row('Song', TONE, 120, duration=1)
    w = window_factory(Document(tmp_path / 'set.yaml', rows=[row]))
    w.dialogs = Dialogs(w)
    w.table.selectRow(0)
    calls = []
    def picker(*args):
        calls.append(args)
        return '', ''
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', picker)
    qtbot.mouseClick(w.replace_button, Qt.LeftButton)
    assert len(calls) == 1 and calls[0][1] == 'Replace file'
    assert row.file == TONE and not row.timing_review and not w.dirty


def test_pending_replacement_manual_edit_supersedes_late_result(qtbot, window_factory, tmp_path, replacement):
    release = threading.Event()
    def estimator(*args, cancelled):
        while not release.wait(.005):
            if cancelled():
                return None
        return BeatGrid(112.371234567, .237891234)
    row = Row('Song', TONE, 120, duration=1, bpm_estimated=True)
    doc = Document(tmp_path / 'set.yaml', rows=[row])
    w = window_factory(doc, estimator=estimator)
    assert w.replace_path(0, replacement)
    assert Document.load(doc.path).rows[0].timing_review == 'pending'
    with pytest.raises(SetlistError, match='Replacement audio needs timing review'):
        load_setlist(doc.path)
    assert w.model.setData(w.model.index(0, 2), '125')
    assert w.model.setData(w.model.index(0, 3), '0.3')
    release.set()
    qtbot.waitUntil(lambda: not w.suggestions.worker.is_alive())
    w.refresh()
    assert row.timing_review == ''
    assert row.bpm == 125 and row.offset == .3
    assert not row.bpm_estimated and not Document.load(doc.path).rows[0].bpm_estimated
    assert id(row) not in w.suggestions.detected


@pytest.fixture
def beatless(tmp_path):
    path = tmp_path / 'beatless.wav'
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22050)
        audio.writeframes(b'\0\0' * 22050 * 8)
    return path


@pytest.mark.parametrize('selected', [True, False])
@pytest.mark.parametrize('state', ['inconclusive', 'review', 'pending'])
@pytest.mark.parametrize('resolution', ['keep', 'bpm', 'offset', 'detected'])
def test_review_controls_and_playback(qtbot, window_factory, tmp_path, beatless,
                                     selected, state, resolution):
    if resolution == 'detected' and state != 'review':
        pytest.skip('Detected timing requires a fit')
    release = threading.Event()
    grid = BeatGrid(112.3, .2)
    def estimator(path, *, cancelled):
        if state == 'pending':
            while not release.wait(.005):
                if cancelled():
                    return None
        return estimate_grid(path, cancelled=cancelled) if state == 'inconclusive' else grid

    row = Row('Song', TONE, 123, offset=.1, offset_explicit=True, duration=1)
    other = Row('Other', TONE, 120, duration=1)
    target = tmp_path / 'set.yaml'
    w = window_factory(Document(target, rows=[row, other]), estimator=estimator)
    w.resize(900, 500)
    w.table.selectRow(0 if selected else 1)
    assert viewport_drop(w, beatless, 0)
    if state != 'pending':
        qtbot.waitUntil(lambda: row.timing_review == state)
    # Reproduce the gate with a different selected row, too.
    if not selected:
        w.table.selectRow(1)
    qtbot.mouseClick(w.play_button, Qt.LeftButton)
    assert w.audio is None
    assert w.table.currentIndex().row() == 0
    assert w.keep_timing_button.isVisible()
    assert w.keep_timing_button.isEnabled()
    assert w.use_timing_button.isVisible() == (state == 'review')
    message = w.row_notice.text()
    assert 'Keep current timing' in message
    assert ('Use detected timing' in message) == w.use_timing_button.isVisible()
    assert ('No estimate' in message) == (state == 'inconclusive')
    assert ('analyzing' in message) == (state == 'pending')
    assert 'edit BPM/offset' in message
    assert message in w.statusBar().currentMessage()
    for button in (w.keep_timing_button, w.use_timing_button):
        if button.isVisible():
            assert w.editor.rect().contains(button.geometry())
            assert w.childAt(button.mapTo(w, button.rect().center())) is button
    for col in (2, 3):
        assert w.model.flags(w.model.index(0, col)) & Qt.ItemIsEditable

    if resolution in ('keep', 'detected'):
        button = w.keep_timing_button if resolution == 'keep' else w.use_timing_button
        qtbot.mousePress(button, Qt.LeftButton)
        w.refresh()  # A normal refresh must not hide the pressed button.
        assert button.isDown()
        qtbot.mouseRelease(button, Qt.LeftButton)
    else:
        index = w.model.index(0, 2 if resolution == 'bpm' else 3)
        w.table.edit(index)
        editor = w.table.focusWidget()
        editor.selectAll()
        qtbot.keyClicks(editor, '125' if resolution == 'bpm' else '0.3')
        qtbot.keyClick(editor, Qt.Key_Return)
        qtbot.waitUntil(lambda: not row.timing_review)
    assert not row.timing_review
    release.set()
    qtbot.waitUntil(lambda: not w.suggestions.worker.is_alive())
    w.refresh()
    expected = {'keep': (123, .1), 'bpm': (125, .1),
                'offset': (123, .3), 'detected': (112.3, .2)}[resolution]
    assert (row.bpm, row.offset) == expected
    assert not row.timing_review
    saved = Document.load(target).rows[0]
    assert saved.problem() is None
    assert (saved.bpm, saved.offset) == expected
    assert load_setlist(target).songs[0].bpm == expected[0]
    qtbot.mouseClick(w.play_button, Qt.LeftButton)
    assert w.audio is not None
    assert w.stack.currentWidget() is w.playback
