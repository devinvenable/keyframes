"""Best-effort priority for the calling clock thread; denial is non-fatal."""
import ctypes
import logging
import os
import sys


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
        else:
            api = os if posix is None else posix
            api.sched_setscheduler(0, api.SCHED_RR, api.sched_param(1))
        return True
    except (OSError, AttributeError) as exc:
        logging.getLogger(__name__).info('clock priority unchanged: %s', exc)
        return False
