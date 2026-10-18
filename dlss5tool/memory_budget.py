"""System RAM/commit headroom for disposable caches, never model precision.

The saved cache preference remains an upper bound. Leave at least 2 GiB or
one eighth of RAM (whichever is larger) for the OS, models and active frames;
cache data can use at most one quarter of physical RAM. Pressure may shrink
existing caches below that cap. This is not a process-wide allocation quota.
"""
import ctypes as C
from functools import lru_cache
import os
import threading
import time

_GIB = 1024**3
_snapshot_lock = threading.Lock()
_snapshot = None
_snapshot_time = float('-inf')


class _MemoryStatus(C.Structure):
    _fields_ = [('length', C.c_uint32), ('load', C.c_uint32)] + [
        (name, C.c_uint64) for name in (
            'total_physical', 'free_physical', 'total_commit', 'free_commit',
            'total_virtual', 'free_virtual', 'extended')]


@lru_cache(maxsize=1)
def _status_function():
    if os.name != 'nt':
        return None
    kernel = C.WinDLL('kernel32', use_last_error=True)
    function = kernel.GlobalMemoryStatusEx
    function.argtypes = [C.POINTER(_MemoryStatus)]
    function.restype = C.c_int
    return function


def system_memory():
    """Cheap cached Windows snapshot; unavailable platforms retain prior policy."""
    global _snapshot, _snapshot_time
    with _snapshot_lock:
        now = time.monotonic()
        if now - _snapshot_time < .25:
            return _snapshot
        try:
            function = _status_function()
            status = _MemoryStatus()
            status.length = C.sizeof(status)
            if function is None or not function(C.byref(status)):
                result = None
            else:
                result = {'total_physical_bytes': status.total_physical,
                          'free_physical_bytes': status.free_physical,
                          'free_commit_bytes': status.free_commit}
        except (OSError, AttributeError):
            result = None
        _snapshot, _snapshot_time = result, now
        return result


def cache_limit_bytes(requested, cached=0, *, memory=None):
    """Limit total cache bytes, crediting already allocated cached memory once.

    Subtract a headroom deficit too: clamping free headroom to zero first would
    keep a full cache intact under pressure. Active inputs/copies are not given
    cache credit and must fit within the reserved headroom.
    """
    requested, cached = max(0, int(requested)), max(0, int(cached))
    memory = system_memory() if memory is None else memory
    if not memory:
        return requested
    total = int(memory['total_physical_bytes'])
    if total <= 0:
        return requested
    reserve = max(2 * _GIB, total // 8)
    headroom = min(int(memory['free_physical_bytes']), int(memory['free_commit_bytes']))
    return max(0, min(requested, total // 4, cached + headroom - reserve))


def memory_headroom_bytes(*, memory=None):
    """RAM and commit available after the system/model/active-frame reserve."""
    memory = system_memory() if memory is None else memory
    if not memory or int(memory['total_physical_bytes']) <= 0:
        return None
    reserve = max(2 * _GIB, int(memory['total_physical_bytes']) // 8)
    return max(0, min(int(memory['free_physical_bytes']),
                      int(memory['free_commit_bytes'])) - reserve)


def bounded_frame_count(requested, frame_bytes):
    """Let a read-ahead/slot queue consume at most 1/4 of remaining headroom.

    Zero means even one entry does not fit. The rest remains available to the
    other processing stages; this is an upper bound, not an allocation promise.
    """
    requested = max(1, int(requested))
    headroom = memory_headroom_bytes()
    if headroom is None:
        return requested
    return min(requested, headroom // (4 * max(1, int(frame_bytes))))
