"""Geometry and real HWND lifecycle; no clicks/capture of external windows."""
import ctypes
from ctypes import wintypes as w
import sys
import tkinter as tk
import unittest
from unittest import mock

from dlss5tool import ui_theme
from dlss5tool.caption_button import CaptionModeButton, caption_action_rect, contains, signed_point, _LIVE


class CaptionGeometryTests(unittest.TestCase):
    def test_slot_keeps_native_buttons_and_client_area_clear(self):
        rect = caption_action_rect((862, 0, 1000, 30), 31, 1000)
        self.assertEqual(rect, (812, 0, 858, 30))
        self.assertFalse(contains(rect, 870, 15))
        self.assertFalse(contains(rect, 820, 31))
        self.assertTrue(contains(rect, 835, 15))

    def test_invalid_hidden_fullscreen_or_tiny_frames_have_no_slot(self):
        for bounds, top in (((0, 0, 0, 0), 31), ((862, 0, 1000, 30), 0), ((100, 0, 238, 30), 31)):
            self.assertIsNone(caption_action_rect(bounds, top, 1000))

    def test_dpi_and_negative_monitor_coordinates(self):
        rect = caption_action_rect((1293, 0, 1500, 45), 47, 1500, 144)
        self.assertEqual(rect, (1218, 0, 1287, 45))
        lp = ((-120 & 0xffff) << 16) | (-1920 & 0xffff)
        self.assertEqual(signed_point(lp), (-1920, -120))


@unittest.skipUnless(sys.platform == 'win32', 'Windows caption only')
class CaptionNativeTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry('1000x600+0+0')
        self.root.update()
        self.original_style = ui_theme._user32().GetWindowLongW(ui_theme._window_hwnd(self.root), -16)
        self.command = mock.Mock()
        self.button = CaptionModeButton(self.root, self.command, ui_theme.tokens('light'))
        self.root.update()

    def tearDown(self):
        self.button.close()
        self.root.destroy()

    def test_real_subclass_rect_theme_and_teardown(self):
        button = self.button
        self.assertTrue(button.installed, button.error)
        self.assertIsNotNone(button._bounds())
        hwnd = button.hwnd
        surface = button.surface
        self.assertIn((hwnd, id(button)), _LIVE)
        self.assertIn((surface, id(button)), _LIVE)
        self.assertEqual(button.user.GetWindowLongW(hwnd, -16), self.original_style)
        style = button.user.GetWindowLongW(surface, -20)
        self.assertTrue(style & 0x08000000)  # NOACTIVATE
        self.assertTrue(style & 0x80)  # TOOLWINDOW: no taskbar entry
        self.assertFalse(style & 0x40000)  # APPWINDOW
        self.assertFalse(style & 0x8)  # TOPMOST
        get_window = button.user.GetWindow
        get_window.argtypes, get_window.restype = [w.HWND, w.UINT], w.HWND
        self.assertEqual(get_window(surface, 4), hwnd)  # GW_OWNER
        button.set_mode('realtime')
        button.apply_theme(ui_theme.tokens('dark'))
        self.root.update()
        self.assertIsNone(button.error)
        button.close()
        self.assertNotIn((hwnd, id(button)), _LIVE)
        self.assertNotIn((surface, id(button)), _LIVE)
        self.assertIsNone(button.surface)
        self.assertIsNone(button._after)

    def test_maximized_minimized_and_fullscreen_bounds(self):
        self.root.state('zoomed')
        self.root.update()
        self.assertIsNotNone(self.button._bounds())
        self.assertTrue(self.button.user.IsWindowVisible(self.button.surface))
        self.root.iconify()
        self.root.update()
        self.assertIsNone(self.button._bounds())
        self.assertFalse(self.button.user.IsWindowVisible(self.button.surface))
        self.root.deiconify()
        self.root.state('normal')
        self.root.attributes('-fullscreen', True)
        self.root.update()
        self.assertIsNone(self.button._bounds())
        self.assertFalse(self.button.user.IsWindowVisible(self.button.surface))
        self.root.attributes('-fullscreen', False)
        self.root.update()
        from ctypes import wintypes as w
        bounds, origin = w.RECT(), w.POINT()
        self.button.dwm.DwmGetWindowAttribute(self.button.hwnd, 5, ctypes.byref(bounds), ctypes.sizeof(bounds))
        self.button.user.ClientToScreen(self.button.hwnd, ctypes.byref(origin))
        self.assertIsNotNone(self.button._bounds(),
                             (self.button.hwnd, ui_theme._window_hwnd(self.root),
                              self.button.user.GetWindowLongW(self.button.hwnd, -16),
                              tuple(getattr(bounds, k) for k in ('left', 'top', 'right', 'bottom')),
                              (origin.x, origin.y), self.root.state()))

    def test_single_client_click_is_queued_once_then_dispatched(self):
        button = self.button
        lp = (12 << 16) | 20
        button._wndproc(button.surface, 0x201, 1, lp, 0, 0)
        button._wndproc(button.surface, 0x202, 0, lp, 0, 0)
        self.command.assert_not_called()  # No Tcl/user callback in native WndProc.
        self.assertEqual(list(button._events).count('click'), 1)
        button._dispatch_events()
        self.command.assert_called_once_with()

    def test_drag_release_outside_does_not_switch(self):
        button = self.button
        button._wndproc(button.surface, 0x201, 1, (12 << 16) | 20, 0, 0)
        button._wndproc(button.surface, 0x202, 0, (12 << 16) | 500, 0, 0)
        button._dispatch_events()
        self.command.assert_not_called()

    def test_position_follows_owner_and_hides_on_withdraw(self):
        button = self.button
        self.root.geometry('900x600+50+40')
        self.root.update()
        actual = w.RECT()
        button.user.GetWindowRect(button.surface, ctypes.byref(actual))
        left, top, right, bottom = button._bounds()
        x, y = button._screen_origin
        self.assertEqual((actual.left, actual.top, actual.right, actual.bottom),
                         (x+left, y+top, x+right, y+bottom))
        self.root.withdraw()
        self.root.update()
        self.assertFalse(button.user.IsWindowVisible(button.surface))
        self.root.deiconify()
        self.root.update()
        self.assertTrue(button.user.IsWindowVisible(button.surface))

    def test_wm_paint_is_delivered_and_offscreen_icon_pixels_are_not_blank(self):
        # Render our own WM_PRINTCLIENT output into an in-memory DIB. This is
        # not a desktop screenshot and does not inspect any other window.
        button = self.button
        with mock.patch.object(button, '_draw', wraps=button._draw) as draw:
            button._invalidate()
            self.root.update()
            self.assertTrue(draw.called)
        rect = w.RECT()
        button.user.GetClientRect(button.surface, ctypes.byref(rect))
        width, height = rect.right, rect.bottom
        class Header(ctypes.Structure):
            _fields_ = [('size', w.DWORD), ('width', w.LONG), ('height', w.LONG),
                        ('planes', w.WORD), ('bits', w.WORD), ('compression', w.DWORD),
                        ('image_size', w.DWORD), ('xppm', w.LONG), ('yppm', w.LONG),
                        ('used', w.DWORD), ('important', w.DWORD)]
        header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        gdi = button.gdi
        gdi.CreateCompatibleDC.argtypes, gdi.CreateCompatibleDC.restype = [w.HDC], w.HDC
        gdi.DeleteDC.argtypes, gdi.DeleteDC.restype = [w.HDC], w.BOOL
        gdi.CreateDIBSection.argtypes = [w.HDC, ctypes.c_void_p, w.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD]
        gdi.CreateDIBSection.restype = w.HBITMAP
        gdi.GdiFlush.argtypes, gdi.GdiFlush.restype = [], w.BOOL
        send = button.user.SendMessageW
        send.argtypes, send.restype = [w.HWND, w.UINT, ctypes.c_size_t, ctypes.c_ssize_t], ctypes.c_ssize_t
        dc = gdi.CreateCompatibleDC(None)
        bits = ctypes.c_void_p()
        bitmap = gdi.CreateDIBSection(dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
        self.assertTrue(dc and bitmap and bits.value)
        previous = gdi.SelectObject(dc, bitmap)
        try:
            for theme in ('light', 'dark'):
                button.apply_theme(ui_theme.tokens(theme))
                for mode in ('local', 'realtime'):
                    button.set_mode(mode)
                    for hover in (False, True):
                        button.hover = hover
                        send(button.surface, 0x318, dc, 4)  # WM_PRINTCLIENT / PRF_CLIENT
                        gdi.GdiFlush()
                        pixels = [pixel & 0xffffff for pixel in
                                  (w.DWORD * (width*height)).from_address(bits.value)]
                        foreground = int(button.ui['accent' if mode == 'realtime' else 'text'][1:], 16)
                        background = int(button.ui['hover' if hover else 'bg'][1:], 16)
                        self.assertGreater(pixels.count(foreground), 20, (theme, mode, hover))
                        self.assertEqual(pixels[0], background)
                        self.assertEqual(pixels[-1], background)
                        self.assertIsNone(button.error)
        finally:
            gdi.SelectObject(dc, previous)
            gdi.DeleteObject(bitmap)
            gdi.DeleteDC(dc)

    def test_disabled_owner_hides_button_without_changing_native_style(self):
        button = self.button
        enable = button.user.EnableWindow
        enable.argtypes, enable.restype = [w.HWND, w.BOOL], w.BOOL
        try:
            enable(button.hwnd, False)
            self.root.update()
            self.assertFalse(button.user.IsWindowVisible(button.surface))
        finally:
            enable(button.hwnd, True)
        self.root.update()
        self.assertTrue(button.user.IsWindowVisible(button.surface))
        self.assertEqual(button.user.GetWindowLongW(button.hwnd, -16), self.original_style)

    def test_mode_text_update_keeps_icon_before_next_paint(self):
        # Read only our button's pixels immediately after WM_SETTEXT. A later
        # WM_PAINT must not be needed to cover a native text-button flash.
        button = self.button
        user, gdi = button.user, button.gdi
        user.UpdateWindow.argtypes, user.UpdateWindow.restype = [w.HWND], w.BOOL
        user.GetDC.argtypes, user.GetDC.restype = [w.HWND], w.HDC
        user.ReleaseDC.argtypes, user.ReleaseDC.restype = [w.HWND, w.HDC], ctypes.c_int
        gdi.GetPixel.argtypes, gdi.GetPixel.restype = [w.HDC, ctypes.c_int, ctypes.c_int], w.DWORD
        user.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        user.GetWindowTextW.restype = ctypes.c_int
        rect = w.RECT()
        user.GetClientRect(button.surface, ctypes.byref(rect))
        for theme in ('light', 'dark'):
            button.apply_theme(ui_theme.tokens(theme))
            user.UpdateWindow(button.surface)
            for mode in ('realtime', 'local'):
                button.set_mode(mode)
                label = ctypes.create_unicode_buffer(100)
                user.GetWindowTextW(button.surface, label, len(label))
                self.assertEqual(label.value, button._label())
                dc = user.GetDC(button.surface)
                self.assertTrue(dc)
                try:
                    pixels = [gdi.GetPixel(dc, x, y) for y in range(rect.bottom) for x in range(rect.right)]
                finally:
                    user.ReleaseDC(button.surface, dc)
                foreground = ui_theme._colorref(button.ui['accent' if mode == 'realtime' else 'text'])
                background = ui_theme._colorref(button.ui['bg'])
                self.assertEqual(set(pixels), {background, foreground}, (theme, mode))
                self.assertGreater(pixels.count(foreground), 20, (theme, mode))
                self.assertIsNone(button.error)


if __name__ == '__main__':
    unittest.main()
