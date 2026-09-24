import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

assert os.environ['DISPLAY'] != ':0'
root = Path.cwd()
sys.path[:0] = [str(root), str(root / 'tests')]
from test_video import make_video
from showsync.audio import AudioEngine
from showsync.document import Document, Row
from showsync.gui import MainWindow
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication([])

def wait_for(predicate):
    end = time.monotonic() + 40
    while not predicate():
        assert time.monotonic() < end, 'Timed out'
        app.processEvents()
        time.sleep(.02)
    app.processEvents()

def xprop(*args):
    return subprocess.check_output(['xprop', *args], text=True)

def stacking():
    return [int(item, 16) for item in re.findall(r'0x[0-9a-f]+', xprop('-root', '_NET_CLIENT_LIST_STACKING'))]

with tempfile.TemporaryDirectory(prefix='showsync-130-smoke-') as directory:
    tmp = Path(directory)
    with (tmp / 'wm.log').open('w') as log:
        wm = subprocess.Popen(['mutter', '--x11', '--sm-disable'], stdout=log, stderr=log)
        background = window = None
        try:
            wait_for(lambda: '_NET_SUPPORTING_WM_CHECK(WINDOW)' in xprop('-root', '_NET_SUPPORTING_WM_CHECK'))
            clip = make_video(tmp / 'clip.mp4')
            def start(setlist):
                audio = AudioEngine(setlist)
                return audio, SimpleNamespace(error=None), audio.close
            window = MainWindow(Document(rows=[Row('clip', clip, 120)]), start_engines=start,
                                estimator=lambda *a, **k: None,
                                settings=QSettings(str(tmp / 'settings.ini'), QSettings.IniFormat))
            window.show()
            app.processEvents()
            background = subprocess.Popen([sys.executable, '-c', '''
import pygame, sys, time
from pathlib import Path
pygame.display.init()
pygame.display.set_caption('Task 130 pygame fullscreen background')
screen = pygame.display.set_mode((1280,720), pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF)
Path(sys.argv[1]).write_text(str(pygame.display.get_wm_info()['window']))
count = 0
while True:
    pygame.event.pump()
    screen.fill((0, 160, 0))
    pygame.display.flip()
    count += 1
    Path(sys.argv[2]).write_text(str(count))
    time.sleep(.02)
''', str(tmp / 'background.id'), str(tmp / 'heartbeat')], stdout=subprocess.DEVNULL, env={**os.environ, 'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/tmp/showsync-130-no-bus'})
            wait_for(lambda: (tmp / 'background.id').exists())
            bg = int((tmp / 'background.id').read_text())
            wait_for(lambda: bg in stacking())
            window.play()
            projector = window.video_window
            wait_for(lambda: projector.isVisible() and not projector.image.isNull())
            wid = int(projector.winId())
            wait_for(lambda: wid in stacking() and stacking().index(wid) > stacking().index(bg))
            state = xprop('-id', str(wid), '_NET_WM_STATE')
            assert '_NET_WM_STATE_FULLSCREEN' in state and '_NET_WM_STATE_ABOVE' in state, state
            assert projector.windowFlags() & Qt.FramelessWindowHint
            assert projector.geometry() == projector.screen().geometry()
            beat = int((tmp / 'heartbeat').read_text())
            QTest.qWait(200)
            assert int((tmp / 'heartbeat').read_text()) > beat
            # Capture only the isolated Xvfb display for an actual compositor pixel check.
            pixel = app.primaryScreen().grabWindow(0).toImage().pixelColor(640, 360)
            assert abs(pixel.red() - 20) < 5 and abs(pixel.green() - 20) < 5, pixel.getRgb()
            QTest.keyClick(projector, Qt.Key_Escape)
            wait_for(lambda: not projector.isFullScreen())
            projector.fullscreen.trigger()
            wait_for(lambda: projector.isFullScreen())
            window.stop()
            wait_for(lambda: not projector.isVisible())
            QTest.qWait(300)
            pixel = app.primaryScreen().grabWindow(0).toImage().pixelColor(640, 360)
            assert pixel.green() == 160 and pixel.red() == 0, pixel.getRgb()
            assert background.poll() is None
            print('PASS: MainWindow video playback covers fullscreen pygame; FULLSCREEN/ABOVE flags, borderless, screen bounds, frame pixel, Escape, fullscreen restore, stop reveals pygame, independent pygame heartbeat.')
        finally:
            if window:
                window.timer.stop()
                window.suggestions.close()
                window.shutdown_engines()
                window.dirty = False
                window.close()
            if background:
                background.kill()
                background.wait(timeout=5)
            wm.terminate()
            wm.wait(timeout=5)
