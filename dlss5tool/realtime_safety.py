"""Host-external emergency stop; no Tk calls and no dependency on native rendering."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import threading
import time

STOP_TIMEOUT = 2.0
WRITE_TIMEOUT = 3.0


class WindowsStopControl:
    """Created/used on one dedicated thread (RegisterHotKey owns a message queue)."""
    def __init__(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.user.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self.user.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                         wintypes.UINT, wintypes.UINT, wintypes.UINT]
        self.user.ClipCursor.argtypes = [ctypes.POINTER(wintypes.RECT)]
        self.user.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
        self.registered = bool(self.user.RegisterHotKey(None, 1, 0x0002 | 0x0001 | 0x4000, 0x79))

    def pressed(self):
        message = wintypes.MSG()
        pressed = False
        while self.user.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
            pressed |= message.message == 0x312 and message.wParam == 1
        return pressed

    def restore_cursor(self):
        self.user.ClipCursor(None)
        # Same system visibility API as Magpie CursorManager; ShowCursor's
        # per-thread counter cannot repair another process's hidden cursor.
        show = getattr(self.user, 'ShowSystemCursor', None)
        if show:
            show.argtypes = [wintypes.BOOL]
            show.restype = None
            show(True)
        else:
            mag = ctypes.WinDLL('Magnification')
            if mag.MagInitialize():
                mag.MagShowSystemCursor(True)
                mag.MagUninitialize()
        self.user.SystemParametersInfoW(0x57, 0, None, 0)  # SPI_SETCURSORS

    def close(self):
        if self.registered:
            self.user.UnregisterHotKey(None, 1)


class RealtimeSafety:
    """Only ever terminates its bound Popen handle, never a name/PID lookup.

    Silence/static content is NOT a failure. Only an explicit stop/quit or a
    blocked command write arms a deadline. Repeated clicks never extend it.
    """
    def __init__(self, stop, emit, *, platform_factory=None):
        self._stop, self._emit = stop, emit
        self._factory = platform_factory or (WindowsStopControl if os.name == 'nt' else None)
        self._lock = threading.Lock()
        self._done, self._ready = threading.Event(), threading.Event()
        self._process = None
        self._active = False
        self._restore = False
        self._stop_deadline = self._write_deadline = None
        self._quitting = False
        self.registered = False
        self._thread = threading.Thread(target=self._run, name='realtime-safety', daemon=True)

    def start(self):
        self._thread.start()
        if not self._ready.wait(2):
            self._done.set()
            raise RuntimeError('Realtime safety thread did not initialize')

    def bind(self, process):
        with self._lock:
            self._process = process

    def starting(self):
        with self._lock:
            self._active = self._restore = True

    def observe(self, event):
        # State events, unlike queued status snapshots, acknowledge transitions.
        if event.get('event') != 'state':
            return
        with self._lock:
            if event.get('state') == 0:
                self._active = self._restore = False
                if not self._quitting:
                    self._stop_deadline = None
            elif event.get('state') in (1, 2, 3, 4):
                self._active = self._restore = True
                if event.get('state') == 3 and self._stop_deadline is None:
                    self._stop_deadline = time.monotonic() + STOP_TIMEOUT

    def request_stop(self, quitting=False, now=None):
        with self._lock:
            self._quitting |= quitting
            if self._stop_deadline is None:
                self._stop_deadline = (time.monotonic() if now is None else now) + STOP_TIMEOUT

    def writing(self, active, now=None):
        with self._lock:
            self._write_deadline = ((time.monotonic() if now is None else now) + WRITE_TIMEOUT) if active else None

    def check(self, now, platform=None):
        with self._lock:
            process = self._process
            if process is None:
                return
            dead = process.poll() is not None
            deadlines = [d for d in (self._stop_deadline, self._write_deadline) if d is not None]
            deadline = min(deadlines) if deadlines else None
            if not dead and deadline is not None and now >= deadline:
                try:
                    process.terminate()
                    self._emit({'event': 'safety_stop', 'reason': 'stop_timeout' if self._stop_deadline else 'write_timeout'})
                except OSError as error:
                    self._emit({'event': 'safety_error', 'message': str(error)})
                # Keep checking exit and retrying a failed termination, without
                # busy-spinning or restoring the cursor while native still owns it.
                self._stop_deadline = now + STOP_TIMEOUT
                dead = process.poll() is not None
            restore = dead and self._restore
            if dead:
                self._restore = self._active = False
                self._stop_deadline = self._write_deadline = None
        if restore and platform:
            try:
                platform.restore_cursor()
                self._emit({'event': 'cursor_restore', 'ok': True})
            except (OSError, AttributeError) as error:
                self._emit({'event': 'cursor_restore', 'ok': False, 'message': str(error)})

    def _run(self):
        platform = None
        try:
            if self._factory:
                try:
                    platform = self._factory()
                    self.registered = platform.registered
                except OSError:
                    pass
            self._ready.set()
            while not self._done.wait(.05):
                if platform and platform.pressed():
                    with self._lock:
                        active = self._active or self._stop_deadline is not None
                    if active:
                        self.request_stop()
                        self._emit({'event': 'emergency_stop'})
                        self._stop()
                self.check(time.monotonic(), platform)
            self.check(time.monotonic(), platform)
        finally:
            self._ready.set()
            if platform:
                platform.close()

    def close(self):
        self._done.set()
        if self._thread.ident is not None and threading.current_thread() is not self._thread:
            self._thread.join(timeout=1)
