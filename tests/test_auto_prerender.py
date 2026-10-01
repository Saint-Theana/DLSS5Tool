"""Automatic fill-ahead can stop without losing current-frame or playback work."""
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from dlss5tool import app_settings, render_cache
from dlss5tool.gui import App


def make_app(enabled=False, playing=False, proxy=(8, 4)):
    app = App.__new__(App)
    app._preview_settings = {'v_auto_prerender': SimpleNamespace(get=lambda: enabled)}
    app._preview_runtime_settings = app._collect_preview_settings()
    app.playing = playing
    app.video = 'preview.mp4'
    app._source_kind = 'video'
    app._image_bgr = None
    app._exporting = app._hold_original = app._preview_cache_frozen = False
    app._pre_rendering = False
    app._frame, app.nframes, app.fps = 2, 80, 24
    app._media_w, app._media_h = 8, 4
    app._prefetch_gen = 10
    app._prefetch_stop = threading.Event()
    app._cache_lock = threading.RLock()
    app._queued_preview_frames = set()
    app._preview_frame_queue = object()
    app._source_frame_cache = {2: np.zeros((4, 8, 3), np.uint8)}
    app._dlss_frame_cache = {('existing',): object()}
    app._source_cache_get = app._source_frame_cache.get
    app._source_cache_store = lambda frame, source: app._source_frame_cache.update({frame: source})
    app._precise_preview_size = lambda: (8, 4)
    app._playback_preview_size = lambda: proxy
    app._super_resolution_scale = lambda: 1
    app._cached_dlss = Mock(return_value=None)
    app._cached_dlss_sk = Mock(return_value=object())
    app._settings_hash = lambda: ('settings',)
    app._cache_capacity_frames = lambda: 16
    app._buffer_target_frames = lambda: 3
    app.view_var = SimpleNamespace(get=lambda: 'compare')
    app.root = SimpleNamespace(after=Mock(), after_cancel=Mock())
    for name in ('display_view', '_start_prefetch', '_queue_preview_frame',
                 '_schedule_preview_decode', '_update_preview_timeline_and_status',
                 '_present_current_cached_preview', '_cancel_after',
                 '_schedule_preview_cache_resume', '_schedule_settings_save', 'set_status'):
        setattr(app, name, Mock())
    app._start_prefetch.return_value = True
    return app


def check_default_and_saved_choice(tmp_path):
    assert app_settings.validate({})['preview_auto_prerender'] is False
    assert app_settings.validate({'preview_auto_prerender': 'false'})['preview_auto_prerender'] is False
    path = tmp_path / 'settings.json'
    for enabled in (True, False):
        app = make_app(enabled)
        app_settings.save(app._collect_preview_settings(), path)
        restored = App.__new__(App)
        restored._saved_settings = app_settings.load(path)
        assert restored._preview_auto_prerender() is enabled


def check_disabled_preview_renders_current_frame_once_without_handoff(proxy):
    app = make_app(proxy=proxy)
    app._apply_full_preview()
    assert app._pre_rendering
    assert app._prerender_target_frames() == 1
    app._start_prefetch.assert_called_once_with(preview_size=(8, 4))
    assert [call.args[0] for call in app._queue_preview_frame.call_args_list] == [2]
    app._queue_preview_frame.reset_mock()
    app._schedule_full_preview = Mock()
    app._handle_preview_worker_error = lambda: False
    app._preview_decode_tick()
    assert not app._pre_rendering
    assert app._prefetch_stop.is_set()
    app._queue_preview_frame.assert_not_called()
    app._schedule_full_preview.assert_not_called()


def check_disabled_mode_rejects_forward_work_after_current_frame_is_cached():
    app = make_app()
    app._cached_dlss.return_value = object()
    app._apply_full_preview()
    app.display_view.assert_called_once_with(quality='full')
    assert app._start_paused_prerender() is False
    app._start_prefetch.assert_not_called()


def check_switch_off_retires_queued_tasks_and_keeps_completed_cache():
    app = make_app()
    app._pre_rendering = True
    app._queued_preview_frames.update((2, 3, 4))
    before = dict(app._dlss_frame_cache)
    app._on_auto_prerender_change()
    assert not app._pre_rendering
    assert app._prefetch_stop.is_set()
    assert app._prefetch_gen == 11
    assert not app._queued_preview_frames
    assert app._preview_frame_queue is None
    assert app._dlss_frame_cache == before
    app._schedule_settings_save.assert_called_once()
    app._schedule_preview_cache_resume.assert_called_once_with(0)
    # A pending retry returns through the normal current-frame preview path.
    app._schedule_full_preview = Mock()
    app._resume_preview_cache()
    app._schedule_full_preview.assert_called_once()
    app._apply_full_preview()
    assert app._prerender_target_frames() == 1


def check_switch_on_resumes_forward_cache_from_current_position():
    app = make_app(enabled=True)
    app._on_auto_prerender_change()
    app._schedule_preview_cache_resume.assert_called_once_with(0)
    assert app._start_paused_prerender()
    assert app._prerender_target_frames() > 1
    assert app._frame == 2


def check_switch_off_during_playback_preserves_worker_and_clock():
    app = make_app(playing=True)
    app._shared_clock = 123.0
    original_queue = app._preview_frame_queue
    app._on_auto_prerender_change()
    assert app.playing
    assert app._shared_clock == 123.0
    assert app._preview_frame_queue is original_queue
    assert not app._prefetch_stop.is_set()
    assert app._prefetch_gen == 10
    app._schedule_preview_cache_resume.assert_not_called()


def check_playback_still_buffers_with_automatic_prerender_off():
    app = make_app(playing=True)
    app._enter_preview_buffering = Mock()
    assert app._start_strict_preview_buffering()
    app._start_prefetch.assert_called_once_with()
    assert app._prerender_frame_limit is None
    app._enter_preview_buffering.assert_called_once_with(2)


def check_shared_switch_off_preserves_session_and_playback(playing):
    app = make_app(playing=playing)
    app._uses_shared_render = lambda: True
    session = app._shared_session = SimpleNamespace(set_prefetch=Mock())
    app._shared_display = Mock()
    app._on_auto_prerender_change()
    assert app._shared_session is session
    assert app.playing is playing
    session.set_prefetch.assert_called_once_with(playing)
    assert app._shared_display.call_count == (0 if playing else 1)


def check_pause_immediately_disables_shared_fill_ahead():
    app = make_app(playing=True)
    app._shared_session = SimpleNamespace(set_prefetch=Mock())
    app._audio = SimpleNamespace(pause=Mock())
    app._set_play_btn = Mock()
    app._schedule_full_preview = Mock()
    app.pause()
    assert not app.playing
    app._shared_session.set_prefetch.assert_called_once_with(False)
    app._schedule_full_preview.assert_called_once()


def check_shared_display_applies_idle_policy_before_request(enabled, playing):
    app = make_app(enabled, playing)
    calls = []
    session = SimpleNamespace(multiplier=2,
        set_prefetch=lambda value: calls.append(('prefetch', value)),
        request=lambda index: calls.append(('request', index)))
    app._shared_ready = lambda: session
    app._shared_source_preview = Mock()
    app._shared_interim = Mock()
    app._shared_display()
    assert calls == [('prefetch', enabled or playing), ('request', 4)]


def check_shared_producer_stops_at_required_real_frame_and_can_resume(multiplier, index, required_sources):
    rendered = []
    entered_next = threading.Event()
    rendered_next = threading.Event()
    finished = threading.Event()

    def renderer(source, output, *, frame_sink, metadata_sink, render_gate, **kwargs):
        metadata_sink({'source_frames': 12})
        pixels = np.zeros((4, 8, 4), np.uint8)
        for source_index in range(13):
            if source_index == required_sources:
                entered_next.set()
            render_gate(source_index)
            if source_index == 12:
                break
            rendered.append(source_index)
            if source_index == required_sources:
                rendered_next.set()
            if source_index:
                for subframe in range(1, multiplier):
                    frame_sink((source_index-1)*multiplier+subframe, pixels, pixels)
            frame_sink(source_index*multiplier, pixels, pixels)
        for subframe in range(1, multiplier):
            frame_sink(11*multiplier+subframe, pixels, pixels)
        finished.set()
        return {}

    session = render_cache.RenderSession('source', {'frame_generation_multiplier': multiplier},
                                         100000, renderer=renderer)
    try:
        session.set_prefetch(False)
        assert session.wait(index, threading.Event()) is not None
        assert entered_next.wait(3)
        assert not rendered_next.wait(.1)
        assert rendered == list(range(required_sources))
        cached = session.peek(index)
        session.set_prefetch(True)
        assert finished.wait(3)
        assert session.peek(index) is cached
        assert rendered == list(range(12))
    finally:
        session.close()


def check_shared_policy_reaches_spatial_and_enhancement_workers():
    from tests.test_render_cache import renderer
    manager = render_cache.RenderCache(200000)
    with patch.object(render_cache, 'export_video', renderer):
        try:
            session = manager.session('source', {'frame_generation_multiplier': 4, 'super_resolution_scale': 2})
            session.set_prefetch(False)
            assert session.wait(0, threading.Event()) is not None
            assert not session.prefetch and not manager.base.prefetch and not manager.spatial.prefetch
            assert manager.base.new_frames == manager.spatial.new_frames == 1
            session.set_prefetch(True)
            assert session.wait(20, threading.Event()) is not None
            assert manager.base.prefetch and manager.spatial.prefetch
        finally:
            manager.close()


class AutoPrerenderTests(unittest.TestCase):
    def test_default_and_saved_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            check_default_and_saved_choice(Path(directory))

    def test_disabled_preview_renders_current_frame_once_without_handoff(self):
        for proxy in ((8, 4), (4, 2)):
            with self.subTest(proxy=proxy):
                check_disabled_preview_renders_current_frame_once_without_handoff(proxy)

    def test_disabled_mode_rejects_forward_work_after_current_frame_is_cached(self):
        check_disabled_mode_rejects_forward_work_after_current_frame_is_cached()

    def test_switch_off_retires_queued_tasks_and_keeps_completed_cache(self):
        check_switch_off_retires_queued_tasks_and_keeps_completed_cache()

    def test_switch_on_resumes_forward_cache_from_current_position(self):
        check_switch_on_resumes_forward_cache_from_current_position()

    def test_switch_off_during_playback_preserves_worker_and_clock(self):
        check_switch_off_during_playback_preserves_worker_and_clock()

    def test_playback_still_buffers_with_automatic_prerender_off(self):
        check_playback_still_buffers_with_automatic_prerender_off()

    def test_shared_switch_off_preserves_session_and_playback(self):
        for playing in (False, True):
            with self.subTest(playing=playing):
                check_shared_switch_off_preserves_session_and_playback(playing)

    def test_pause_immediately_disables_shared_fill_ahead(self):
        check_pause_immediately_disables_shared_fill_ahead()

    def test_shared_display_applies_idle_policy_before_request(self):
        for enabled, playing in ((False, False), (True, False), (False, True)):
            with self.subTest(enabled=enabled, playing=playing):
                check_shared_display_applies_idle_policy_before_request(enabled, playing)

    def test_shared_producer_stops_at_required_real_frame_and_can_resume(self):
        for multiplier, index, required in ((1, 0, 1), (4, 0, 1), (4, 5, 3)):
            with self.subTest(multiplier=multiplier, index=index):
                check_shared_producer_stops_at_required_real_frame_and_can_resume(multiplier, index, required)

    def test_shared_policy_reaches_spatial_and_enhancement_workers(self):
        check_shared_policy_reaches_spatial_and_enhancement_workers()


if __name__ == '__main__':
    unittest.main()
