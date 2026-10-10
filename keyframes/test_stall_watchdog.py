"""Render-stall watchdog (task 266) — a wedged main loop must leave a stack.

Keyframes froze intermittently during live runs leaving no evidence: the
process stays alive (live.sh's crash supervisor never fires) and there is no
traceback. With KEYFRAMES_STALL_LOG set, a faulthandler watchdog re-armed
every frame dumps every thread's stack to that file if a frame overruns —
the next live freeze names the wedged call automatically."""
import faulthandler
import os
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

from main import arm_stall_watchdog, resolve_stall_log_path


def test_resolve_stall_log_path_env_gated():
    assert resolve_stall_log_path({}) is None
    assert resolve_stall_log_path({'KEYFRAMES_STALL_LOG': ''}) is None
    assert resolve_stall_log_path(
        {'KEYFRAMES_STALL_LOG': '/tmp/x.log'}) == '/tmp/x.log'


def test_stall_dumps_all_thread_stacks(tmp_path):
    path = tmp_path / 'stall.log'
    rearm = arm_stall_watchdog(str(path), timeout=0.3)
    try:
        assert rearm is not None
        time.sleep(0.8)  # a "frame" overrunning the deadline
    finally:
        faulthandler.cancel_dump_traceback_later()
    text = path.read_text()
    assert 'stall watchdog armed' in text
    # faulthandler's dump header + this very test frame in the stack.
    assert 'Timeout' in text
    assert 'test_stall_dumps_all_thread_stacks' in text


def test_rearming_keeps_a_live_loop_from_dumping(tmp_path):
    path = tmp_path / 'stall.log'
    rearm = arm_stall_watchdog(str(path), timeout=0.5)
    try:
        for _ in range(8):  # a healthy loop: frames well under the deadline
            time.sleep(0.1)
            rearm()
    finally:
        faulthandler.cancel_dump_traceback_later()
    assert 'Timeout' not in path.read_text()


def test_unwritable_path_disables_watchdog_instead_of_raising(tmp_path, capsys):
    rearm = arm_stall_watchdog(str(tmp_path / 'no-such-dir' / 'stall.log'))
    assert rearm is None
    assert 'watchdog off' in capsys.readouterr().out
