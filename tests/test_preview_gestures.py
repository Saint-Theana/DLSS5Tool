"""Gesture ownership, coalescing and real Tk strip-copy verification."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import cv2
import numpy as np
from dlss5tool.gui import App
from tests.test_preview_interaction_continuity import PreviewContinuityTests


def test_right_pan_overrides_near_divider_without_stopping_producer():
    app = PreviewContinuityTests().make_app(playing=True)
    app._preview_zoom = 2.
    app._near_split.return_value = True
    queue = app._preview_frame_queue
    press = SimpleNamespace(x=50, y=50, state=0)
    app.on_canvas_pan_press(press)
    assert app._canvas_press[0] == 'right_pan'
    app.on_canvas_drag(SimpleNamespace(x=70, y=52))
    assert app._preview_pan_x != .5
    app.on_canvas_pan_release(press)
    assert app._canvas_press is None
    app.toggle_play.assert_not_called()
    app._update_split_from_event.assert_not_called()
    PreviewContinuityTests().assert_preserved(app, queue, True)


def test_right_click_and_fit_view_do_not_toggle_play_or_split():
    for zoom in (1., 2.):
        app = PreviewContinuityTests().make_app()
        app._preview_zoom = zoom
        event = SimpleNamespace(x=40, y=40)
        app.on_canvas_pan_press(event)
        app.on_canvas_pan_release(event)
        app.toggle_play.assert_not_called()
        app._update_split_from_event.assert_not_called()


def test_drag_burst_only_schedules_one_repaint_and_release_flushes():
    app = PreviewContinuityTests().make_app()
    app._update_split_from_event = App._update_split_from_event.__get__(app)
    app._video_geom = (0, 0, 200, 100)
    app._drag_split = True
    for x in range(1, 180):
        app._update_split_from_event(SimpleNamespace(x=x))
    assert app.split_x == 179/200
    assert app.root.after.call_count == 1
    app._refresh_viewport_display.assert_not_called()
    app.on_canvas_release(SimpleNamespace(x=179, y=50))
    app._refresh_viewport_display.assert_called_once()


def test_viewport_rasters_reuse_and_invalidate_for_zoom_frame_and_size():
    app = PreviewContinuityTests().make_app()
    source = np.zeros((100, 200, 3), np.uint8)
    other = np.ones_like(source)
    with patch.object(cv2, 'resize', wraps=cv2.resize) as resize:
        for _ in range(20):
            app._render_viewport_image(source, 180, 100)
            app._render_viewport_image(other, 180, 100, track=False)
        assert resize.call_count == 2
        app._preview_zoom = 2.
        app._render_viewport_image(source, 180, 100)
        app._render_viewport_image(source, 200, 100)
        app._render_viewport_image(source.copy(), 200, 100)
        assert resize.call_count == 5
        assert len(app._viewport_rasters) <= 2


def test_real_tk_wipe_updates_only_strip_and_keeps_scene():
    import tkinter as tk
    from PIL import ImageTk
    from dlss5tool import ui_theme
    root = tk.Tk()
    root.withdraw()
    try:
        ui_theme.configure_fonts(root)
        app = PreviewContinuityTests().make_app()
        app.root = root
        app.canvas = tk.Canvas(root, width=200, height=100)
        app._split_orig = np.full((100, 200, 3), (0, 0, 255), np.uint8)
        app._split_dlss = np.full((100, 200, 3), (255, 0, 0), np.uint8)
        app._dlss_pending = False
        app.split_x = .5
        app._draw_navigator = Mock()
        app._draw_pending_status = Mock()
        with patch.object(cv2, 'resize', wraps=cv2.resize) as resize, \
                patch.object(ImageTk, 'PhotoImage', wraps=ImageTk.PhotoImage) as photos:
            app._blit_split(200, 100)
            items = app.canvas.find_all()
            initial_photos = photos.call_count
            def rgb(x):
                return root.tk.call(str(app._photo), 'get', x, 70)
            assert rgb(20) == (255, 0, 0) and rgb(180) == (0, 0, 255)
            for split in (.8, .2, 0., 1., .5):
                app.split_x = split
                app._blit_split(200, 100)
                boundary = int(split*200)
                for x in (0, 20, 90, 170, 199):
                    assert rgb(x) == ((255, 0, 0) if x < boundary else (0, 0, 255))
            assert resize.call_count == 2
            assert photos.call_count == initial_photos
            assert app.canvas.find_all() == items
            app.canvas.delete('all')
            app._blit_split(200, 100)
            assert photos.call_count > initial_photos
    finally:
        app._wipe_photos = None
        app._photo = None
        root.destroy()
