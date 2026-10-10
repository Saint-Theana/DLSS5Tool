import os
import struct
import subprocess
import sys
import unittest
from unittest import mock

from PIL import Image

from dlss5tool import ui_theme


REQUIRED_ICO_SIZES = (
    (16, 16), (20, 20), (24, 24), (32, 32), (36, 36),
    (40, 40), (48, 48), (64, 64), (256, 256),
)


class AppIconTests(unittest.TestCase):
    def test_release_files_require_icons_and_include_full_upstream_notices(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "packaging/DLSS5Tool.spec"), encoding="utf-8") as handle:
            spec = handle.read()
        self.assertIn("Missing required application icon", spec)
        self.assertIn("icon=app_icon", spec)
        with open(os.path.join(root, "THIRD_PARTY_NOTICES.md"), encoding="utf-8") as handle:
            notices = handle.read()
        self.assertIn("Lucide ISC License", notices)
        self.assertIn("Feather-derived icons — MIT License", notices)
        self.assertIn("Permission to use, copy, modify, and/or distribute", notices)
        self.assertIn("Copyright (c) 2013-present Cole Bemis", notices)

    def test_icon_files_exist(self):
        ico_path, png_path = ui_theme.app_icon_paths()
        self.assertTrue(os.path.isfile(ico_path), ico_path)
        self.assertTrue(os.path.isfile(png_path), png_path)

    def test_png_is_square(self):
        _ico_path, png_path = ui_theme.app_icon_paths()
        with Image.open(png_path) as image:
            self.assertEqual(image.size[0], image.size[1])
            self.assertGreaterEqual(image.size[0], 256)

    def test_png_has_transparent_corners(self):
        _ico_path, png_path = ui_theme.app_icon_paths()
        with Image.open(png_path) as image:
            rgba = image.convert("RGBA")
            width, height = rgba.size
            for x, y in (
                (0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1),
            ):
                self.assertLessEqual(rgba.getpixel((x, y))[3], 8, (x, y))

    def test_ico_taskbar_size_keeps_rounded_corners(self):
        ico_path, _png_path = ui_theme.app_icon_paths()
        with Image.open(ico_path) as image:
            image.size = (48, 48)
            rgba = image.convert("RGBA")
        for x, y in ((0, 0), (47, 0), (0, 47), (47, 47)):
            self.assertLessEqual(rgba.getpixel((x, y))[3], 32, (x, y))
        center = rgba.getpixel((24, 24))
        self.assertGreaterEqual(center[3], 200)

    def test_png_has_center_split(self):
        _ico_path, png_path = ui_theme.app_icon_paths()
        with Image.open(png_path) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            found = False
            for y in range(height):
                red, green, blue = rgb.getpixel((width // 2, y))
                if green >= 180 and blue >= 180 and green >= red and blue >= red:
                    found = True
                    break
        self.assertTrue(found, "expected a cyan/white vertical split on the midline")

    def test_ico_contains_windows_sizes(self):
        ico_path, _png_path = ui_theme.app_icon_paths()
        with Image.open(ico_path) as image:
            sizes = set(image.ico.sizes())
        for required in REQUIRED_ICO_SIZES:
            self.assertIn(required, sizes)

    def test_ico_small_sizes_are_bmp(self):
        ico_path, _png_path = ui_theme.app_icon_paths()
        with open(ico_path, "rb") as handle:
            data = handle.read()
        count = struct.unpack_from("<H", data, 4)[0]
        self.assertGreaterEqual(count, 8)
        saw_bmp = False
        saw_png = False
        for index in range(count):
            width = data[6 + 16 * index]
            size, offset = struct.unpack_from("<II", data, 6 + 16 * index + 8)
            blob = data[offset:offset + size]
            if width == 0:
                self.assertTrue(blob.startswith(b"\x89PNG\r\n\x1a\n"))
                saw_png = True
            else:
                self.assertFalse(blob.startswith(b"\x89PNG\r\n\x1a\n"), width)
                saw_bmp = True
        self.assertTrue(saw_bmp)
        self.assertTrue(saw_png)

    def test_claim_app_identity(self):
        if sys.platform != "win32":
            self.skipTest("Windows only")
        self.assertTrue(ui_theme.claim_app_identity())

    def test_apply_app_icon(self):
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        try:
            self.assertTrue(ui_theme.apply_app_icon(root, default=True))
            if sys.platform == "win32":
                handles = getattr(root, "_app_icon_handles", [])
                self.assertTrue(any(handles))
                ui_theme.release_app_icon(root)
                self.assertEqual(root._app_icon_handles, [])
        finally:
            root.destroy()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows only')
    def test_windows_default_icon_is_registered_once_for_tk_not_only_hwnd(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            with mock.patch.object(root, 'iconbitmap', wraps=root.iconbitmap) as bitmap:
                self.assertTrue(ui_theme.apply_app_icon(root, default=True))
                self.assertTrue(ui_theme.apply_app_icon(root, default=True))
            bitmap.assert_called_once_with(default=ui_theme.app_icon_paths()[0])
        finally:
            root.destroy()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows only')
    def test_default_class_icon_changes_from_feather_in_fresh_process(self):
        # Unlike a mock assertion, this checks the actual Tk class icon used
        # by Windows' default-icon fallback, in an interpreter with no prior
        # app icon registrations. WM_SETICON alone does not change this value.
        script = '''
import ctypes
import tkinter as tk
from dlss5tool import ui_theme
root = tk.Tk()
root.update_idletasks()
root.withdraw()
user = ctypes.WinDLL('user32')
user.GetClassLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user.GetClassLongPtrW.restype = ctypes.c_void_p
try:
    before = [user.GetClassLongPtrW(ui_theme._window_hwnd(root), n) for n in (-14, -34)]
    assert all(before), before
    ui_theme._apply_win32_icons(root, ui_theme.app_icon_paths()[0])
    window_only = [user.GetClassLongPtrW(ui_theme._window_hwnd(root), n) for n in (-14, -34)]
    assert window_only == before, (window_only, before)
    assert ui_theme.apply_app_icon(root, default=True)
    after = [user.GetClassLongPtrW(ui_theme._window_hwnd(root), n) for n in (-14, -34)]
    assert all(after) and all(a != b for a, b in zip(after, before)), (before, after)
    child = tk.Toplevel(root)
    child.update_idletasks()
    inherited = [user.GetClassLongPtrW(ui_theme._window_hwnd(child), n) for n in (-14, -34)]
    assert inherited == after, (inherited, after)
    child.destroy()
finally:
    root.destroy()
print('Tk default/class icon changed; new windows inherit the product icon')
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
                                timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_destroying_window_releases_native_icon_handles(self):
        if sys.platform != "win32":
            self.skipTest("Windows only")
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        window = tk.Toplevel(root)
        window.withdraw()
        try:
            self.assertTrue(ui_theme.apply_app_icon(window))
            self.assertTrue(any(
                getattr(window, "_app_icon_handles", ())
                or getattr(window, "_app_icon_borrowed_handles", ())
            ))
            window.destroy()
            root.update_idletasks()
            self.assertEqual(window._app_icon_handles, [])
            self.assertEqual(window._app_icon_borrowed_handles, [])
        finally:
            try:
                window.destroy()
            except tk.TclError:
                pass
            root.destroy()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows only')
    def test_native_icons_survive_remap_and_theme_without_reloading(self):
        import ctypes
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        user32 = ctypes.WinDLL('user32')
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        user32.SendMessageW.restype = ctypes.c_void_p
        user32.GetClassLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetClassLongPtrW.restype = ctypes.c_void_p
        try:
            self.assertTrue(ui_theme.apply_app_icon(root, default=True))
            original = root._app_icon_handles[:]
            # Class/default handles must also exist, for newly created wrappers.
            hwnd = ui_theme._window_hwnd(root)
            self.assertTrue(user32.GetClassLongPtrW(hwnd, -14))
            self.assertTrue(user32.GetClassLongPtrW(hwnd, -34))
            with mock.patch('dlss5tool.ui_theme._load_icon_file', wraps=ui_theme._load_icon_file) as load:
                for theme in ('light', 'dark'):
                    root.deiconify()
                    root.update()
                    ui_theme.apply_native_titlebar(root, ui_theme.tokens(theme), theme == 'dark')
                    root.iconify()
                    root.update()
                    root.deiconify()
                    root.update()
                    for index, expected in enumerate(original):
                        self.assertEqual(user32.SendMessageW(ui_theme._window_hwnd(root), 0x007F, index, 0), expected)
                    child = tk.Toplevel(root)
                    child.withdraw()
                    ui_theme.apply_app_icon(child)
                    child.deiconify()
                    root.update()
                    self.assertEqual(child._app_icon_borrowed_handles, original)
                    child.destroy()
                    root.withdraw()
                    root.update()
            load.assert_not_called()
            self.assertEqual(root._app_icon_handles, original)
            self.assertEqual(errors, [])
        finally:
            root.destroy()
        self.assertEqual(root._app_icon_cache, {})

    @unittest.skipUnless(sys.platform == 'win32', 'Windows only')
    def test_repeated_detach_and_dock_has_bounded_gui_resources(self):
        import ctypes
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        user32 = ctypes.WinDLL('user32')
        kernel32 = ctypes.WinDLL('kernel32')
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        user32.GetGuiResources.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.GetGuiResources.restype = ctypes.c_uint
        process = kernel32.GetCurrentProcess()
        def cycle():
            child = tk.Toplevel(root)
            child.withdraw()
            ui_theme.apply_app_icon(child)
            child.destroy()
            root.update_idletasks()
        try:
            ui_theme.apply_app_icon(root, default=True)
            cycle()
            before = [user32.GetGuiResources(process, kind) for kind in (0, 1)]
            for _ in range(25):
                cycle()
            after = [user32.GetGuiResources(process, kind) for kind in (0, 1)]
            self.assertTrue(all(end <= start + 4 for start, end in zip(before, after)), (before, after))
        finally:
            root.destroy()
