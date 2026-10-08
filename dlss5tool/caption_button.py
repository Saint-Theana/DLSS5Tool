"""A composited caption action, without painting on Windows' non-client DC.

A tiny no-activate owned BUTTON surface sits beside the native caption buttons.
It has no taskbar entry or separate workspace. Windows composes its WM_PAINT
content after uncover/resize. Native callbacks never enter Tcl.
"""
from collections import deque
import ctypes
from ctypes import wintypes as w
import sys
import tkinter as tk
import weakref

from dlss5tool import ui_theme
from dlss5tool.i18n import tr


def caption_action_rect(buttons, client_top, window_width, dpi=96):
    """Window-relative slot immediately left of native caption buttons."""
    left, top, right, bottom = buttons
    scale = max(1, dpi) / 96
    if not (0 < left < right <= window_width and 0 <= top < bottom <= client_top + 2):
        return None
    slot = max(round(32 * scale), min(round(46 * scale), (right - left) // 3))
    gap = max(2, round(4 * scale))
    if left - slot - gap < round(160 * scale):
        return None
    return left - slot - gap, top, left - gap, bottom


def signed_point(lparam):
    return ctypes.c_short(lparam & 0xffff).value, ctypes.c_short((lparam >> 16) & 0xffff).value


def contains(rect, x, y):
    return bool(rect and rect[0] <= x < rect[2] and rect[1] <= y < rect[3])


class _TrackMouse(ctypes.Structure):
    _fields_ = [('size', w.DWORD), ('flags', w.DWORD), ('hwnd', w.HWND), ('hover', w.DWORD)]


class _Paint(ctypes.Structure):
    _fields_ = [('dc', w.HDC), ('erase', w.BOOL), ('rect', w.RECT),
                ('restore', w.BOOL), ('update', w.BOOL), ('reserved', w.BYTE * 32)]


class _DrawItem(ctypes.Structure):
    _fields_ = [('control_type', w.UINT), ('control_id', w.UINT), ('item_id', w.UINT),
                ('action', w.UINT), ('state', w.UINT), ('hwnd', w.HWND),
                ('dc', w.HDC), ('rect', w.RECT), ('data', ctypes.c_size_t)]


# Keep callbacks alive until their native subclass has been removed.
_LIVE = {}


class CaptionModeButton:
    def __init__(self, root, command, ui):
        self.root, self.command, self.ui = root, command, dict(ui)
        self.mode = 'local'
        self.hwnd = self.surface = None
        self.rect = None
        self.hover = self.pressed = self.closed = False
        self._events = deque(maxlen=8)
        self._after = self._tooltip_after = None
        self._tip = None
        self.error = None
        self._callback = None
        self._surface_position = None
        self._surface_visible = False
        if sys.platform == 'win32':
            try:
                self._load_api()
                self._attach()
            except (AttributeError, OSError, tk.TclError) as error:
                self.error = str(error)
        root.bind('<Destroy>', self._destroy, add='+')
        root.bind('<Map>', self._mapped, add='+')
        if self._callback:
            self._after = root.after(60, self._tick)

    @property
    def installed(self):
        return self.hwnd is not None and self.surface is not None

    def _load_api(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.gdi = ctypes.WinDLL('gdi32', use_last_error=True)
        self.dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
        self.comctl = ctypes.WinDLL('comctl32', use_last_error=True)
        ptr, uint, size, result = ctypes.c_void_p, w.UINT, ctypes.c_size_t, ctypes.c_ssize_t
        self._proc_type = ctypes.WINFUNCTYPE(result, w.HWND, uint, size, result, size, size)
        specs = [
            (self.user, 'GetWindowRect', [w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
            (self.user, 'GetClientRect', [w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
            (self.user, 'ClientToScreen', [w.HWND, ctypes.POINTER(w.POINT)], w.BOOL),
            (self.user, 'IsWindowVisible', [w.HWND], w.BOOL),
            (self.user, 'IsWindowEnabled', [w.HWND], w.BOOL),
            (self.user, 'IsIconic', [w.HWND], w.BOOL),
            (self.user, 'GetDpiForWindow', [w.HWND], uint),
            (self.user, 'GetWindowLongW', [w.HWND, ctypes.c_int], w.LONG),
            (self.user, 'CreateWindowExW', [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                                          ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                          w.HWND, w.HMENU, w.HINSTANCE, ptr], w.HWND),
            (self.user, 'DestroyWindow', [w.HWND], w.BOOL),
            (self.user, 'SetWindowPos', [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, uint], w.BOOL),
            (self.user, 'ShowWindow', [w.HWND, ctypes.c_int], w.BOOL),
            (self.user, 'SetWindowTextW', [w.HWND, w.LPCWSTR], w.BOOL),
            (self.user, 'BeginPaint', [w.HWND, ctypes.POINTER(_Paint)], w.HDC),
            (self.user, 'EndPaint', [w.HWND, ctypes.POINTER(_Paint)], w.BOOL),
            (self.user, 'InvalidateRect', [w.HWND, ptr, w.BOOL], w.BOOL),
            (self.user, 'FillRect', [w.HDC, ctypes.POINTER(w.RECT), w.HBRUSH], ctypes.c_int),
            (self.user, 'TrackMouseEvent', [ctypes.POINTER(_TrackMouse)], w.BOOL),
            (self.user, 'SetCapture', [w.HWND], w.HWND),
            (self.user, 'GetCapture', [], w.HWND),
            (self.user, 'ReleaseCapture', [], w.BOOL),
            (self.gdi, 'CreateSolidBrush', [w.DWORD], w.HBRUSH),
            (self.gdi, 'CreatePen', [ctypes.c_int, ctypes.c_int, w.DWORD], ptr),
            (self.gdi, 'SelectObject', [w.HDC, ptr], ptr),
            (self.gdi, 'DeleteObject', [ptr], w.BOOL),
            (self.gdi, 'MoveToEx', [w.HDC, ctypes.c_int, ctypes.c_int, ptr], w.BOOL),
            (self.gdi, 'LineTo', [w.HDC, ctypes.c_int, ctypes.c_int], w.BOOL),
            (self.dwm, 'DwmGetWindowAttribute', [w.HWND, w.DWORD, ptr, w.DWORD], w.LONG),
            (self.comctl, 'SetWindowSubclass', [w.HWND, self._proc_type, size, size], w.BOOL),
            (self.comctl, 'RemoveWindowSubclass', [w.HWND, self._proc_type, size], w.BOOL),
            (self.comctl, 'DefSubclassProc', [w.HWND, uint, size, result], result),
        ]
        for dll, name, args, returns in specs:
            function = getattr(dll, name)
            function.argtypes, function.restype = args, returns
        # A bound ctypes callback creates a cycle that can release Tk objects
        # during worker-thread GC. Keep only a weak owner inside the callback.
        owner = weakref.ref(self)
        default_proc = self.comctl.DefSubclassProc
        def dispatch(hwnd, message, wp, lp, ident, data):
            instance = owner()
            if instance is None:
                return default_proc(hwnd, message, wp, lp)
            return instance._wndproc(hwnd, message, wp, lp, ident, data)
        self._callback = self._proc_type(dispatch)

    def _attach(self):
        hwnd = ui_theme._window_hwnd(self.root)
        if not hwnd:
            return
        if not self.comctl.SetWindowSubclass(hwnd, self._callback, id(self), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = hwnd
        _LIVE[hwnd, id(self)] = self
        # TOOLWINDOW | NOACTIVATE, owned WS_POPUP: no taskbar/Alt-Tab entry,
        # never topmost, no activation or changes to the owner's native frame.
        # BS_OWNERDRAW prevents the standard BUTTON renderer from painting
        # the accessible label during synchronous WM_SETTEXT/theme updates.
        surface = self.user.CreateWindowExW(0x08000080, 'BUTTON', self._label(), 0x8000000B,
                                            0, 0, 1, 1, hwnd, None, None, None)
        if not surface:
            error = ctypes.WinError(ctypes.get_last_error())
            self._detach_owner()
            raise error
        self.surface = surface
        if not self.comctl.SetWindowSubclass(surface, self._callback, id(self), 0):
            error = ctypes.WinError(ctypes.get_last_error())
            self.user.DestroyWindow(surface)
            self.surface = None
            self._detach_owner()
            raise error
        _LIVE[surface, id(self)] = self
        self._surface_position = None
        self._sync_surface()

    def _detach_owner(self):
        if self.hwnd and self.comctl.RemoveWindowSubclass(self.hwnd, self._callback, id(self)):
            _LIVE.pop((self.hwnd, id(self)), None)
            self.hwnd = None

    def _mapped(self, event):
        # Tk recreates its wrapper HWND on fullscreen transitions.
        if event.widget is self.root and not self.closed and self._callback and not self.hwnd:
            try:
                self._attach()
            except OSError as error:
                self.error = str(error)

    def _bounds(self):
        if not self.hwnd or not self.user.IsWindowVisible(self.hwnd) or self.user.IsIconic(self.hwnd):
            return None
        if not self.user.IsWindowEnabled(self.hwnd):
            return None
        if self.user.GetWindowLongW(self.hwnd, -16) & 0x00C00000 != 0x00C00000:
            return None  # Fullscreen: never cover the image.
        outer, buttons, origin = w.RECT(), w.RECT(), w.POINT()
        if not self.user.GetWindowRect(self.hwnd, ctypes.byref(outer)):
            return None
        if not self.user.ClientToScreen(self.hwnd, ctypes.byref(origin)):
            return None
        if self.dwm.DwmGetWindowAttribute(self.hwnd, 5, ctypes.byref(buttons), ctypes.sizeof(buttons)) != 0:
            return None
        self._screen_origin = (outer.left, outer.top)
        return caption_action_rect((buttons.left, buttons.top, buttons.right, buttons.bottom),
                                   origin.y - outer.top, outer.right - outer.left,
                                   self.user.GetDpiForWindow(self.hwnd) or 96)

    def _sync_surface(self):
        self.rect = None if self.closed else self._bounds()
        if not self.surface:
            return
        if not self.rect:
            if self._surface_visible:
                self.user.ShowWindow(self.surface, 0)
                self._surface_visible = False
                self.hover = self.pressed = False
                self._events.append('leave')
            return
        x, y = self._screen_origin
        left, top, right, bottom = self.rect
        position = (x+left, y+top, right-left, bottom-top)
        if position != self._surface_position or not self._surface_visible:
            # NOACTIVATE | NOZORDER | NOOWNERZORDER | SHOWWINDOW. No global lift.
            if not self.user.SetWindowPos(self.surface, None, *position, 0x0254):
                raise ctypes.WinError(ctypes.get_last_error())
            self._surface_position = position
            self._surface_visible = True
            self._invalidate()

    def _invalidate(self):
        if self.surface:
            self.user.InvalidateRect(self.surface, None, False)

    def _draw(self, dc, rect):
        """Paint only the button's client surface, also used by WM_PRINTCLIENT."""
        brush = pen = previous = None
        try:
            bg = self.ui['hover'] if self.hover or self.pressed else self.ui['bg']
            brush = self.gdi.CreateSolidBrush(ui_theme._colorref(bg))
            if not brush or not self.user.FillRect(dc, ctypes.byref(rect), brush):
                raise ctypes.WinError(ctypes.get_last_error())
            color = self.ui['accent'] if self.mode == 'realtime' else self.ui['text']
            scale = (self.user.GetDpiForWindow(self.hwnd) or 96) / 96
            pen = self.gdi.CreatePen(0, max(1, round(1.5*scale)), ui_theme._colorref(color))
            if not pen:
                raise ctypes.WinError(ctypes.get_last_error())
            previous = self.gdi.SelectObject(dc, pen)
            cx, cy = (rect.left+rect.right)//2, (rect.top+rect.bottom)//2
            s = max(1, round(3*scale))
            # Complete arrowheads, independent of fonts or icon glyph support.
            for points in (((cx-2*s, cy-s), (cx+2*s, cy-s)),
                           ((cx+s, cy-2*s), (cx+2*s, cy-s), (cx+s, cy)),
                           ((cx+2*s, cy+s), (cx-2*s, cy+s)),
                           ((cx-s, cy), (cx-2*s, cy+s), (cx-s, cy+2*s))):
                self.gdi.MoveToEx(dc, *points[0], None)
                for point in points[1:]:
                    if not self.gdi.LineTo(dc, *point):
                        raise ctypes.WinError(ctypes.get_last_error())
            if self.mode == 'realtime':
                self.gdi.MoveToEx(dc, cx-2*s, rect.bottom-max(3, round(3*scale)), None)
                self.gdi.LineTo(dc, cx+2*s, rect.bottom-max(3, round(3*scale)))
        finally:
            if previous:
                self.gdi.SelectObject(dc, previous)
            if pen:
                self.gdi.DeleteObject(pen)
            if brush:
                self.gdi.DeleteObject(brush)

    def _inside_surface(self, lp):
        rect = w.RECT()
        return (self.user.GetClientRect(self.surface, ctypes.byref(rect))
                and contains((0, 0, rect.right, rect.bottom), *signed_point(lp)))

    def _surface_message(self, hwnd, message, wp, lp):
        if message in (0xF, 0x318):  # WM_PAINT / WM_PRINTCLIENT
            paint, rect = _Paint(), w.RECT()
            dc = self.user.BeginPaint(hwnd, ctypes.byref(paint)) if message == 0xF else wp
            try:
                if dc and self.user.GetClientRect(hwnd, ctypes.byref(rect)):
                    self._draw(dc, rect)
            finally:
                if message == 0xF:
                    self.user.EndPaint(hwnd, ctypes.byref(paint))
            return 0
        if message == 0x14:  # WM_ERASEBKGND: the full background is in _draw.
            return 1
        if message == 0x21:  # WM_MOUSEACTIVATE: leave focus on the main window.
            return 3  # MA_NOACTIVATE
        if message == 0x200:  # WM_MOUSEMOVE
            hover = bool(self._inside_surface(lp))
            if hover != self.hover:
                self.hover = hover
                self._events.append('hover' if hover else 'leave')
                self._invalidate()
            track = _TrackMouse(ctypes.sizeof(_TrackMouse), 2, hwnd, 0)
            self.user.TrackMouseEvent(ctypes.byref(track))
            return 0
        if message in (0x2A3, 0x215, 0x1F):  # LEAVE / CAPTURECHANGED / CANCELMODE
            self.hover = False
            if message != 0x2A3:
                self.pressed = False
            self._events.append('leave')
            self._invalidate()
            return 0
        if message in (0x201, 0x203):  # L down / double click
            self.pressed = bool(self._inside_surface(lp))
            if self.pressed:
                self.user.SetCapture(hwnd)
            self._events.append('leave')
            self._invalidate()
            return 0
        if message == 0x202:  # L up: exactly one queued toggle on a valid release.
            clicked = self.pressed and self._inside_surface(lp)
            self.pressed = False
            if self.user.GetCapture() == hwnd:
                self.user.ReleaseCapture()
            if clicked:
                self._events.append('click')
            self._invalidate()
            return 0
        if message == 0xF5:  # BM_CLICK, standard button accessibility invocation.
            self._events.append('click')
            return 0
        return None

    def _wndproc(self, hwnd, message, wp, lp, _id, _data):
        result = None
        try:
            if not self.closed and hwnd == self.hwnd and message == 0x2B and lp:  # WM_DRAWITEM
                item = ctypes.cast(lp, ctypes.POINTER(_DrawItem)).contents
                if item.control_type == 4 and item.hwnd == self.surface:  # ODT_BUTTON
                    self._draw(item.dc, item.rect)
                    return 1
            if message == 0x82:  # WM_NCDESTROY
                self.comctl.RemoveWindowSubclass(hwnd, self._callback, id(self))
                _LIVE.pop((hwnd, id(self)), None)
                if hwnd == self.surface:
                    self.surface = None
                    self._surface_visible = False
                    self._surface_position = None
                elif hwnd == self.hwnd:
                    if self.surface:
                        self.user.DestroyWindow(self.surface)
                    self.hwnd = None
            elif not self.closed and hwnd == self.surface:
                handled = self._surface_message(hwnd, message, wp, lp)
                if handled is not None:
                    return handled
            result = self.comctl.DefSubclassProc(hwnd, message, wp, lp)
            # No owner hit-test or paint interception: native drag, snap,
            # resize and all three caption controls remain Windows-owned.
            if not self.closed and hwnd == self.hwnd and message in (0x47, 0x18, 0xA, 0x6, 0x2E0):
                self._sync_surface()
            return result
        except Exception as error:
            self.error = str(error)
            return result if result is not None else self.comctl.DefSubclassProc(hwnd, message, wp, lp)

    def _dispatch_events(self):
        while self._events and not self.closed:
            kind = self._events.popleft()
            self._hide_tip()
            if kind == 'click':
                self.command()
            elif kind == 'hover':
                self._tooltip_after = self.root.after(600, self._show_tip)

    def _tick(self):
        self._after = None
        if self.closed:
            return
        try:
            if not self.hwnd and self._callback:
                self._attach()
            self._sync_surface()
            self._dispatch_events()
        except (OSError, tk.TclError) as error:
            self.error = str(error)
        if not self.closed:
            self._after = self.root.after(60, self._tick)

    def _label(self):
        target = tr('workbench.mode.realtime' if self.mode == 'local' else 'workbench.mode.local')
        return tr('workbench.switch_to', mode=target)

    def _show_tip(self):
        self._tooltip_after = None
        if not self.hover or self.closed or not self.rect:
            return
        tip = self._tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        x, y = self._screen_origin
        tx, ty = x+self.rect[2]-240, y+self.rect[3]+4
        # '+-N' is an absolute negative Tk position, not right-edge anchoring.
        tip.geometry(f'+{tx}+{ty}')
        current = tr('workbench.mode.' + self.mode)
        target = tr('workbench.mode.realtime' if self.mode == 'local' else 'workbench.mode.local')
        tk.Label(tip, text=tr('workbench.switch_hint', current=current, target=target), bg=self.ui['panel'],
                 fg=self.ui['text'], padx=10, pady=6).pack()

    def _hide_tip(self):
        if self._tooltip_after:
            self.root.after_cancel(self._tooltip_after)
            self._tooltip_after = None
        if self._tip:
            self._tip.destroy()
            self._tip = None

    def set_mode(self, mode):
        self.mode = mode
        self._hide_tip()
        if self.surface:
            self.user.SetWindowTextW(self.surface, self._label())
        self._invalidate()

    def apply_theme(self, ui):
        self._hide_tip()
        self.ui = dict(ui)
        self._invalidate()

    def _destroy(self, event):
        if event.widget is self.root:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.command = None
        self._events.clear()
        self._hide_tip()
        if self._after:
            self.root.after_cancel(self._after)
            self._after = None
        if self.surface:
            self.user.DestroyWindow(self.surface)
        self._detach_owner()
