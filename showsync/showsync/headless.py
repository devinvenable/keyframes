"""Headless show runner: playback engines + projector, no editor window.

For solo recording takes the editor GUI only adds windows and GPU load.
--headless keeps the engine lifecycle, MIDI clock egress, audio, and the
projector's fullscreen show/hide behavior exactly as in GUI mode, but the
only window that ever appears is the projector (task 143)."""
import logging
import signal

from PySide6.QtCore import QObject, QSettings, QTimer, Signal
from PySide6.QtWidgets import QApplication

from .identity import application_arguments, configure_identity


class HeadlessShow(QObject):
    # Cross-thread bridge: rtmidi delivers transport bytes on its own
    # thread; the queued signal hands them to the GUI thread.
    transport_received = Signal(int)

    def __init__(self, document, *, start_engines, settings, quit,
                 devices=None, autostart=None, midi_transport=False):
        super().__init__()
        self.document, self.start_engines = document, start_engines
        self.devices, self.quit = devices, quit
        self.audio = self.clock = self.close_engines = None
        self.midi_input = None
        from .video_window import VideoWindow
        self.video_window = VideoWindow(settings, on_escape=self.request_quit)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()  # also wakes Python so SIGINT/SIGTERM are seen
        if midi_transport:
            self.enable_midi_transport()
        if autostart is not None:
            logging.info('Autostart: set begins in %gs (Ctrl+C to abort).', autostart)
            QTimer.singleShot(round(autostart * 1000), self.play)
        elif not midi_transport:
            logging.warning('--headless without --autostart or --midi-transport: '
                            'nothing will start the set.')

    def play(self):
        if self.audio is not None:
            return
        if self.devices is not None:
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
        try:
            self.audio, self.clock, self.close_engines = self.start_engines(self.document.setlist())
        except Exception as exc:
            self.fail(f'Could not start the show: {exc}')
            return
        if self.devices is not None and self.devices.notice:
            logging.info('%s', self.devices.notice)
        self.video_window.start(self.audio)
        logging.info('Set started: %s', self.document.display_title)

    def pause(self):
        if self.audio is not None and not self.audio.position().ended:
            self.audio.toggle_pause()

    def stop_set(self):
        """Stop and close engines; the process stays up for another Start."""
        if self.audio is None:
            return
        self.video_window.stop()
        close, self.close_engines = self.close_engines, None
        try:
            if close:
                close()  # CLI factory sends MIDI Stop, then closes audio and MIDI.
        finally:
            self.audio = self.clock = None

    def enable_midi_transport(self):
        """--midi-transport: hardware Play/Stop drive the set like GUI mode."""
        from .transport import TransportControl, connect_transport
        self.transport = TransportControl(
            is_active=lambda: self.audio is not None,
            is_playing=lambda: (self.audio is not None
                                and (p := self.audio.position()).playing and not p.ended),
            is_paused=lambda: (self.audio is not None
                               and not (p := self.audio.position()).playing and not p.ended),
            start=self.play, resume=self.pause, stop=self.stop_set)
        self.midi_input = connect_transport(
            self, self.transport, self.devices.midi if self.devices else None)

    def refresh(self):
        if self.audio is None:
            return
        error = self.audio.error or self.clock.error
        if error:
            # Defer shutdown out of snapshot rendering to the event queue.
            self.timer.stop()
            QTimer.singleShot(0, lambda: self.fail(error))
            return
        if self.audio.position().ended:
            logging.info('Set complete — exiting.')
            self.request_quit()

    def fail(self, message):
        logging.error('%s', message)
        self.request_quit(1)

    def request_quit(self, code=0):
        self.timer.stop()
        self.quit(code)

    def shutdown(self):
        self.timer.stop()
        if self.midi_input is not None:
            self.midi_input.close_port()
            self.midi_input = None
        self.stop_set()


def headless_loop(document, *, start_engines, remember=None, settings=None,
                  devices=None, autostart=None, midi_transport=False):
    """Run one headless show to completion; returns the process exit code."""
    app = QApplication.instance() or QApplication(application_arguments())
    configure_identity()
    if settings is None:
        settings = QSettings('ShowSync', 'ShowSync')
    if remember and document.path:
        remember(document.path)
    show = HeadlessShow(document, start_engines=start_engines, settings=settings,
                        quit=app.exit, devices=devices, autostart=autostart,
                        midi_transport=midi_transport)
    # Qt's event loop swallows SIGINT/SIGTERM; exit the loop cleanly instead
    # so engines close (sending MIDI Stop) and the process exits 0.
    previous = {sig: signal.signal(sig, lambda *_: show.request_quit())
                for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        return app.exec()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        show.shutdown()
