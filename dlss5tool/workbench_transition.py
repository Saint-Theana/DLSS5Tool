"""Persistent status-bar mode badge with a brief, local color highlight."""
import ctypes
import sys
import time
import tkinter as tk
from tkinter import font as tkfont

from dlss5tool import ui_theme
from dlss5tool.ui_widgets import round_rect


def animations_enabled():
    if sys.platform != 'win32':
        return True
    try:
        enabled = ctypes.c_int(1)
        api = ctypes.windll.user32.SystemParametersInfoW
        api.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        api.restype = ctypes.c_int
        return bool(enabled.value) if api(0x1042, 0, ctypes.byref(enabled), 0) else True
    except (AttributeError, OSError):
        return True


class WorkbenchTransition:
    NOTICE_MS = 700

    def __init__(self, host, ui, title, titles):
        self.host = host
        # Older UI probes inspect these fields. There are no overlay widgets.
        self.cover = self.notice = None
        self._after = None
        self._generation = 0
        self._pending = None
        self._started = 0
        self.title = title
        self._ui = dict(ui)
        self._strength = 0.
        font = tkfont.nametofont(ui_theme.UI_FONT_SMALL, root=host)
        self._width = max(font.measure(label) for label in titles) + ui_theme.scale_px(host, 20)
        self._height = max(ui_theme.scale_px(host, 24), font.metrics('linespace') + ui_theme.scale_px(host, 6))
        self.badge = tk.Canvas(
            host, width=self._width, height=self._height, bg=ui['surface'],
            borderwidth=0, highlightthickness=0, takefocus=0)
        self.badge.pack(side='left', padx=(ui_theme.scale_px(host, 10), 0), pady=2)
        self._draw()
        self.host.bind('<Destroy>', self._destroy, add='+')

    def apply_theme(self, ui):
        self._ui = dict(ui)
        self.badge.configure(bg=ui['surface'])
        self._draw()

    def _draw(self):
        self.badge.delete('all')
        self.badge._chrome_live = []
        round_rect(self.badge, 1, 1, self._width-1, self._height-1,
                   ui_theme.scale_px(self.host, 6), fill=self._ui['select_bg'])
        self._text = self.badge.create_text(
            self._width/2, self._height/2, text=self.title,
            font=ui_theme.UI_FONT_SMALL, fill=self._ui['muted'])
        self._paint()

    def _paint(self):
        channels = []
        for offset in (1, 3, 5):
            start = int(self._ui['muted'][offset:offset+2], 16)
            end = int(self._ui['accent'][offset:offset+2], 16)
            channels.append(round(start + (end-start)*self._strength))
        color = '#{:02x}{:02x}{:02x}'.format(*channels)
        try:
            self.badge.itemconfigure(self._text, fill=color)
        except tk.TclError:
            pass  # The host's Destroy event arrives after its children.

    def begin(self, ui, title, direction=1):
        self.cancel()
        # Commit the label only after the new workbench opens successfully.
        self._pending = (dict(ui), title)

    def reveal(self, *, highlight=True):
        if self._pending is None:
            return
        ui, self.title = self._pending
        self._pending = None
        self.apply_theme(ui)
        if not highlight or not self.host.winfo_ismapped():
            return
        self._strength = 1.
        self._paint()
        self._started = time.monotonic()
        generation = self._generation
        if animations_enabled():
            self._schedule(generation)
        else:
            # Reduced motion gets one static highlight, then the resting color.
            self._after = self.host.after(self.NOTICE_MS, lambda: self._finish(generation))

    def _schedule(self, generation):
        self._after = self.host.after(16, lambda: self._notice_step(generation))

    def _notice_step(self, generation=None):
        if generation is not None and generation != self._generation:
            return
        self._after = None
        progress = min(1., max(0., (time.monotonic()-self._started)*1000/self.NOTICE_MS))
        if progress >= 1 or not self.host.winfo_ismapped():
            self._finish(self._generation)
            return
        # Readable throughout: hold briefly, then ease to the muted resting text.
        self._strength = (1 - max(0., (progress-.2)/.8))**2
        self._paint()
        self._schedule(self._generation)

    def _finish(self, generation):
        if generation != self._generation:
            return
        self._after = None
        self._strength = 0.
        self._paint()

    def cancel(self):
        self._generation += 1
        if self._after is not None:
            self.host.after_cancel(self._after)
            self._after = None
        self._pending = None
        self._strength = 0.
        self._paint()

    def _destroy(self, event):
        if event.widget is self.host:
            self.cancel()
