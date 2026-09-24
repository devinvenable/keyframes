"""Independent projector window; QImage/QPainter requires no OpenGL backend."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from .video import VideoWorker


class VideoWindow(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent, Qt.Window)
        self.settings = settings
        self.setWindowTitle('ShowSync Video — double-click or F11 for fullscreen')
        self.resize(960, 540)
        self.image = QImage()
        self.picture = None
        self.audio = self.worker = None
        self.key = self.dismissed = None
        self.projector_fullscreen = True
        self.fullscreen = QAction('Fullscreen', self)
        self.fullscreen.setShortcut('F11')
        self.fullscreen.triggered.connect(self.toggle_fullscreen)
        self.addAction(self.fullscreen)
        self.setContextMenuPolicy(Qt.ActionsContextMenu)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.refresh)
        geometry = settings.value('video/geometry')
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.setWindowState(Qt.WindowNoState)
        screen_name = settings.value('video/screen', '')
        screen = next((s for s in QApplication.screens() if s.name() == screen_name),
                      QApplication.primaryScreen())
        self.setScreen(screen)
        if not screen.availableGeometry().intersects(self.frameGeometry()):
            self.move(screen.availableGeometry().topLeft())
        self.windowed_geometry = self.saveGeometry()

    def start(self, audio):
        self.audio = audio
        self.worker = VideoWorker()
        self.dismissed = None
        self.timer.start()
        self.refresh()

    def stop(self):
        self.timer.stop()
        self.audio = None
        if self.worker:
            self.worker.close()
            self.worker = None
        self.key = self.dismissed = None
        self.blank_and_hide()

    def remember(self):
        if not self.projector_fullscreen:
            self.windowed_geometry = self.saveGeometry()
        self.settings.setValue('video/geometry', self.windowed_geometry)
        self.settings.setValue('video/screen', self.screen().name())

    def show_projector(self):
        screen = self.screen()
        self.setWindowFlag(Qt.FramelessWindowHint, self.projector_fullscreen)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.projector_fullscreen)
        self.setScreen(screen)
        if self.projector_fullscreen:
            self.move(screen.geometry().topLeft())
            self.showFullScreen()
        else:
            self.showNormal()
            self.restoreGeometry(self.windowed_geometry)
        self.raise_()

    def blank_and_hide(self):
        self.picture = None
        self.image = QImage()
        if self.isVisible():
            self.remember()
            self.hide()
        self.update()

    def reveal(self):
        self.dismissed = None
        self.refresh()
        if self.isVisible():
            self.raise_()

    def refresh(self):
        if self.audio is None:
            return
        position = self.audio.position()
        layout = position.layout
        songs = layout.setlist.songs if layout is not None else self.audio.setlist.songs
        song = songs[position.song_index]
        path = song.video_source
        # Trim is playback-only: the container keeps its own clock, so the
        # engine's song time maps to `trim` seconds into the file.
        seconds = position.song_time + song.trim
        key = ((path, song.video is None and not song.mute,
                position.epoch, position.song_index)
               if path and not position.ended and not position.gap else None)
        self.worker.submit(key, seconds)
        if key != self.key:
            self.key = key
            self.picture = None
            self.image = QImage()
            self.update()
        if key is None or key == self.dismissed:
            self.blank_and_hide()
            return
        result = self.worker.result
        pictures = result[1] if result and result[0] == key else ()
        # A slow decoder can publish an already obsolete frame; never display it.
        picture = next((p for p in reversed(pictures)
                        if p.pts <= seconds + 1e-9 < p.until), None)
        # Never cover another app with an empty projector, including after a
        # short video ends while its separate backing track keeps playing.
        if picture is None:
            self.blank_and_hide()
            return
        if picture is not self.picture:
            self.picture = picture
            rgb = picture.rgb
            self.image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0],
                                QImage.Format_RGB888).copy()
            self.update()
        if not self.isVisible():
            self.show_projector()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)
        if not self.image.isNull():
            size = self.image.size().scaled(self.size(), Qt.KeepAspectRatio)
            target = self.rect()
            target.setSize(size)
            target.moveCenter(self.rect().center())
            painter.drawImage(target, self.image)

    def toggle_fullscreen(self):
        self.remember()
        self.projector_fullscreen = not self.projector_fullscreen
        if self.isVisible():
            self.show_projector()

    def mouseDoubleClickEvent(self, event):
        self.toggle_fullscreen()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        # Closing the projector must never stop the backing track.
        self.dismissed = self.key
        self.blank_and_hide()
        event.accept()
