"""Inspect the About branding in both languages/themes without network calls."""
import argparse
import json
from pathlib import Path
import sys
import tkinter as tk
from unittest import mock

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dlss5tool import about_dialog, i18n, ui_theme


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def inspect(directory, screenshots=False):
    directory.mkdir(parents=True, exist_ok=True)
    ui_theme.enable_dpi_awareness()
    root = tk.Tk()
    root.geometry('420x150+40+40')
    root.update()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(str(args[1]))
    records = []
    try:
        for language in ('zh_CN', 'en_US'):
            i18n.set_language(language)
            for theme in ('light', 'dark'):
                root._dlss_ui = ui_theme.tokens(theme)
                ui_theme.apply_ttk(root, root._dlss_ui)
                with mock.patch.object(about_dialog, '_load_latest'):
                    window = about_dialog.show_about(root, lambda: None, lambda: None,
                                                     on_import_update=lambda: None)
                root.update()
                assert window.winfo_ismapped()
                width, height = window.winfo_width(), window.winfo_height()
                labels = [w for w in walk(window) if isinstance(w, tk.Label) and w.cget('image')]
                assert len(labels) == 1
                assert window._about_mark.width() >= 56
                for widget in walk(window):
                    if not widget.winfo_ismapped():
                        continue
                    x = widget.winfo_rootx() - window.winfo_rootx()
                    y = widget.winfo_rooty() - window.winfo_rooty()
                    assert x >= 0 and y >= 0
                    assert x + widget.winfo_width() <= width
                    assert y + widget.winfo_height() <= height
                if screenshots:
                    ImageGrab.grab(window=ui_theme._window_hwnd(window)).save(directory / f'about-{language}-{theme}.png')
                records.append(dict(language=language, theme=theme, size=[width, height],
                                    logo_size=window._about_mark.width(), fits=True))
                window.destroy()
                root.update()
        assert not errors, errors
        print(json.dumps(records))
    finally:
        root.destroy()
        i18n.set_language(i18n.DEFAULT_LANGUAGE)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--screenshots', action='store_true')
    args = parser.parse_args()
    inspect(args.work_dir, args.screenshots)
