"""Bounded, one-shot source snapshots. No desktop fallback, inference or disk files."""
from dataclasses import dataclass
import io
import multiprocessing
import os
import time

from PIL import Image


class SnapshotError(Exception):
    """A stable, localizable reason; no target title or pixels in diagnostics."""


@dataclass
class Snapshot:
    image: Image.Image
    source_size: tuple


def source_crop(window, frame, client, *, native_frame, style, border=0,
                title_bar=False, uwp_client=None, monitor=None):
    """Physical source bounds, matching Magpie SrcTracker::_CalcSrcRect."""
    if not native_frame:
        if not style & (0x00c00000 | 0x00040000) or title_bar:
            rect = list(window)
        else:
            rect = list(client)
            thickness = min(client[0] - window[0], window[2] - client[2])
            if style & 0x00200000:  # WS_VSCROLL
                rect[0], rect[2] = window[0] + thickness, window[2] - thickness
            if style & 0x00100000:  # WS_HSCROLL
                rect[3] = window[3] - thickness
    else:
        rect = [frame[0]+border, frame[1]+border, frame[2]-border, frame[3]-border]
        if uwp_client and not title_bar:
            rect = list(uwp_client)
            rect[1] = max(rect[1], frame[1]+border)
        elif not title_bar or not style & 0x00c00000:
            rect[1] = max(rect[1], client[1])
    if monitor:
        rect = [max(rect[0], monitor[0]), max(rect[1], monitor[1]),
                min(rect[2], monitor[2]), min(rect[3], monitor[3])]
    if rect[2] <= rect[0] or rect[3] <= rect[1]:
        raise SnapshotError('unavailable')
    return tuple(rect)


def capture_window(selected, title_bar=False):
    """Print only the validated HWND in a disposable process, never screen-grab."""
    if os.name != 'nt':
        raise SnapshotError('unavailable')
    import ctypes as c
    from ctypes import wintypes as w
    user = c.WinDLL('user32', use_last_error=True)
    gdi = c.WinDLL('gdi32', use_last_error=True)
    dwm = c.WinDLL('dwmapi')
    def api(dll, name, result, *args):
        fn = getattr(dll, name); fn.restype = result; fn.argtypes = list(args)
        return fn
    api(user, 'SetThreadDpiAwarenessContext', c.c_void_p, c.c_void_p)(c.c_void_p(-4))
    is_window = api(user, 'IsWindow', w.BOOL, w.HWND)
    pid_of = api(user, 'GetWindowThreadProcessId', w.DWORD, w.HWND, c.POINTER(w.DWORD))
    iconic = api(user, 'IsIconic', w.BOOL, w.HWND)
    visible = api(user, 'IsWindowVisible', w.BOOL, w.HWND)
    window_rect = api(user, 'GetWindowRect', w.BOOL, w.HWND, c.POINTER(w.RECT))
    client_rect = api(user, 'GetClientRect', w.BOOL, w.HWND, c.POINTER(w.RECT))
    to_screen = api(user, 'ClientToScreen', w.BOOL, w.HWND, c.POINTER(w.POINT))
    attr = api(dwm, 'DwmGetWindowAttribute', c.c_long, w.HWND, w.DWORD, c.c_void_p, w.DWORD)
    hwnd, expected_pid = int(selected['hwnd']), int(selected['pid'])
    def identity():
        pid = w.DWORD()
        if not is_window(hwnd) or not pid_of(hwnd, c.byref(pid)) or pid.value != expected_pid:
            raise SnapshotError('missing')
        if iconic(hwnd) or not visible(hwnd):
            raise SnapshotError('minimized')
    identity()
    affinity = w.DWORD()
    if api(user, 'GetWindowDisplayAffinity', w.BOOL, w.HWND, c.POINTER(w.DWORD))(hwnd, c.byref(affinity)) and affinity.value:
        raise SnapshotError('unavailable')
    rect = w.RECT(); frame = w.RECT(); client = w.RECT(); origin = w.POINT()
    if not window_rect(hwnd, c.byref(rect)) or not client_rect(hwnd, c.byref(client)) or not to_screen(hwnd, c.byref(origin)):
        raise SnapshotError('unavailable')
    def coords(r): return (r.left, r.top, r.right, r.bottom)
    window = coords(rect)
    width, height = rect.right-rect.left, rect.bottom-rect.top
    if not 0 < width <= 16384 or not 0 < height <= 16384 or width*height > 40_000_000:
        raise SnapshotError('size')
    if attr(hwnd, 9, c.byref(frame), c.sizeof(frame)) < 0:
        raise SnapshotError('unavailable')
    client_bounds = (origin.x, origin.y, origin.x+client.right, origin.y+client.bottom)
    nc = w.BOOL()
    native = attr(hwnd, 1, c.byref(nc), c.sizeof(nc)) >= 0 and bool(nc.value)
    style = api(user, 'GetWindowLongW', c.c_long, w.HWND, c.c_int)(hwnd, -16) & 0xffffffff
    maximized = bool(api(user, 'IsZoomed', w.BOOL, w.HWND)(hwnd))
    monitor_handle = api(user, 'MonitorFromWindow', w.HANDLE, w.HWND, w.DWORD)(hwnd, 2)
    class MonitorInfo(c.Structure):
        _fields_ = [('cbSize', w.DWORD), ('monitor', w.RECT), ('work', w.RECT), ('flags', w.DWORD)]
    monitor = MonitorInfo(); monitor.cbSize = c.sizeof(monitor)
    if not api(user, 'GetMonitorInfoW', w.BOOL, w.HANDLE, c.POINTER(MonitorInfo))(monitor_handle, c.byref(monitor)):
        raise SnapshotError('unavailable')
    dpi_x, dpi_y = w.UINT(96), w.UINT(96)
    shcore = c.WinDLL('shcore')
    api(shcore, 'GetDpiForMonitor', c.c_long, w.HANDLE, c.c_int, c.POINTER(w.UINT), c.POINTER(w.UINT))(monitor_handle, 0, c.byref(dpi_x), c.byref(dpi_y))
    # Native border thickness is one physical pixel at 96 DPI, rounded.
    import sys
    no_border = window == client_bounds
    win11 = sys.getwindowsversion().build >= 22000
    border = (int(dpi_x.value / 96 + .5) if win11 else 1) if native and not maximized and (not no_border or win11) else 0
    # UWP's embedded content can differ from its top-level client geometry.
    klass = c.create_unicode_buffer(256)
    api(user, 'GetClassNameW', c.c_int, w.HWND, w.LPWSTR, c.c_int)(hwnd, klass, len(klass))
    if klass.value == 'ApplicationFrameWindow':
        raise SnapshotError('unavailable')  # Do not promise incorrectly mapped protection.
    crop = source_crop(window, coords(frame), client_bounds, native_frame=native,
                       style=style, border=border, title_bar=title_bar,
                       monitor=coords(monitor.monitor) if maximized else None)
    crop_local = (crop[0]-window[0], crop[1]-window[1], crop[2]-window[0], crop[3]-window[1])
    if not (0 <= crop_local[0] < crop_local[2] <= width and 0 <= crop_local[1] < crop_local[3] <= height):
        raise SnapshotError('unavailable')
    getdc = api(user, 'GetWindowDC', w.HDC, w.HWND)
    releasedc = api(user, 'ReleaseDC', c.c_int, w.HWND, w.HDC)
    createdc = api(gdi, 'CreateCompatibleDC', w.HDC, w.HDC)
    deletedc = api(gdi, 'DeleteDC', w.BOOL, w.HDC)
    select = api(gdi, 'SelectObject', w.HANDLE, w.HDC, w.HANDLE)
    delete = api(gdi, 'DeleteObject', w.BOOL, w.HANDLE)
    class Header(c.Structure):
        _fields_ = [('size', w.DWORD), ('width', w.LONG), ('height', w.LONG),
                    ('planes', w.WORD), ('bits', w.WORD), ('compression', w.DWORD),
                    ('imageSize', w.DWORD), ('xppm', w.LONG), ('yppm', w.LONG),
                    ('used', w.DWORD), ('important', w.DWORD)]
    class BitmapInfo(c.Structure):
        _fields_ = [('header', Header), ('colors', w.DWORD * 3)]
    info = BitmapInfo(); info.header = Header(c.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    dc = mem = bitmap = old = None
    try:
        dc = getdc(hwnd)
        if not dc: raise SnapshotError('unavailable')
        mem = createdc(dc)
        bits = c.c_void_p()
        bitmap = api(gdi, 'CreateDIBSection', w.HANDLE, w.HDC, c.POINTER(BitmapInfo), w.UINT,
                     c.POINTER(c.c_void_p), w.HANDLE, w.DWORD)(dc, c.byref(info), 0, c.byref(bits), None, 0)
        if not mem or not bitmap or not bits.value: raise SnapshotError('unavailable')
        old = select(mem, bitmap)
        if not old or old == c.c_void_p(-1).value: raise SnapshotError('unavailable')
        # This may block indefinitely; the parent owns timeout/cancellation.
        if not api(user, 'PrintWindow', w.BOOL, w.HWND, w.HDC, w.UINT)(hwnd, mem, 2):
            raise SnapshotError('unavailable')
        identity()
        after = w.RECT()
        if not window_rect(hwnd, c.byref(after)) or coords(after) != window:
            raise SnapshotError('changed')
        image = Image.frombuffer('RGB', (width, height), c.string_at(bits, width*height*4), 'raw', 'BGRX', 0, 1).crop(crop_local)
        size = image.size
        image.thumbnail((1280, 800), Image.Resampling.LANCZOS)
        # Protected/GPU-only windows commonly report success but paint black.
        if all(high <= 2 for low, high in image.getextrema()):
            raise SnapshotError('blank')
        return Snapshot(image, size)
    finally:
        if old and mem: select(mem, old)
        if bitmap: delete(bitmap)
        if mem: deletedc(mem)
        if dc: releasedc(hwnd, dc)


def _worker(connection, selected, title_bar):
    try:
        snapshot = capture_window(selected, title_bar)
        output = io.BytesIO(); snapshot.image.save(output, format='PNG')
        connection.send(('ok', snapshot.source_size, output.getvalue()))
    except SnapshotError as error:
        connection.send(('error', str(error)))
    except Exception:
        connection.send(('error', 'unavailable'))
    finally:
        connection.close()


class SnapshotJob:
    """At most one disposable process. Polling never takes another frame."""
    def __init__(self, selected, title_bar=False, *, timeout=4):
        context = multiprocessing.get_context('spawn')
        self.connection, child = context.Pipe(duplex=False)
        self.process = context.Process(target=_worker, args=(child, dict(selected), title_bar), daemon=True)
        self.deadline = time.monotonic() + timeout
        try:
            self.process.start()
        except Exception:
            self.connection.close()
            raise
        finally:
            child.close()

    def poll(self):
        if self.connection.poll():
            try:
                result = self.connection.recv()
                if result[0] != 'ok': raise SnapshotError(result[1])
                image = Image.open(io.BytesIO(result[2])); image.load()
                return Snapshot(image, tuple(result[1]))
            except (EOFError, OSError) as error:
                raise SnapshotError('unavailable') from error
            finally:
                self.cancel()
        if time.monotonic() >= self.deadline:
            self.cancel(); raise SnapshotError('timeout')
        if not self.process.is_alive():
            self.cancel(); raise SnapshotError('unavailable')
        return None

    def cancel(self):
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=.2)
        self.connection.close()


def fitted_rect(size, width, height):
    """Letterboxed pixel bounds; normalized region coordinates exclude margins."""
    ratio = min(max(1, width)/size[0], max(1, height)/size[1])
    w, h = max(1, round(size[0]*ratio)), max(1, round(size[1]*ratio))
    x, y = (width-w)/2, (height-h)/2
    return x, y, x+w, y+h


def normalized_point(x, y, bounds, *, clamp=False):
    left, top, right, bottom = bounds
    if right <= left or bottom <= top: return None
    if not clamp and not (left <= x <= right and top <= y <= bottom): return None
    return max(0, min(1, (x-left)/(right-left))), max(0, min(1, (y-top)/(bottom-top)))
