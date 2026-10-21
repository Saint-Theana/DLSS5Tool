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


def system_memory(*, refresh=False):
    """Cheap cached Windows snapshot; unavailable platforms retain prior policy."""
    global _snapshot, _snapshot_time
    with _snapshot_lock:
        now = time.monotonic()
        if not refresh and now - _snapshot_time < .25:
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


def require_memory_headroom(required_bytes):
    """Reject known upcoming frame allocations before creating their owners.

    This checks RAM and commit after the shared system reserve. It does not
    reserve memory globally or change policy when the OS snapshot is unknown.
    """
    required = max(0, int(required_bytes))
    memory = system_memory()
    if not memory or int(memory['total_physical_bytes']) <= 0:
        return
    available = memory_headroom_bytes(memory=memory)
    if available is not None and required > available:
        # Cache eviction/worker retirement may have freed memory during the
        # snapshot's 250 ms lifetime. Recheck once before denying work; keep
        # the last known denial if the fresh OS query is unavailable.
        fresh = system_memory(refresh=True)
        refreshed = bool(fresh and int(fresh['total_physical_bytes']) > 0)
        if refreshed:
            memory = fresh
            available = memory_headroom_bytes(memory=memory)
            if required <= available:
                return
        from dlss5tool.i18n import tr
        def size(value):
            return (f'{value/_GIB:.2f} GiB' if value >= _GIB else
                    f'{value/1024**2:.0f} MiB')
        detail = tr('message.ram_headroom_details', required_bytes=required,
            available_bytes=available,
            free_physical_bytes=int(memory['free_physical_bytes']),
            free_commit_bytes=int(memory['free_commit_bytes']),
            reserve_bytes=max(2 * _GIB, int(memory['total_physical_bytes']) // 8),
            refreshed=refreshed)
        raise MemoryError(tr('message.ram_headroom', required=size(required),
                             available=size(available)) + '\n' + detail)


def receive_worker_command(connection, frame_bytes):
    """Keep disposable GPU workers within the reserve while active or idle.

    The caller handles MemoryError by reporting failure and retiring the native
    owner. Stop commands remain possible under pressure. No model is restarted
    automatically and no temporal history or processing quality is changed.
    """
    required = max(1, int(frame_bytes)) * 2
    while not connection.poll(.5):
        require_memory_headroom(required)
    message = connection.recv()
    if message.get('operation') not in ('stop', 'close'):
        require_memory_headroom(required)
    return message
