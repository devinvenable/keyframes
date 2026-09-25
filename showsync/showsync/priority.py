"""Best-effort priority for the calling clock thread; denial is non-fatal."""
import ctypes
import logging
import os
import sys

LOG = logging.getLogger(__name__)

_POLICIES = ('SCHED_OTHER', 'SCHED_FIFO', 'SCHED_RR', 'SCHED_BATCH', 'SCHED_IDLE')

# The audio callback feeds the DAC — the hardest deadline — so it outranks
# the clock thread's SCHED_RR prio 1.
CALLBACK_PRIORITY = 2


def elevate_thread(priority, api=None):
    """Request SCHED_RR for the calling thread; return the achieved schedule.

    Never logs and never raises: the audio callback calls this, where logging
    could block. Denial is folded into the returned readback string so the
    producer thread can log it as either positive proof or the fallback.
    """
    api = os if api is None else api
    try:
        api.sched_setscheduler(0, api.SCHED_RR, api.sched_param(priority))
    except (OSError, AttributeError) as exc:
        achieved = thread_schedule(api) or 'an unknown policy'
        return f'{achieved} (SCHED_RR denied: {exc})'
    return thread_schedule(api) or f'SCHED_RR prio {priority}'


def thread_schedule(api=None):
    """Read back the calling thread's achieved policy+priority, or None.

    A good take must carry positive proof of real-time scheduling, so this
    queries the kernel rather than assuming a successful request stuck.
    """
    api = os if api is None else api
    try:
        policy = api.sched_getscheduler(0)
        priority = api.sched_getparam(0).sched_priority
    except (OSError, AttributeError):
        return None
    names = {getattr(api, name): name for name in _POLICIES if hasattr(api, name)}
    label = names.get(policy, f'policy {policy}')
    return f'{label} prio {priority}' if priority else label


def raise_thread_priority(*, platform=None, windows=None, posix=None):
    platform = sys.platform if platform is None else platform
    try:
        if platform == 'win32':
            kernel = windows if windows is not None else ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetCurrentThread.restype = ctypes.c_void_p
            kernel.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
            kernel.SetThreadPriority.restype = ctypes.c_int
            if not kernel.SetThreadPriority(kernel.GetCurrentThread(), 2):
                raise OSError('SetThreadPriority denied')
            granted = 'Windows priority ABOVE_NORMAL'
        elif platform == 'darwin':
            lib = posix if posix is not None else ctypes.CDLL(None)
            class SchedParam(ctypes.Structure):
                _fields_ = [('sched_priority', ctypes.c_int)]
            lib.pthread_self.restype = ctypes.c_void_p
            lib.pthread_setschedparam.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(SchedParam)]
            lib.pthread_setschedparam.restype = ctypes.c_int
            # Darwin SCHED_RR = 2. Permission depends on the login/session policy.
            if lib.pthread_setschedparam(lib.pthread_self(), 2, ctypes.byref(SchedParam(10))):
                raise OSError('pthread_setschedparam denied')
            granted = 'SCHED_RR prio 10'
        else:
            api = os if posix is None else posix
            api.sched_setscheduler(0, api.SCHED_RR, api.sched_param(1))
            granted = thread_schedule(api) or 'SCHED_RR prio 1'
        LOG.info('clock thread: %s', granted)
        return True
    except (OSError, AttributeError) as exc:
        fallback = thread_schedule(os if posix is None else posix)
        LOG.info('clock priority unchanged: %s — running %s',
                 exc, fallback or 'the default policy')
        return False
