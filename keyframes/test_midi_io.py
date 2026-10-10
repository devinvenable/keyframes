"""Headless process/port churn regressions. No real MIDI backend is loaded."""
import ctypes
import multiprocessing
import os
import queue
import statistics
import sys
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import mido
import pytest

from midi_io import MidiInputs

HARDWARE = 'MIDIPLUS TBOX 2x2:Midi Out 1 36:0'
CUE = 'ShowSync:ShowSync Cues 128:0'
RENAMED = 'ShowSync:ShowSync Cues 129:0'


class FakeBackend:
    def __init__(self, context):
        self.stage = context.Value('i', 0)
        self.block = context.Value('i', 0)
        self.entered = context.Event()
        self.release = context.Event()
        self.hardware = context.Queue()
        self.cues = context.Queue()
        self.opens = context.Value('i', 0)
        self.closes = context.Value('i', 0)
        self.read_error = context.Value('i', 0)

    def __call__(self):
        return self

    def maybe_block(self, operation):
        if self.block.value == operation:
            self.entered.set()
            if operation == 4 and sys.platform == 'linux':
                # Model the actual failure: native close holds the GIL, so a
                # Python close thread/heartbeat cannot escape it.
                ctypes.PyDLL(None).sleep(30)
            else:
                self.release.wait(30)

    def get_input_names(self):
        self.maybe_block(1)
        return [HARDWARE] + ([] if self.stage.value == 1 else [
            RENAMED if self.stage.value == 2 else CUE])

    def open_input(self, name):
        self.maybe_block(2)
        with self.opens.get_lock():
            self.opens.value += 1
        return FakePort(self, name)


class FakePort:
    def __init__(self, backend, name):
        self.backend, self.name = backend, name

    def iter_pending(self):
        self.backend.maybe_block(3)
        if self.backend.read_error.value and self.name != HARDWARE:
            self.backend.read_error.value = 0
            raise OSError('sender vanished')
        messages = self.backend.hardware if self.name == HARDWARE else self.backend.cues
        while True:
            try:
                yield mido.Message.from_bytes(messages.get_nowait())
            except queue.Empty:
                return

    def close(self):
        with self.backend.closes.get_lock():
            self.backend.closes.value += 1
        self.backend.maybe_block(4)


@pytest.fixture
def rig():
    context = multiprocessing.get_context('spawn')
    backend = FakeBackend(context)
    proxy = MidiInputs(backend_factory=backend, context=context,
                       rescan_seconds=.08, timeout=.4, startup_timeout=5)
    try:
        wait_for(proxy, lambda: proxy.ready)
        yield proxy, backend
    finally:
        proxy.close()
        backend.hardware.close()
        backend.cues.close()


def wait_for(proxy, predicate, seconds=8):
    deadline = time.monotonic() + seconds
    events = []
    while time.monotonic() < deadline:
        events.extend(proxy.poll())
        if predicate():
            return events
        time.sleep(.001)
    assert predicate(), 'fake MIDI worker did not reach the expected state'


def receive(proxy, name, expected):
    received = []

    def has_message():
        source = proxy.sources.get(name)
        if source:
            while not source.empty():
                received.append(source.get_nowait())
        return expected in received

    wait_for(proxy, has_message)
    return received


@pytest.mark.parametrize('same_name', [False, True])
def test_disappear_reappear_and_same_name_rebind_preserve_messages(rig, same_name):
    proxy, backend = rig
    backend.stage.value = 1
    wait_for(proxy, lambda: list(proxy.sources) == [HARDWARE])
    backend.stage.value = 0 if same_name else 2
    name = CUE if same_name else RENAMED
    wait_for(proxy, lambda: name in proxy.sources)
    # Rebinding must also happen with no observable name change at all.
    opened = backend.opens.value
    wait_for(proxy, lambda: backend.opens.value > opened)
    cue = mido.Message('program_change', channel=15, program=2)
    backend.cues.put(cue.bytes())
    assert receive(proxy, name, cue) == [cue]
    note = mido.Message('note_on', channel=1, note=62, velocity=120)
    backend.hardware.put(note.bytes())
    assert receive(proxy, HARDWARE, note) == [note]
    assert backend.closes.value >= 2


@pytest.mark.parametrize('operation', [1, 2, 3, 4], ids=['enumerate', 'open', 'read', 'close-gil'])
def test_blocked_backend_does_not_block_frames_and_recovers(rig, operation):
    proxy, backend = rig
    original = proxy._process.pid
    backend.block.value = operation
    wait_for(proxy, backend.entered.is_set)
    backend.block.value = 0  # Replacement worker can proceed; old remains stuck.
    samples = []
    events = []
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        started = time.monotonic()
        events.extend(proxy.poll())
        samples.append(time.monotonic() - started)
        if proxy._process.pid != original and proxy.ready:
            break
        time.sleep(.001)
    assert proxy._process.pid != original and proxy.ready
    assert max(samples) < .15, 'frame waited on backend shutdown/restart'
    assert any('stalled' in e.get('message', '') for e in events)
    note = mido.Message('note_on', note=60, velocity=99)
    backend.hardware.put(note.bytes())
    assert receive(proxy, HARDWARE, note) == [note]


def test_shutdown_kills_a_native_close_deadlock_within_budget(rig):
    proxy, backend = rig
    process = proxy._process
    backend.block.value = 4
    started = time.monotonic()
    proxy.close()
    elapsed = time.monotonic() - started
    assert backend.entered.is_set(), 'shutdown did not attempt to close ports'
    assert elapsed < 1.0
    assert process._closed, 'worker was not reaped'
    proxy.close()  # Safe if both normal cleanup and an exception call it.


def test_dead_port_read_error_does_not_break_other_inputs(rig):
    proxy, backend = rig
    closed = backend.closes.value
    backend.read_error.value = 1
    events = wait_for(proxy, lambda: backend.closes.value > closed)
    assert any('sender vanished' in e.get('message', '') for e in events)
    note = mido.Message('note_on', note=60)
    backend.hardware.put(note.bytes())
    assert receive(proxy, HARDWARE, note) == [note]
    wait_for(proxy, lambda: CUE in proxy.sources)
    cue = mido.Message('control_change', channel=15, control=102, value=1)
    backend.cues.put(cue.bytes())
    assert receive(proxy, CUE, cue) == [cue]


def test_proxy_delivery_latency_and_byte_semantics(rig):
    proxy, backend = rig
    samples = []
    messages = [mido.Message('clock'), mido.Message('start'), mido.Message('stop'),
                mido.Message('continue'), mido.Message('pitchwheel', pitch=-8192),
                mido.Message('sysex', data=(1, 2, 127)),
                mido.Message('note_on', note=62, velocity=0)]
    for message in messages * 4:
        started = time.monotonic()
        backend.hardware.put(message.bytes())
        assert receive(proxy, HARDWARE, message) == [message]
        samples.append((time.monotonic() - started) * 1000)
    median = statistics.median(samples)
    print(f'Fake input through proxy: median={median:.3f}ms max={max(samples):.3f}ms')
    assert median < 20, 'proxy adds more than one render frame of latency'


def test_default_main_keeps_rendering_and_receives_notes_after_worker_restart(
        rig, tmp_path, monkeypatch):
    import pygame
    import main
    from test_note_echo import no_args_startup, NOTE

    proxy, backend = rig
    pygame.init()
    pygame.display.set_mode((64, 64))
    no_args_startup(tmp_path, monkeypatch, {'enabled': False})
    monkeypatch.delenv('KEYFRAMES_MIDI_LOG', raising=False)
    monkeypatch.delenv('KEYFRAMES_STALL_LOG', raising=False)
    monkeypatch.delenv('KEYFRAMES_BANK_STATE', raising=False)
    monkeypatch.setattr(sys, 'argv', ['keyframes', '--windowed', '--size', '64x64'])
    # Legacy/unfixed main may enumerate here, but must never touch real ports.
    monkeypatch.setattr(main.mido, 'get_input_names', lambda: [])
    monkeypatch.setattr(main, 'MidiInputs', lambda *args: proxy)
    original_pid = proxy._process.pid
    frames = []
    original_draw = main.draw_performance_frame
    original_configure = main.configure_note_source
    configured = False
    completed = False
    sent_first = sent_second = False
    deadline = time.monotonic() + 8

    def configure(*args, **kwargs):
        nonlocal configured
        configured = True
        return original_configure(*args, **kwargs)

    def draw(screen, state, *args, **kwargs):
        nonlocal completed
        frames.append((backend.entered.is_set(), proxy._process.pid, state['note_active']))
        if state['note_active'] == NOTE:
            if sent_second and state['inverted']:
                completed = True
            elif not backend.entered.is_set():
                backend.block.value = 4
        return original_draw(screen, state, *args, **kwargs)

    def events():
        nonlocal sent_first, sent_second
        # Make an initial port snapshot available to main even though the rig
        # fixture waited for readiness before handing it the proxy.
        if configured and not sent_first:
            backend.hardware.put(mido.Message('note_on', note=NOTE, velocity=100).bytes())
            sent_first = True
        if backend.entered.is_set():
            backend.block.value = 0
        if proxy._process.pid != original_pid and proxy.ready and not sent_second:
            backend.hardware.put(mido.Message('note_on', note=NOTE, velocity=100).bytes())
            sent_second = True
        if completed or time.monotonic() > deadline:
            return [pygame.event.Event(pygame.QUIT)]
        return []

    monkeypatch.setattr(main, 'draw_performance_frame', draw)
    monkeypatch.setattr(main, 'configure_note_source', configure)
    monkeypatch.setattr(pygame.event, 'get', events)
    try:
        main.main()
        assert completed, 'default main did not recover note delivery after the deadlock'
        assert sum(blocked and pid == original_pid for blocked, pid, _ in frames) >= 5
        assert proxy._closed, 'main did not shut down its MIDI helper'
    finally:
        pygame.quit()


def _orphan_parent(connection, backend):
    context = multiprocessing.get_context('spawn')
    proxy = MidiInputs(backend_factory=backend, context=context, rescan_seconds=.05)
    wait_for(proxy, lambda: proxy.ready)
    backend.block.value = 4
    wait_for(proxy, backend.entered.is_set)
    connection.send(proxy._process.pid)
    connection.close()
    os._exit(0)  # Model live.sh SIGTERM: no Python finally/atexit cleanup.


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux parent-death signal')
def test_parent_death_kills_even_a_gil_wedged_helper():
    import signal
    from pathlib import Path

    context = multiprocessing.get_context('spawn')
    backend = FakeBackend(context)
    receiver, sender = context.Pipe(duplex=False)
    parent = context.Process(target=_orphan_parent, args=(sender, backend))
    parent.start()
    sender.close()
    worker_pid = None

    def worker_alive():
        try:
            return Path(f'/proc/{worker_pid}/stat').read_text().split()[2] != 'Z'
        except FileNotFoundError:
            return False

    try:
        assert receiver.poll(8), 'test parent failed to start fake helper'
        worker_pid = receiver.recv()
        parent.join(2)
        assert not parent.is_alive()
        deadline = time.monotonic() + 2
        while worker_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert not worker_alive(), 'MIDI helper survived renderer death'
    finally:
        if worker_pid is not None and worker_alive():
            os.kill(worker_pid, signal.SIGKILL)
        if parent.is_alive():
            parent.kill()
            parent.join(1)
        parent.close()
        receiver.close()
        backend.hardware.close()
        backend.cues.close()
