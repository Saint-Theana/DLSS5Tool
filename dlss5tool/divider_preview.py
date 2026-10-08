"""A lightweight divider line shared by the local and realtime workspaces."""
import ctypes
from ctypes import wintypes as w
import sys
import tkinter as tk


class DividerPreview(tk.Frame):
    """Keep the line in its own composited surface, not in sibling Tk pixels.

    A normal placed child can leave trails across nested Canvas/ttk siblings
    on Windows. Layering retains the underlying content as the line moves;
    it does not force the panels to lay out or recreate their controls.
    """
    def __init__(self, parent, color):
        super().__init__(parent, bg=color, borderwidth=0, highlightthickness=0,
                         cursor='sb_h_double_arrow', takefocus=0)
        self.layered = False
        self.layer_error = None
        self._old_bounds = None
        self.bind('<Configure>', self._restore_underlay)
        self.bind('<Unmap>', self._restore_underlay)
        if sys.platform == 'win32':
            try:
                user = ctypes.WinDLL('user32', use_last_error=True)
                user.GetWindowLongW.argtypes, user.GetWindowLongW.restype = [w.HWND, ctypes.c_int], w.LONG
                user.SetWindowLongW.argtypes, user.SetWindowLongW.restype = [w.HWND, ctypes.c_int, w.LONG], w.LONG
                user.SetLayeredWindowAttributes.argtypes = [w.HWND, w.DWORD, w.BYTE, w.DWORD]
                user.SetLayeredWindowAttributes.restype = w.BOOL
                hwnd = self.winfo_id()
                style = user.GetWindowLongW(hwnd, -20)
                user.SetWindowLongW(hwnd, -20, style | 0x80000)  # WS_EX_LAYERED
                if not user.SetLayeredWindowAttributes(hwnd, 0, 255, 2):  # LWA_ALPHA
                    error = ctypes.WinError(ctypes.get_last_error())
                    user.SetWindowLongW(hwnd, -20, style)
                    raise error
                self.layered = True
            except (OSError, AttributeError) as error:
                self.layer_error = str(error)

    def _restore_underlay(self, event):
        if self.layered:
            return
        # Non-layered platforms/failure fallback: repaint only the old stripe,
        # including nested children, without changing geometry or parameters.
        old = self._old_bounds
        self._old_bounds = ((self.winfo_rootx(), self.winfo_rooty(), self.winfo_width(), self.winfo_height())
                            if event.type == tk.EventType.Configure else None)
        if old is None:
            return
        left, top, width, height = old
        def expose(widget):
            if widget is self or not widget.winfo_ismapped():
                return
            x, y = widget.winfo_rootx(), widget.winfo_rooty()
            x0, y0 = max(left, x), max(top, y)
            x1, y1 = min(left+width, x+widget.winfo_width()), min(top+height, y+widget.winfo_height())
            if x0 < x1 and y0 < y1:
                widget.event_generate('<Expose>', x=x0-x, y=y0-y, width=x1-x0, height=y1-y0)
                for child in widget.winfo_children():
                    expose(child)
        expose(self.master)
