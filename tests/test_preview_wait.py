"""Waiting feedback animates on Tk; worker progress publishers never touch Tk."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
from dlss5tool.gui import App
from dlss5tool.render_cache import RenderSession


def make_app():
    app = App.__new__(App)
    app.root = SimpleNamespace(after=Mock(return_value='timer'), after_cancel=Mock())
    app.video = 'source'
    app._frame = 0
    app._exporting = False
    app._draw_work_status = Mock()
    app.set_status = Mock()
    app.eta_label = SimpleNamespace(cget=lambda _key: (
        app.set_status.call_args.args[0] if app.set_status.call_args else ''))
    return app


def test_wait_clock_pulses_does_not_restart_and_clears_timer():
    app = make_app()
    with patch('dlss5tool.preview_feedback.time.monotonic', return_value=10):
        app._show_preview_wait('Preparing')
    with patch('dlss5tool.preview_feedback.time.monotonic', return_value=13.4):
        app._show_preview_wait('Rendering')
        assert 'Rendering' in app.set_status.call_args.args[0]
        assert '3' in app.set_status.call_args.args[0]
        assert app.root.after.call_count == 1
        app._tick_preview_wait()
    app._clear_preview_wait()
    assert app._preview_wait_key is None
    app.root.after_cancel.assert_called_with('timer')
    app.set_status.assert_called_with('')
    app._draw_work_status.assert_not_called()
    app.set_status.reset_mock()
    app._tick_preview_wait()
    app.set_status.assert_not_called()


def test_clear_wait_preserves_newer_status():
    app = make_app()
    for status in ('Ready', 'Preview failed', 'Exporting'):
        app._show_preview_wait('Preparing')
        app.set_status(status)
        count = app.set_status.call_count
        app._clear_preview_wait()
        app._tick_preview_wait()
        assert app.set_status.call_count == count
        app.set_status.assert_called_with(status)
    app._draw_work_status.assert_not_called()


def test_new_media_resets_clock_and_export_stops_waiting():
    app = make_app()
    with patch('dlss5tool.preview_feedback.time.monotonic', return_value=10):
        app._show_preview_wait('Preparing')
    app.video = 'other'
    with patch('dlss5tool.preview_feedback.time.monotonic', return_value=20):
        app._show_preview_wait('Preparing')
        assert app._preview_wait_started == 20
    app._exporting = True
    app.set_status('Exporting')
    app._tick_preview_wait()
    assert app._preview_wait_key is None
    app.set_status.assert_called_with('Exporting')
    app._draw_work_status.assert_not_called()


def test_progress_is_thread_data_only_and_old_revision_is_ignored():
    app = make_app()
    session = SimpleNamespace(set_progress=Mock())
    app._shared_bind_progress(session)
    old = session.set_progress.call_args.args[0]
    old('scan', .5, (12, 24))
    app._draw_work_status.assert_not_called()
    app.set_status.assert_not_called()
    app._shared_wait_status('Preparing')
    text = app.set_status.call_args.args[0]
    assert 'Preparing' in text and 'scan (12/24)' in text
    assert '\n' not in text
    assert app.set_status.call_count == 1
    app._shared_revision = 2
    app._shared_bind_progress(session)
    old('stale', .8)
    assert app._shared_progress_detail is None
    session.set_progress.call_args.args[0]('new', 0)
    app._shared_wait_status('Preparing')
    assert 'new' in app.set_status.call_args.args[0]
    app._draw_work_status.assert_not_called()


def test_shared_interim_keeps_wait_status_and_ready_frame_stops_it():
    import numpy as np
    app = make_app()
    app._shared_display_config = {}
    app._uses_shared_render = lambda: True
    app.playing = app._hold_original = False
    app.fps = 24
    app.view_var = SimpleNamespace(get=lambda: 'compare')
    app.timeline = SimpleNamespace(get=lambda: 0, set=Mock(), set_cache_ranges=Mock())
    app._sync_transport_labels = Mock()
    app._canvas_size = lambda: (640, 360)
    app._blit_play_split = Mock(side_effect=lambda *args, **kwargs:
                                app._draw_pending_status(640, 360))
    session = SimpleNamespace(multiplier=2, metadata={}, upstream=None,
        snapshot=lambda: {'bytes': 0, 'frames': 1, 'ranges': [0]})
    pair = (np.zeros((8, 8, 4), np.uint8),) * 2
    app._shared_wait_status('Preparing')
    waiting_text = app.set_status.call_args.args[0]
    app._shared_paint(session, pair, 0, waiting=True)
    app.set_status.assert_called_once_with(waiting_text)
    app._shared_paint(session, pair, 0)
    assert app._preview_wait_key is None
    app.root.after_cancel.assert_called_with('timer')
    ready_text = app.set_status.call_args.args[0]
    assert ready_text and ready_text != waiting_text
    app._tick_preview_wait()
    app.set_status.assert_called_with(ready_text)
    app._draw_work_status.assert_not_called()


def test_legacy_pending_updates_bottom_status_and_clears_when_ready():
    app = make_app()
    app._dlss_pending = True
    app._draw_pending_status(640, 360)
    assert app.set_status.call_args.args[0]
    app._dlss_pending = False
    app._draw_pending_status(640, 360)
    app.set_status.assert_called_with('')
    assert app._preview_wait_key is None
    app._draw_work_status.assert_not_called()


def test_legacy_cache_poll_does_not_overwrite_wait_message():
    import threading
    app = make_app()
    app.view_var = SimpleNamespace(get=lambda: 'compare')
    app._active_preview_size = (8, 8)
    app._settings_hash = lambda: ()
    app._cache_lock = threading.RLock()
    app._evict_preview_cache_locked = Mock()
    app._dlss_frame_cache = app._source_frame_cache = {}
    app._dlss_cache_bytes = app._source_cache_bytes = 0
    app.timeline = SimpleNamespace(set_cache_ranges=Mock())
    app._show_preview_wait('Rendering')
    text = app.set_status.call_args.args[0]
    app._update_preview_timeline_and_status(force=True)
    app.timeline.set_cache_ranges.assert_called_once()
    app.set_status.assert_called_once_with(text)


def test_render_session_resolves_latest_progress_subscriber():
    session = RenderSession('source', {}, 1000)
    try:
        old, new = Mock(), Mock()
        session.set_progress(old)
        report = session._report_progress
        session.set_progress(new)
        report('stage', 0)
        old.assert_not_called()
        new.assert_called_once_with('stage', 0)
    finally:
        session.close()


def test_repeated_source_poll_does_not_repaint_unchanged_frame():
    import numpy as np
    app = make_app()
    app.view_var = SimpleNamespace(get=lambda: 'original')
    app._canvas_size = lambda: (640, 360)
    app._draw_fit = Mock()
    image = np.zeros((100, 200, 3), np.uint8)
    for _ in range(20):
        app._present_shared_source(image)
    assert app._draw_fit.call_count == 1
    app._preview_zoom = 2
    app._present_shared_source(image)
    assert app._draw_fit.call_count == 2
