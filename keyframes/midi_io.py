"""MIDI I/O isolation: the renderer never owns a native port.

python-rtmidi 1.5.8 calls closePort() with the GIL held. A daemon thread
cannot contain its close-vs-callback deadlock; a spawned process can. The
socket carries only port lists and MIDI bytes, leaving routing/rendering in
main.py. Nonblocking reads also tolerate a worker dying mid-record.
"""
import json
import multiprocessing
import os
import queue
import signal
import socket
import sys
import time

import mido


HEARTBEAT_SECONDS = 0.1
IO_TIMEOUT_SECONDS = 2.0
STARTUP_TIMEOUT_SECONDS = 10.0
SHUTDOWN_TIMEOUT_SECONDS = 0.25
READ_BYTES_PER_FRAME = 256 * 1024


def _send(sock, kind, **fields):
    sock.sendall((json.dumps(dict(kind=kind, **fields)) + '\n').encode())


def _midi_worker(sock, parent_pid, port_filter, rescan_seconds, backend_factory=None):
    if sys.platform == 'linux':
        # live.sh terminates the renderer with SIGTERM. Even a helper wedged
        # inside a GIL-holding backend must die with it, releasing ALSA clients.
        import ctypes
        if ctypes.CDLL(None).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError('cannot arm MIDI worker parent-death signal')
        if os.getppid() != parent_pid:
            return  # Parent died before prctl armed the signal.
    # Import here so the proxy module itself has no SDL/OpenCV dependency.
    from main import (cue_port_refresh, drain_startup_midi, select_midi_ports,
                      MIDI_FLOOD_READ_CAP)

    backend = backend_factory() if backend_factory else mido
    ports = []
    sock.settimeout(IO_TIMEOUT_SECONDS)

    def report_ports():
        _send(sock, 'ports', names=[p.name for p in ports])

    def open_port(name):
        try:
            ports.append(backend.open_input(name))
        except (OSError, RuntimeError) as exc:
            _send(sock, 'warning', message=f'cannot open MIDI input {name}: {exc}')

    try:
        for name in select_midi_ports(backend.get_input_names(), port_filter):
            open_port(name)
        if ports:
            stale = drain_startup_midi(ports)
            if stale:
                _send(sock, 'warning', message=f'Discarded {stale} stale MIDI event(s) queued before startup.')
        report_ports()
        last_scan = last_heartbeat = time.monotonic()
        while True:
            # The only parent command is shutdown. No backend call is needed
            # to receive it; if a backend blocks, the parent kills this process.
            sock.setblocking(False)
            try:
                if sock.recv(1) in (b'', b'q'):
                    break
            except BlockingIOError:
                pass
            finally:
                sock.settimeout(IO_TIMEOUT_SECONDS)

            for port in list(ports):
                batch = []
                try:
                    for index, msg in enumerate(port.iter_pending()):
                        batch.append(msg.bytes())
                        if len(batch) == 128:
                            _send(sock, 'messages', port=port.name, messages=batch)
                            batch = []
                        if index + 1 >= MIDI_FLOOD_READ_CAP:
                            break
                    if batch:
                        _send(sock, 'messages', port=port.name, messages=batch)
                except (OSError, RuntimeError) as exc:
                    ports.remove(port)
                    report_ports()
                    _send(sock, 'warning', message=f'MIDI input lost {port.name}: {exc}')
                    port.close()

            now = time.monotonic()
            if now - last_scan >= rescan_seconds:
                last_scan = now
                try:
                    stale, fresh = cue_port_refresh(
                        [p.name for p in ports], backend.get_input_names())
                    for name in stale:
                        gone = next(p for p in ports if p.name == name)
                        ports.remove(gone)
                        gone.close()
                    for name in fresh:
                        open_port(name)
                    report_ports()
                except (OSError, RuntimeError) as exc:
                    report_ports()
                    _send(sock, 'warning', message=f'cue port refresh failed: {exc}')
            if now - last_heartbeat >= HEARTBEAT_SECONDS:
                _send(sock, 'heartbeat')
                last_heartbeat = now
            time.sleep(0.001)
    except (EOFError, OSError):
        pass  # Parent disappeared or stopped draining; never keep orphan inputs.
    finally:
        for port in ports:
            port.close()  # May deadlock with the GIL held; parent bounds this.
        sock.close()


class MidiInputs:
    """Nonblocking, render-thread-facing proxy with bounded restart/shutdown.

    Each source is a regular queue consumed by the existing flood/routing
    logic. Backpressure stays in the socket/worker instead of growing an
    additional unbounded queue in the renderer. No MIDI messages are changed.
    """

    def __init__(self, port_filter=None, rescan_seconds=5.0, *,
                 backend_factory=None, context=None,
                 timeout=IO_TIMEOUT_SECONDS,
                 startup_timeout=STARTUP_TIMEOUT_SECONDS):
        self._context = context or multiprocessing.get_context('spawn')
        self._args = (port_filter, rescan_seconds, backend_factory)
        self.timeout = timeout
        self.startup_timeout = startup_timeout
        self.sources = {}
        self.ready = False
        self._closed = False
        self._restarting = False
        self._start()

    def _start(self):
        parent, child = socket.socketpair()
        parent.setblocking(False)
        self._socket = parent
        self._buffer = bytearray()
        self._process = self._context.Process(
            target=_midi_worker, args=(child, os.getpid(), *self._args),
            name='keyframes-midi', daemon=True)
        try:
            self._process.start()
        except BaseException:
            parent.close()
            raise
        finally:
            child.close()
        self._last_reply = time.monotonic()

    def _restart(self, events, reason):
        events.append({'kind': 'warning', 'message': f'MIDI worker {reason}; restarting'})
        self._socket.close()
        if self._process.is_alive():
            self._process.kill()
        # Do not join on the frame loop. Reap on a later frame before opening
        # replacement ports, so at most one worker can own subscriptions.
        self._restarting = True
        self.sources.clear()
        self._buffer.clear()
        self.ready = False
        events.append({'kind': 'ports', 'names': []})

    def poll(self):
        """Advance I/O once per frame; return port changes/diagnostics."""
        events = []
        if self._closed:
            return events
        if self._restarting:
            if not self._process.is_alive():
                self._process.join(0)
                self._process.close()
                self._start()
                self._restarting = False
            return events

        # Leave backpressure in the socket until the frame consumes its queues.
        if not any(q.qsize() >= 4096 for q in self.sources.values()):
            try:
                for _ in range(4):
                    chunk = self._socket.recv(READ_BYTES_PER_FRAME // 4)
                    if not chunk:
                        self._restart(events, 'disconnected')
                        return events
                    self._buffer.extend(chunk)
                    self._last_reply = time.monotonic()
            except BlockingIOError:
                pass
            except OSError as exc:
                self._restart(events, f'disconnected ({exc})')
                return events

        while b'\n' in self._buffer:
            line, _, self._buffer = self._buffer.partition(b'\n')
            record = json.loads(line)
            if record['kind'] == 'messages':
                source = self.sources.get(record['port'])
                if source is not None:
                    for data in record['messages']:
                        source.put(mido.Message.from_bytes(data))
            elif record['kind'] == 'ports':
                self.sources = {name: self.sources.get(name, queue.Queue())
                                for name in record['names']}
                self.ready = True
                events.append(record)
            elif record['kind'] != 'heartbeat':
                events.append(record)

        deadline = self.timeout if self.ready else self.startup_timeout
        if time.monotonic() - self._last_reply > deadline:
            self._restart(events, 'stalled')
        elif not self._process.is_alive():
            self._restart(events, 'exited')
        return events

    def close(self):
        """Request a clean close, then terminate/kill a wedged native backend."""
        if self._closed:
            return
        self._closed = True
        try:
            self._socket.send(b'q')
        except OSError:
            pass
        self._process.join(SHUTDOWN_TIMEOUT_SECONDS)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(SHUTDOWN_TIMEOUT_SECONDS)
        if self._process.is_alive():
            self._process.kill()
            self._process.join(SHUTDOWN_TIMEOUT_SECONDS)
        self._socket.close()
        self.sources.clear()
        if not self._process.is_alive():
            self._process.close()
