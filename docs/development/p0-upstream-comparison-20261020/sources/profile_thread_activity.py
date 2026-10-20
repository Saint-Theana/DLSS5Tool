"""Read task-local thread counts/start modules; diagnostics only, no hooks."""
import ctypes as C
import os
from pathlib import Path


def load_counter():
    if os.environ.get('DLSS5TOOL_P0_THREAD_ACTIVITY') != '1':
        return None
    from scripts.verify_p0_stability import checked_path
    task = checked_path(Path(os.environ['TEMP']).parent)
    path = checked_path(task/'native_thread_activity.dll')
    if not (task/'TASK.md').is_file() or not path.is_file():
        raise ValueError('Thread counter must be built inside the registered task')
    library = C.WinDLL(str(path))
    library.thread_activity_read.argtypes = [C.POINTER(C.c_uint64)]
    library.thread_activity_read.restype = None
    return library


def read_counter(library):
    if library is None:
        return None
    values = (C.c_uint64*131)()
    library.thread_activity_read(values)
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.GetModuleHandleExW.argtypes = [C.c_uint32, C.c_void_p, C.POINTER(C.c_void_p)]
    kernel.GetModuleHandleExW.restype = C.c_int
    kernel.GetModuleFileNameW.argtypes = [C.c_void_p, C.c_wchar_p, C.c_uint32]
    kernel.GetModuleFileNameW.restype = C.c_uint32
    groups = []
    for index in range(64):
        address, count = values[3+index*2], values[4+index*2]
        if not address:
            continue
        module = C.c_void_p()
        row = dict(start_address=address, started=count)
        if kernel.GetModuleHandleExW(6, C.c_void_p(address), C.byref(module)):
            path = C.create_unicode_buffer(32768)
            if kernel.GetModuleFileNameW(module, path, len(path)):
                row.update(module=path.value, offset=address-module.value)
        groups.append(row)
    return dict(started=values[0], detached=values[1], unclassified=values[2], groups=groups)
