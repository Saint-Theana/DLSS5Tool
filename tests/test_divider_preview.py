"""Targeted divider behavior/pixels; no full App, media or native enhancement."""
import ctypes
from ctypes import wintypes as w
import sys
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest import mock

from dlss5tool import gui, ui_theme
from dlss5tool.divider_preview import DividerPreview


class LocalDividerTests(unittest.TestCase):
    def setUp(self):
        ui_theme.enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.geometry('1000x600+80+80')
        ui_theme.apply_ttk(self.root, ui_theme.tokens('dark'))
        self.app = app = gui.App.__new__(gui.App)
        app.root = self.root
        self.root._studio_scale = 1.0
        app._studio = ttk.Frame(self.root)
        app._studio.pack(fill='both', expand=True)
        app._inspector_width = 360
        app._inspector_drag = app._inspector_pending_width = None
        app._inspector = ttk.Frame(app._studio, width=360)
        app._inspector.pack(side='right', fill='y')
        app._inspector.pack_propagate(False)
        app._inspector_grip = tk.Frame(app._inspector, width=4, bg='#718293', takefocus=1)
        app._inspector_grip.pack(side='left', fill='y')
        self.left = tk.Canvas(app._studio, bg='#172535', highlightthickness=0)
        self.left.pack(side='left', fill='both', expand=True)
        app._inspector_preview = DividerPreview(app._studio, '#7fe8e8')
        app._schedule_settings_save = mock.Mock()
        app._inspector_grip.bind('<Unmap>', app._cancel_inspector_grip)
        app._studio.bind('<Configure>', app._cancel_inspector_grip)
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_local_drag_previews_then_saves_final_release_once(self):
        app = self.app
        app._on_inspector_grip_start(SimpleNamespace(x_root=600))
        for x in (580, 560, 540):
            app._on_inspector_grip_drag(SimpleNamespace(x_root=x))
            self.root.update_idletasks()
            self.assertEqual(app._inspector_width, 360)
            self.assertEqual(app._inspector.winfo_width(), 360)
            self.assertEqual(app._inspector_preview.winfo_x(), 1000-(360+600-x))
        app._schedule_settings_save.assert_not_called()
        app._on_inspector_grip_end(SimpleNamespace(x_root=520))
        app._on_inspector_grip_end(SimpleNamespace(x_root=500))
        self.root.update()
        self.assertEqual(app._inspector_width, 440)
        self.assertEqual(app._inspector.winfo_width(), 440)
        app._schedule_settings_save.assert_called_once_with()
        self.assertFalse(app._inspector_preview.winfo_ismapped())

    def test_local_limits_cancel_hide_and_click_do_not_save(self):
        app = self.app
        for x, expected in ((-10000, ui_theme.INSPECTOR_MAX), (10000, ui_theme.INSPECTOR_MIN)):
            app._on_inspector_grip_start(SimpleNamespace(x_root=600))
            app._on_inspector_grip_drag(SimpleNamespace(x_root=x))
            self.assertEqual(app._inspector_pending_width, expected)
            app._cancel_inspector_grip()
            app._on_inspector_grip_end(SimpleNamespace(x_root=x))
            self.assertEqual(app._inspector_width, 360)
        app._on_inspector_grip_start(SimpleNamespace(x_root=600))
        app._on_inspector_grip_end(SimpleNamespace(x_root=600))
        app._schedule_settings_save.assert_not_called()
        app._on_inspector_grip_start(SimpleNamespace(x_root=600))
        app._on_inspector_grip_drag(SimpleNamespace(x_root=560))
        self.root.update()
        app._studio.pack_forget()
        self.root.update()
        self.assertIsNone(app._inspector_drag)
        self.assertFalse(app._inspector_preview.winfo_manager())
        app._schedule_settings_save.assert_not_called()

    def test_local_scaled_pointer_delta(self):
        self.root._studio_scale = 1.5
        app = self.app
        app._inspector.configure(width=540)
        self.root.update()
        app._on_inspector_grip_start(SimpleNamespace(x_root=600))
        app._on_inspector_grip_drag(SimpleNamespace(x_root=540))
        self.assertEqual(app._inspector_pending_width, 400)
        app._on_inspector_grip_end(SimpleNamespace(x_root=540))
        self.root.update()
        self.assertEqual(app._inspector.winfo_width(), 600)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows compositing regression')
    def test_preview_pixels_restore_old_columns_and_do_not_take_focus(self):
        self.check_preview_pixels(layered=True)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows repaint fallback regression')
    def test_nonlayered_fallback_restores_pixels(self):
        self.check_preview_pixels(layered=False)

    def check_preview_pixels(self, *, layered):
        # Read only pixels inside this owned test window, without WM_PRINT,
        # which would repaint and conceal the stale-pixel regression.
        user = ctypes.WinDLL('user32', use_last_error=True)
        gdi = ctypes.WinDLL('gdi32', use_last_error=True)
        dwm = ctypes.WinDLL('dwmapi')
        user.GetDC.argtypes, user.GetDC.restype = [w.HWND], w.HDC
        user.ReleaseDC.argtypes, user.ReleaseDC.restype = [w.HWND, w.HDC], ctypes.c_int
        gdi.GetPixel.argtypes, gdi.GetPixel.restype = [w.HDC, ctypes.c_int, ctypes.c_int], w.DWORD
        user.GetAncestor.argtypes, user.GetAncestor.restype = [w.HWND, w.UINT], w.HWND
        user.WindowFromPoint.argtypes, user.WindowFromPoint.restype = [w.POINT], w.HWND
        hwnd = user.GetAncestor(self.root.winfo_id(), 2)
        self.root.attributes('-topmost', True)
        self.root.lift()
        self.root.focus_force()
        self.root.update()
        preview = self.app._inspector_preview
        self.assertTrue(preview.layered, preview.layer_error)
        if not layered:
            user.GetWindowLongW.argtypes, user.GetWindowLongW.restype = [w.HWND, ctypes.c_int], w.LONG
            user.SetWindowLongW.argtypes, user.SetWindowLongW.restype = [w.HWND, ctypes.c_int, w.LONG], w.LONG
            handle = preview.winfo_id()
            user.SetWindowLongW(handle, -20, user.GetWindowLongW(handle, -20) & ~0x80000)
            preview.layered = False
        # Include native nested siblings under the moving stripe, as in the
        # user's screenshot (Canvas, ttk containers, labels and buttons).
        panel = ttk.Frame(self.left)
        self.left.create_window(0, 140, window=panel, anchor='nw', width=630, height=80)
        ttk.Label(panel, text='Owned pixel fixture').pack(fill='x')
        ttk.Button(panel, text='Test control').pack(fill='x')
        for theme in ('dark', 'light'):
            ui_theme.apply_ttk(self.root, ui_theme.tokens(theme))
            self.left.configure(bg=ui_theme.tokens(theme)['canvas'])
            preview.configure(bg='#ff00ff')
            self.root.update()
            dwm.DwmFlush()
            focus = str(self.root.tk.call('focus'))
            positions = (100, 150, 200, 250, 300)
            def pixels():
                ox, oy = self.app._studio.winfo_rootx(), self.app._studio.winfo_rooty()
                points = {(x, y): w.POINT(ox+x+1, oy+y)
                          for x in positions for y in (100, 150, 180, 230, 400)}
                for point in points.values():
                    self.assertEqual(user.GetAncestor(user.WindowFromPoint(point), 2), hwnd,
                                     'Never read a pixel covered by another app')
                dc = user.GetDC(None)
                try:
                    return {key: gdi.GetPixel(dc, point.x, point.y) for key, point in points.items()}
                finally:
                    user.ReleaseDC(None, dc)
            baseline = pixels()
            for x in positions:
                preview.place(x=x, y=0, width=3, height=580)
                preview.lift()
                self.root.update()
                dwm.DwmFlush()
                painted = pixels()
                self.assertEqual(painted[x, 100], 0xff00ff, 'Preview must actually be visible')
                for position, color in painted.items():
                    if position[0] != x:
                        self.assertEqual(color, baseline[position], (theme, x, position, 'stale stripe'))
                self.assertEqual(str(self.root.tk.call('focus')), focus)
            preview.place_forget()
            self.root.update()
            dwm.DwmFlush()
            self.assertEqual(pixels(), baseline, 'Cancel/release must erase every preview pixel')


if __name__ == '__main__':
    unittest.main()
