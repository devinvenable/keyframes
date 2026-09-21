"""Qt desktop shell. Engines publish snapshots; only transport actions write them."""
from copy import deepcopy
import math
from pathlib import Path
import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QHeaderView, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QStackedWidget, QStyledItemDelegate, QTableView, QVBoxLayout, QWidget,
)

from .bpmdetect import BeatGrid, Suggestions, estimate_grid
from .document import Document
from .tempomap import TempoEvent

FIELDS = ('name', 'file', 'bpm', 'offset', 'ramp', 'start', 'dur', 'restart')
HEADERS = ('Song', 'File', 'BPM', 'Offset (s)', 'End BPM', 'Ramp start (s)', 'Ramp duration (s)',
           'Restart patterns')
EMPTY_HINT = 'Drop audio files here, or choose Add Songs to build your set.'
CUSTOM_TEMPO = 'Custom tempo map — edit in YAML'


def bpm_label(song):
    final = song.tempo[-1].bpm if song.tempo else song.bpm
    return f'{song.bpm:g}' if final == song.bpm else f'{song.bpm:g}->{final:g}'


def timestamp(seconds):
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f'{minutes:02d}:{seconds:02d}'


def bpm_cell(row, state):
    if row.bpm is not None:
        return ('~' if state == 'estimated' else '') + f'{row.bpm:g}'
    if state == 'analyzing':
        return 'Analyzing ' + '◴◷◶◵'[int(time.monotonic() * 6) % 4]
    return {'queued': 'Queued', 'no estimate': 'No estimate'}.get(state, '—')


class SongModel(QAbstractTableModel):
    """An editable view over the existing lenient document, not another model."""
    def __init__(self, window):
        super().__init__(window)
        self.window = window

    @property
    def rows(self):
        return self.window.document.rows

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(FIELDS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return HEADERS[section] if orientation == Qt.Horizontal else str(section + 1)

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and FIELDS[index.column()] == 'restart':
            return flags | Qt.ItemIsUserCheckable
        if index.isValid() and index.column() != 1:
            if not (index.column() >= 4 and self.rows[index.row()].custom_tempo):
                flags |= Qt.ItemIsEditable
        return flags

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = self.rows[index.row()], index.column()
        if FIELDS[col] == 'restart':
            if role == Qt.CheckStateRole:
                return Qt.Checked if row.restart else Qt.Unchecked
            if role == Qt.ToolTipRole:
                return 'Send Stop/Start at this song to restart external patterns (requires Send MIDI Start/Stop).'
            return None
        if role == Qt.ToolTipRole:
            if col >= 4 and row.custom_tempo:
                return CUSTOM_TEMPO
            if col == 1:
                return str(row.file)
            if col == 3 and self.window.suggestions.offset_estimated(row):
                return 'Estimated first beat — double-click to confirm or correct'
            if col == 2:
                return {'estimated': 'Estimated beat grid — double-click BPM or offset to correct',
                        'no estimate': 'No estimate — enter BPM manually'}.get(
                            self.window.suggestions.state(row), row.problem())
            return row.problem()
        if role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        ramp = row.ramp
        values = (row.name, str(row.file), '' if row.bpm is None else f'{row.bpm:g}',
                  f'{row.offset:g}', '' if ramp is None else f'{ramp.bpm:g}',
                  '' if ramp is None else f'{ramp.at:g}',
                  '' if ramp is None else f'{ramp.ramp:g}')
        if role == Qt.DisplayRole:
            if col == 2:
                return bpm_cell(row, self.window.suggestions.state(row))
            if col == 3 and self.window.suggestions.offset_estimated(row):
                return '~' + values[col]
            if col == 4 and row.custom_tempo:
                return 'Custom'
        return values[col]

    def setData(self, index, value, role=Qt.EditRole):
        if index.isValid() and FIELDS[index.column()] == 'restart' and role == Qt.CheckStateRole:
            self.rows[index.row()].restart = value == Qt.Checked.value
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            self.window.changed()
            return True
        if role != Qt.EditRole or not index.isValid() or not self.flags(index) & Qt.ItemIsEditable:
            return False
        row, field = self.rows[index.row()], FIELDS[index.column()]
        value = str(value).strip()
        try:
            if field == 'name':
                if not value:
                    raise ValueError('Name must not be empty')
                row.name = value
            elif field == 'bpm':
                bpm = self.number(value, 'BPM', positive=True, bpm=True) if value else None
                self.window.suggestions.manual(row)
                row.bpm = bpm
            elif field == 'offset':
                offset = self.number(value or '0', 'Offset')
                if row.duration is not None and offset >= row.duration:
                    raise ValueError(f'Offset must be under the file length ({row.duration:g}s)')
                row.offset_explicit = True
                row.offset = offset
            elif field == 'ramp':
                if not value:
                    row.tempo = ()
                else:
                    end = self.number(value, 'End BPM', positive=True, bpm=True)
                    if row.ramp:
                        row.tempo = (TempoEvent(row.ramp.at, end, row.ramp.ramp),)
                    elif row.duration is None or row.offset >= row.duration:
                        raise ValueError('Cannot add a ramp: check the file duration and offset')
                    else:
                        row.tempo = (TempoEvent(row.offset, end, row.duration - row.offset),)
            else:
                event = row.ramp
                if event is None:
                    raise ValueError('Set an end BPM first to add a ramp')
                if field == 'start':
                    start = self.number(value or '0', 'Ramp start')
                    to_end = row.duration is not None and event.at + event.ramp == row.duration
                    length = row.duration - start if to_end and start < row.duration else event.ramp
                    row.tempo = (TempoEvent(start, event.bpm, length),)
                else:
                    if not value:
                        if row.duration is None or event.at >= row.duration:
                            raise ValueError('Cannot reach the end of the file from this ramp start')
                        length = row.duration - event.at
                    else:
                        length = self.number(value, 'Ramp duration', positive=True)
                    row.tempo = (TempoEvent(event.at, event.bpm, length),)
        except ValueError as exc:
            self.window.notice(str(exc))
            return False
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), 6))
        self.window.changed()
        return True

    @staticmethod
    def number(value, name, *, positive=False, bpm=False):
        try:
            result = float(value)
        except ValueError:
            raise ValueError(f'{name} must be a number') from None
        if not math.isfinite(result) or result < 0 or (positive and result == 0) or (bpm and result >= 1000):
            constraint = 'between 0 and 1000' if bpm else 'positive' if positive else 'nonnegative'
            raise ValueError(f'{name} must be {constraint}')
        return result

    def refresh(self):
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(FIELDS) - 1))


class SongDelegate(QStyledItemDelegate):
    """Native cells, including animated BPM suggestion text and plain text edits."""
    def createEditor(self, parent, option, index):
        if index.column() == 2:
            window = index.model().window
            window.suggestions.manual(window.document.rows[index.row()])
        elif index.column() == 3:
            index.model().window.document.rows[index.row()].offset_explicit = True
        return QLineEdit(parent)

    def setEditorData(self, editor, index):
        editor.setText(index.data(Qt.EditRole))
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text())


class SongTable(QTableView):
    """External files replace the highlighted row; empty space appends."""
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.drop_row = -1
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if self.window.audio is None and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if self.window.audio is not None or not event.mimeData().hasUrls():
            event.ignore()
            return
        self.drop_row = self.indexAt(event.position().toPoint()).row()
        if self.drop_row >= 0:
            name = self.window.document.rows[self.drop_row].name
            self.window.notice(f'Drop one audio file to replace “{name}”.')
        else:
            self.window.notice('Drop audio files to append songs.')
        self.viewport().update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.drop_row = -1
        self.viewport().update()
        self.window.notice('')
        event.accept()

    def dropEvent(self, event):
        index = self.indexAt(event.position().toPoint()).row()
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self.drop_row = -1
        self.viewport().update()
        if self.window.audio is not None:
            event.ignore()
            return
        if index >= 0:
            if len(paths) != 1:
                self.window.notice('Drop exactly one audio file to replace a song.')
                event.ignore()
                return
            if not self.window.replace_path(index, paths[0]):
                event.ignore()
                return
        else:
            self.window.add_paths(paths)
        event.acceptProposedAction()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.drop_row >= 0:
            painter = QPainter(self.viewport())
            painter.setPen(QPen(self.palette().highlight().color(), 3))
            rect = self.visualRect(self.model().index(self.drop_row, 0))
            rect.setLeft(1)
            rect.setRight(self.viewport().width() - 2)
            painter.drawRect(rect.adjusted(0, 1, 0, -1))


class MainWindow(QMainWindow):
    def __init__(self, document, *, start_engines, dialogs=None, remember=None,
                 estimator=estimate_grid, settings=None, notice='',
                 clock_offset_ms=0, offset_changed=None, devices=None):
        super().__init__()
        if dialogs is None:
            from .dialogs import Dialogs
            dialogs = Dialogs(self)
        self.dialogs, self.remember = dialogs, remember
        self.document, self.start_engines = document, start_engines
        self.clock_offset_ms = clock_offset_ms
        self.offset_changed = offset_changed
        self.devices = devices
        self.midi_status = QLabel()
        self.midi_status.setTextFormat(Qt.PlainText)
        self.statusBar().addPermanentWidget(self.midi_status)
        self.estimator = estimator
        self.suggestions = Suggestions(estimator)
        self.settings = settings if settings is not None else QSettings('ShowSync', 'ShowSync')
        self.audio = self.clock = self.close_engines = None
        self.save_declined = self.dirty = False
        self._saving = False
        self.baseline = []
        self.setWindowTitle('ShowSync')
        self.resize(1120, 700)
        self.setMinimumSize(760, 520)
        self.setAcceptDrops(True)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self._build_editor()
        self._build_playback()
        self._build_menus()
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.update_title()
        self.refresh()
        if document.path:
            self.record_path()
        if notice:
            self.notice(notice)

    @staticmethod
    def button(text, callback, layout):
        button = QPushButton(text)
        button.setMinimumHeight(36)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _build_editor(self):
        self.editor = QWidget()
        layout = QVBoxLayout(self.editor)
        heading = QLabel('Setlist Editor')
        heading.setStyleSheet('font-size: 24px; font-weight: bold')
        layout.addWidget(heading)
        toolbar = QHBoxLayout()
        self.add_button = self.button('Add Songs…', self.add_songs, toolbar)
        self.replace_button = self.button('Replace file…', self.replace_song, toolbar)
        self.remove_button = self.button('Remove', self.remove_song, toolbar)
        self.up_button = self.button('Move Up', lambda: self.move_song(-1), toolbar)
        self.down_button = self.button('Move Down', lambda: self.move_song(1), toolbar)
        toolbar.addStretch()
        self.play_button = self.button('Play Set', self.play, toolbar)
        self.play_button.setStyleSheet('font-weight: bold; padding: 4px 24px')
        layout.addLayout(toolbar)
        self.empty_hint = QLabel(EMPTY_HINT)
        layout.addWidget(self.empty_hint)
        self.model = SongModel(self)
        self.table = SongTable(self)
        self.table.setModel(self.model)
        self.table.setItemDelegate(SongDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for col, width in enumerate((210, 220, 120, 90, 90, 120, 140, 125)):
            self.table.setColumnWidth(col, width)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.selectionModel().currentChanged.connect(self.show_row_problem)
        layout.addWidget(self.table, 1)
        self.row_notice = QLabel('')
        self.row_notice.setWordWrap(True)
        layout.addWidget(self.row_notice)
        review = QHBoxLayout()
        self.use_timing_button = self.button('Use detected timing', lambda: self.resolve_timing(True), review)
        self.keep_timing_button = self.button('Confirm current timing', lambda: self.resolve_timing(False), review)
        review.addStretch()
        layout.addLayout(review)
        layout.addWidget(QLabel('Drop one file on a row to replace it; drop below the rows to append songs.'))
        layout.addWidget(QLabel('Double-click a cell to edit. Changes save automatically.'))
        self.stack.addWidget(self.editor)

    def _build_playback(self):
        self.playback = QWidget()
        layout = QVBoxLayout(self.playback)
        self.set_label = QLabel()
        layout.addWidget(self.set_label)
        for name, size in (('song_label', 34), ('bpm_label', 38), ('state_label', 20)):
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            label.setStyleSheet(f'font-size: {size}px; font-weight: bold')
            setattr(self, name, label)
            layout.addWidget(label)
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.time_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.next_label = QLabel()
        self.next_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.next_label)
        self.queue = QListWidget()
        layout.addWidget(self.queue, 1)
        order = QHBoxLayout()
        order.addWidget(QLabel('Upcoming songs'))
        self.button('Move Up', lambda: self.move_upcoming(-1), order)
        self.button('Move Down', lambda: self.move_upcoming(1), order)
        order.addStretch()
        layout.addLayout(order)
        controls = QHBoxLayout()
        self.pause_button = self.button('Pause', self.pause, controls)
        self.skip_button = self.button('Skip', self.skip, controls)
        self.restart_button = self.button('Restart', self.restart, controls)
        self.stop_button = self.button('Stop', self.stop, controls)
        self.editor_button = self.button('Return to Editor', self.return_to_editor, controls)
        layout.addLayout(controls)
        offset_row = QHBoxLayout()
        offset_row.addWidget(QLabel('MIDI clock offset (ms)'))
        self.offset_spin = self.make_offset_spin()
        offset_row.addWidget(self.offset_spin)
        self.button('−10 ms', lambda: self.offset_spin.setValue(self.clock_offset_ms - 10), offset_row)
        self.button('+10 ms', lambda: self.offset_spin.setValue(self.clock_offset_ms + 10), offset_row)
        layout.addLayout(offset_row)
        layout.addWidget(QLabel('Increase if gear sounds late; decrease if gear sounds early.'))
        self.stack.addWidget(self.playback)

    def make_offset_spin(self):
        spin = QDoubleSpinBox()
        spin.setRange(-250, 250)
        spin.setDecimals(1)
        spin.setSingleStep(1)
        spin.setValue(self.clock_offset_ms)
        spin.setToolTip('Positive = earlier MIDI ticks; negative = later. Live while playing.')
        spin.valueChanged.connect(self.set_clock_offset)
        return spin

    def set_clock_offset(self, value):
        self.clock_offset_ms = value
        if self.clock is not None:
            self.clock.clock_offset_ms = value
        self.offset_spin.blockSignals(True)
        self.offset_spin.setValue(value)
        self.offset_spin.blockSignals(False)
        if self.offset_changed:
            self.offset_changed(value)

    def clock_preferences(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('MIDI clock offset (ms)')
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Positive = earlier ticks; negative = later.\n'
                               'Increase if gear sounds late; decrease if gear sounds early.\n'
                               'Changes apply live. Use arrows for 1 ms; Ctrl+arrows for 10 ms.'))
        layout.addWidget(self.make_offset_spin())
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def device_preferences(self):
        if self.devices is None:
            return
        from .device_dialog import DeviceDialog
        DeviceDialog(self.devices, self).exec()

    def prepare_devices(self):
        if self.devices is None:
            return
        from .devices import midi_outputs, audio_outputs
        try:
            ports = midi_outputs()
        except Exception:
            ports = []
        try:
            outputs = audio_outputs()
        except Exception:
            outputs = []
        self.devices.resolve(ports, outputs)

    def action(self, menu, text, callback, shortcut=None):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def _build_menus(self):
        file_menu = self.menuBar().addMenu('&File')
        self.new_action = self.action(file_menu, '&New Set', self.new_set, 'Ctrl+N')
        self.open_action = self.action(file_menu, '&Open…', self.open_set, 'Ctrl+O')
        self.action(file_menu, '&Save', lambda: self.save(explicit=True), 'Ctrl+S')
        self.action(file_menu, 'Save &As…', self.save_as, 'Ctrl+Shift+S')
        self.recent_menu = file_menu.addMenu('Recent Sets')
        self.recent_menu.aboutToShow.connect(self.populate_recents)
        file_menu.addSeparator()
        self.action(file_menu, '&Quit', self.close, 'Ctrl+Q')
        self.devices_action = self.action(file_menu, 'Preferences…', self.device_preferences)
        self.offset_action = self.action(file_menu, 'MIDI clock offset…', self.clock_preferences)
        set_menu = self.menuBar().addMenu('&Set')
        self.play_action = self.action(set_menu, '&Play Set', self.play)
        self.pause_action = self.action(set_menu, 'Pause / Resume', self.pause, 'Space')
        self.skip_action = self.action(set_menu, 'Skip', self.skip, 'Ctrl+Right')
        self.restart_action = self.action(set_menu, 'Restart', self.restart, 'Ctrl+R')
        self.stop_action = self.action(set_menu, '&Stop', self.stop, 'Ctrl+.')
        self.editor_action = self.action(set_menu, 'Return to &Editor', self.return_to_editor, 'Ctrl+E')
        view = self.menuBar().addMenu('&View')
        self.fullscreen_action = self.action(view, '&Fullscreen', self.toggle_fullscreen, 'F11')
        self.fullscreen_action.setCheckable(True)
        help_menu = self.menuBar().addMenu('&Help')
        self.action(help_menu, '&About', lambda: QMessageBox.about(
            self, 'About ShowSync', 'ShowSync\nBacking tracks and audio-master MIDI clock.\nQt / PySide6 desktop edition.'))

    def notice(self, message):
        self.statusBar().showMessage(message)

    def update_title(self):
        self.setWindowTitle(f'{self.document.display_title}{" *" if self.dirty else ""} — ShowSync')

    def record_path(self):
        if self.remember:
            self.remember(self.document.path)
        path = str(self.document.path)
        recent = self.settings.value('recentSets', [], type=list)
        self.settings.setValue('recentSets', [path] + [p for p in recent if p != path][:9])

    def populate_recents(self):
        self.recent_menu.clear()
        paths = self.settings.value('recentSets', [], type=list)
        if not paths:
            self.recent_menu.addAction('No recent sets').setEnabled(False)
        for path in paths:
            action = self.action(self.recent_menu, path, lambda checked=False, p=path: self.open_set(p))
            action.setEnabled(self.audio is None)

    def changed(self):
        self.dirty = True
        self.save()
        self.update_title()
        self.show_row_problem()

    def save(self, *, explicit=False):
        if self._saving:
            return False
        self._saving = True
        try:
            if self.document.path is None:
                if self.save_declined and not explicit:
                    return False
                target = self.dialogs.save_path(self.document.default_save_directory())
                if not target:
                    self.save_declined = True
                    self.notice('Not saved yet — choose File > Save to select a file.')
                    return False
                self.document.path = Path(target).expanduser().resolve()
            self.document.save()
            self.record_path()
            self.dirty = False
            self.update_title()
            self.notice(f'Saved {self.document.path.name}')
            return True
        except Exception as exc:
            self.notice(f'Save failed: {exc}')
            return False
        finally:
            self._saving = False

    def save_as(self):
        if self._saving:
            return
        self._saving = True
        try:
            target = self.dialogs.save_path(self.document.path.parent if self.document.path else
                                            self.document.default_save_directory())
            if not target:
                return
            # Keep the original document intact on failure. Preserve relative audio
            # references and comments when moving a saved set to another directory.
            replacement = deepcopy(self.document)
            if replacement._source is not None and replacement.path is not None:
                root = Path(str(replacement._source.get('audio_root', '.'))).expanduser()
                replacement._source['audio_root'] = str((replacement.path.parent / root).resolve())
            replacement.path = Path(target).expanduser().resolve()
            replacement.save()
            self.document.path = replacement.path
            self.document._source = replacement._source
            for row, saved in zip(self.document.rows, replacement.rows):
                row.source_index = saved.source_index
            self.record_path()
            self.dirty = False
            self.update_title()
            self.notice(f'Saved {replacement.path.name}')
        except Exception as exc:
            self.notice(f'Save failed: {exc}')
        finally:
            self._saving = False

    def confirm(self, title, message):
        return QMessageBox.question(self, title, message, QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No) == QMessageBox.Yes

    def can_replace_document(self):
        if self.audio is not None:
            self.notice('Stop the set or return to the editor first.')
            return False
        if not self.dirty:
            return True
        result = QMessageBox.warning(self, 'Unsaved set', 'Save changes before continuing?',
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                     QMessageBox.Save)
        return result == QMessageBox.Discard or (result == QMessageBox.Save and self.save(explicit=True))

    def replace_document(self, document):
        self.suggestions.close()
        self.suggestions = Suggestions(self.estimator)
        self.model.beginResetModel()
        self.document = document
        self.model.endResetModel()
        self.dirty = self.save_declined = False
        self.update_title()
        self.refresh()

    def new_set(self):
        if self.can_replace_document():
            self.replace_document(Document())

    def open_set(self, path=None):
        if not self.can_replace_document():
            return
        try:
            path = path or self.dialogs.setlist_path()
            if path:
                replacement = Document.load(path)
                self.replace_document(replacement)
                self.record_path()
        except Exception as exc:
            self.notice(f'Open failed: {exc}')

    def add_songs(self):
        try:
            self.add_paths(self.dialogs.audio_files())
        except Exception as exc:
            self.notice(f'File dialog unavailable: {exc}')

    def add_paths(self, paths):
        if self.audio is not None:
            self.notice('Return to the editor to add songs.')
            return
        self.model.beginResetModel()
        try:
            added, rejected = self.document.add_files(paths)
        finally:
            self.model.endResetModel()
        if added:
            self.table.selectRow(len(self.document.rows) - len(added))
            self.changed()
        if rejected:
            self.notice('; '.join(f'Skipped {p.name}: {reason}' for p, reason in rejected))
        self.refresh()

    def dragEnterEvent(self, event):
        if self.audio is None and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def replace_song(self):
        index = self.table.currentIndex().row()
        if self.audio is not None or index < 0:
            return
        try:
            path = self.dialogs.replacement_file(self.document.rows[index].file)
            if path:
                self.replace_path(index, path)
        except Exception as exc:
            self.notice(f'File dialog unavailable: {exc}')

    def replace_path(self, index, path):
        if self.audio is not None:
            self.notice('Return to the editor to replace a song’s file.')
            return False
        row = self.document.rows[index]
        try:
            self.document.replace_file(row, path)
        except ValueError as exc:
            self.notice(f'Cannot replace {row.name}: {exc}')
            return False
        self.suggestions.replaced(row)
        self.table.selectRow(index)
        self.changed()
        self.refresh()
        return True

    def resolve_timing(self, use_detected):
        index = self.table.currentIndex().row()
        if self.audio is not None or index < 0:
            return
        row = self.document.rows[index]
        if not row.timing_review or id(row) in self.suggestions.replacements:
            return
        value = self.suggestions.detected.get(id(row))
        if use_detected:
            if value is None:
                return
            row.bpm = value.bpm if isinstance(value, BeatGrid) else value
            if isinstance(value, BeatGrid):
                row.offset = value.offset
        if row.bpm is None:
            self.notice('Enter a BPM before confirming timing.')
            return
        row.timing_review = ''
        row.offset_explicit = True
        self.suggestions.manual(row)
        self.changed()
        self.refresh()

    def dropEvent(self, event):
        if self.audio is None:
            self.add_paths([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
            event.acceptProposedAction()

    def remove_song(self):
        index = self.table.currentIndex().row()
        if index < 0:
            return
        row = self.document.rows[index]
        if self.confirm('Remove song', f'Remove “{row.name}” from the set?'):
            self.model.beginRemoveRows(QModelIndex(), index, index)
            self.document.rows.pop(index)
            self.model.endRemoveRows()
            self.changed()

    def move_song(self, delta):
        index = self.table.currentIndex().row()
        target = index + delta
        if index < 0 or not 0 <= target < len(self.document.rows):
            return
        self.model.beginMoveRows(QModelIndex(), index, index, QModelIndex(), target if delta < 0 else target + 1)
        self.document.rows.insert(target, self.document.rows.pop(index))
        self.model.endMoveRows()
        self.table.selectRow(target)
        self.changed()

    def show_row_problem(self, *args):
        index = self.table.currentIndex().row()
        self.replace_button.setEnabled(self.audio is None and index >= 0)
        self.use_timing_button.setVisible(False)
        self.keep_timing_button.setVisible(False)
        if 0 <= index < len(self.document.rows):
            row = self.document.rows[index]
            message = row.problem() or (CUSTOM_TEMPO if row.custom_tempo else '')
            state = self.suggestions.state(row)
            if state == 'estimated' and not row.problem():
                message = 'Estimated beat grid (~) — double-click BPM or offset to correct.'
            elif state == 'no estimate' and row.bpm is None:
                message = 'No estimate — enter BPM manually.'
            if row.timing_review:
                pending = id(row) in self.suggestions.replacements
                value = self.suggestions.detected.get(id(row))
                message = 'Replacement audio: analyzing timing…' if pending else 'Replacement audio needs timing review.'
                if value is not None:
                    bpm = value.bpm if isinstance(value, BeatGrid) else value
                    message += f' Detected BPM: {bpm:.9g}'
                    if isinstance(value, BeatGrid):
                        message += f'; offset: {value.offset:.9g}s'
                    message += '. Confirm current values or use detected timing.'
                elif not pending:
                    message += ' No estimate — enter/check BPM and offset, then confirm current timing.'
                self.use_timing_button.setVisible(not pending and value is not None)
                self.keep_timing_button.setVisible(not pending)
            self.row_notice.setText(f'{row.name}: {message}' if message else '')
        else:
            self.row_notice.clear()

    def play(self):
        if self.audio is not None:
            return
        blocked = self.document.first_problem()
        if blocked:
            row, message = blocked
            self.notice(f'Cannot play — {row.name + ": " if row else ""}{message}')
            return
        self.prepare_devices()
        self.suggestions.close()
        try:
            self.audio, self.clock, self.close_engines = self.start_engines(self.document.setlist())
        except Exception as exc:
            self.suggestions = Suggestions(self.estimator)
            self.notice(f'Could not start the show: {exc}')
            return
        if self.devices is not None:
            self.midi_status.setText(f'MIDI: {self.devices.midi_name or "No output (audio only)"}')
        self.baseline = list(self.document.rows)
        self.populate_queue()
        self.stack.setCurrentWidget(self.playback)
        self.notice(self.devices.notice if self.devices else '')
        self.refresh()

    def shutdown_engines(self):
        close = self.close_engines
        self.close_engines = None
        try:
            if close:
                close()  # CLI factory sends MIDI Stop, then closes audio and MIDI.
        finally:
            self.audio = self.clock = None
            self.midi_status.clear()

    def return_to_editor(self, *, confirm=True):
        if self.audio is None:
            return
        if confirm and not self.audio.position().ended and not self.confirm(
                'Return to editor', 'Stop this set and return to the editor?'):
            return
        try:
            self.shutdown_engines()
        except Exception as exc:
            self.notice(f'Could not close devices: {exc}')
        self.suggestions = Suggestions(self.estimator)
        self.model.beginResetModel()
        self.model.endResetModel()
        self.stack.setCurrentWidget(self.editor)
        self.refresh()

    def stop(self):
        self.return_to_editor(confirm=False)

    def pause(self):
        if self.audio is not None and not self.audio.position().ended:
            self.audio.toggle_pause()

    def skip(self):
        if self.audio is not None and not self.audio.position().ended:
            self.audio.skip()

    def restart(self):
        if self.audio is not None and (self.audio.position().ended or self.confirm(
                'Restart set', 'Stop this performance and restart from the first song?')):
            self.audio.restart()

    def populate_queue(self):
        self.queue.clear()
        for song in self.audio.setlist.songs:
            self.queue.addItem(f'{song.name}  ({bpm_label(song)} BPM)')

    def move_upcoming(self, delta):
        if self.audio is None:
            return
        target = self.audio.move(self.queue.currentRow(), delta)
        if target is None:
            self.notice('That song cannot move now. Only unplayed songs can move during playback.')
            return
        self.document.rows = [self.baseline[i] for i in self.audio.order]
        self.populate_queue()
        self.queue.setCurrentRow(target)
        self.changed()

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()
        self.fullscreen_action.setChecked(self.isFullScreen())

    def refresh(self):
        """30 Hz reader: no transport mutations or MIDI sends in painting."""
        live = self.audio is not None
        self.devices_action.setEnabled(not live)
        self.play_action.setEnabled(not live)
        self.pause_action.setEnabled(live)
        self.skip_action.setEnabled(live)
        self.restart_action.setEnabled(live)
        self.stop_action.setEnabled(live)
        self.editor_action.setEnabled(live)
        self.new_action.setEnabled(not live)
        self.open_action.setEnabled(not live)
        if not live:
            if not self._saving and self.suggestions.update(self.document.rows):
                self.changed()
            # Do not reset a live cell editor with periodic dataChanged signals.
            if self.table.state() != QAbstractItemView.EditingState:
                self.model.refresh()
            self.empty_hint.setVisible(not self.document.rows)
            self.show_row_problem()
            return
        audio = self.audio
        p = audio.position()
        songs = audio.setlist.songs
        song, tempo = songs[p.song_index], audio.maps[p.song_index]
        self.set_label.setText(f'{audio.setlist.title}  •  {p.song_index + 1}/{len(songs)} songs')
        self.song_label.setText(song.name)
        target = tempo.ramp_target(p.song_time)
        self.bpm_label.setText(f'{tempo.bpm_at(p.song_time):.1f} BPM' +
                               (f'  → {target:g}' if target is not None else ''))
        state = ('End of set' if p.ended else 'Paused' if not p.playing else
                 'Gap' if p.gap else 'Lead-in' if p.song_time < song.offset else 'Playing')
        self.state_label.setText(state)
        style = 'background: #fff1d6; color: #594018' if state == 'Paused' else ''
        if self.playback.styleSheet() != style:
            self.playback.setStyleSheet(style)
        duration = audio.durations[p.song_index]
        elapsed = min(duration, p.song_time)
        self.time_label.setText(f'{timestamp(elapsed)} elapsed    /    {timestamp(duration - elapsed)} remaining')
        self.progress.setValue(round(1000 * elapsed / duration))
        upcoming = songs[p.song_index + 1] if p.song_index + 1 < len(songs) else None
        self.next_label.setText('Set complete — restart or return to the editor.' if p.ended else
                                f'Next: {upcoming.name}  ({bpm_label(upcoming)} BPM)' if upcoming else 'Next: end of set')
        self.pause_button.setText('Pause' if p.playing else 'Resume')
        self.pause_button.setEnabled(not p.ended)
        self.skip_button.setEnabled(not p.ended)
        self.pause_action.setEnabled(not p.ended)
        self.skip_action.setEnabled(not p.ended)
        if audio.underruns:
            self.notice(f'Audio underruns: {audio.underruns}')
        error = audio.error or self.clock.error
        if error:
            # Defer shutdown out of snapshot rendering to the event queue.
            self.timer.stop()
            QTimer.singleShot(0, lambda: self.handle_engine_error(error))

    def handle_engine_error(self, error):
        self.stop()
        self.notice(error)
        self.timer.start()

    def closeEvent(self, event):
        if self.audio is not None and not self.audio.position().ended:
            if not self.confirm('Quit ShowSync', 'Stop the set and quit ShowSync?'):
                event.ignore()
                return
        elif self.audio is None and not self.can_replace_document():
            event.ignore()
            return
        self.timer.stop()
        self.suggestions.close()
        try:
            self.shutdown_engines()
        except Exception as exc:
            self.notice(f'Could not close devices: {exc}')
            event.ignore()
            self.timer.start()
            return
        event.accept()


def main_loop(document, *, start_engines, dialogs=None, remember=None, notice='',
              clock_offset_ms=0, offset_changed=None, devices=None):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(document, start_engines=start_engines, dialogs=dialogs,
                        remember=remember, notice=notice, clock_offset_ms=clock_offset_ms,
                        offset_changed=offset_changed, devices=devices)
    window.show()
    try:
        return app.exec()
    finally:
        window.suggestions.close()
        window.shutdown_engines()
