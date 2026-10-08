"""Synthetic, hidden-Tk wipe probe; no GPU, media files or settings writes.

Run: .venv/Scripts/python.exe -B scripts/preview_interaction_probe.py
Reports callback time, not visible end-to-end mouse latency. Sources and all Tk
surfaces are held only in RAM; peak for the 8K case is below 1 GiB.
"""
import json
from pathlib import Path
import sys
import time
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from PIL import ImageTk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dlss5tool.gui import App


def main():
    root = tk.Tk()
    root.withdraw()
    try:
        app = App.__new__(App)
        app.canvas = tk.Canvas(root)
        app.compare_layout = SimpleNamespace(get=lambda: 'wipe')
        app._preview_zoom = 1.
        app._preview_pan_x = app._preview_pan_y = .5
        app._source_kind = 'video'
        app._hold_original = app._dlss_pending = False
        app._active_compare = lambda: True
        app._compare_label = lambda: 'Processed'
        app._ui_color = lambda name, fallback: fallback
        for method in ('_canvas_shadow_text', '_draw_processed_preview_label',
                       '_draw_navigator', '_draw_pending_status'):
            setattr(app, method, lambda *args, **kwargs: None)
        for sw, sh, vw, vh in ((1920, 1080, 1280, 720), (3840, 2160, 1920, 1080),
                                (7680, 4320, 3840, 2160)):
            app._viewport_rasters = []
            app._wipe_photos = None
            app._wipe_surface_key = None
            app._split_orig = np.full((sh, sw, 3), 48, np.uint8)
            app._split_dlss = np.full((sh, sw, 3), 148, np.uint8)
            app.split_x = .25
            app._blit_split(vw, vh)
            timings = []
            with patch.object(cv2, 'resize', wraps=cv2.resize) as resize, \
                    patch.object(ImageTk, 'PhotoImage', wraps=ImageTk.PhotoImage) as photo:
                for index in range(1, 31):
                    app.split_x = .25 + index * .015
                    start = time.perf_counter()
                    app._blit_split(vw, vh)
                    timings.append((time.perf_counter() - start) * 1000)
                print(json.dumps(dict(source=[sw, sh], viewport=[vw, vh],
                    median_ms=round(float(np.median(timings)), 3),
                    p95_ms=round(float(np.percentile(timings, 95)), 3),
                    resizes=resize.call_count, photo_constructions=photo.call_count)))
    finally:
        root.destroy()


if __name__ == '__main__':
    main()
