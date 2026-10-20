"""Source changes invalidate pixels without churning a stateless GPU device."""
import threading
import time
from unittest.mock import Mock, patch

import numpy as np
import pytest

from dlss5tool.gui import App
from dlss5tool.preview_jobs import LatestPreviewJob


def until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(.002)


def cache_app():
    app = App.__new__(App)
    app._cancel_after = Mock()
    app._cache_lock = threading.RLock()
    app._dlss_frame_cache = {0: object()}
    app._source_frame_cache = {0: object()}
    app._queued_preview_frames = {1}
    app._source_cache_bytes = app._dlss_cache_bytes = 10
    app._local_composition_request = object()
    app._local_composition_inputs = (object(), object())
    app._local_composition_last = (0, object())
    app._background_preview_decoder = Mock()
    return app


def test_source_invalidation_reuses_owner_and_rejects_inflight_old_pixels():
    app = cache_app()
    cleanup, owners = [], []
    entered, release = threading.Event(), threading.Event()
    job = app._local_composition_job = LatestPreviewJob(
        persistent=True, cleanup=lambda: cleanup.append(threading.get_ident()))

    def old():
        owners.append(threading.get_ident())
        entered.set()
        assert release.wait(3)
        return 'old pixels'

    try:
        job.request('same-key', old)
        assert entered.wait(1)
        app._cache_clear(release_composition=False)
        assert app._local_composition_request is None
        assert app._local_composition_inputs is None
        assert app._local_composition_last is None
        assert not app._local_composition_busy
        assert app._source_frame_cache == app._dlss_frame_cache == {}
        assert app._source_cache_bytes == app._dlss_cache_bytes == 0
        app._background_preview_decoder.invalidate.assert_called_once_with()
        job.request('same-key', lambda: owners.append(threading.get_ident()) or 'new pixels')
        release.set()
        until(job.ready)
        assert job.request('same-key', None) == 'new pixels'
        assert len(owners) == 2 and owners[0] == owners[1]
        assert cleanup == []
        app._cache_clear()
        until(lambda: len(cleanup) == 1)
        assert cleanup == [owners[0]]
    finally:
        release.set()
        job.close()
        until(lambda: not job.is_alive())


@pytest.mark.parametrize('reuse', [False, True])
def test_source_load_selects_reuse_and_still_clears_media(reuse):
    app = App.__new__(App)
    app.pause = Mock()
    app._freeze_preview_cache = Mock()
    app._audio = Mock()
    app._cache_clear = Mock()
    app._cancel_after = Mock()
    app._update_zoom_controls = Mock()
    app.timeline = Mock()
    app._cap = Mock()
    cap = app._cap
    app._begin_source_load(reuse_composition=reuse)
    if reuse:
        app._cache_clear.assert_called_once_with(release_composition=False)
    else:
        app._cache_clear.assert_called_once_with()
    cap.release.assert_called_once_with()
    assert app.video is app._cap is app._image_bgr is None
    app._freeze_preview_cache.assert_called_once_with(resume_ms=None)


@pytest.mark.parametrize('readable', [False, True])
def test_image_load_only_reuses_composer_after_validating_source(readable):
    app = App.__new__(App)
    for name in ('_begin_source_load', '_sync_window_titles', '_sync_transport_labels',
                 '_update_action_labels', '_update_export_control_states', 'display_view',
                 'logln', 'set_status', '_schedule_preview_cache_resume'):
        setattr(app, name, Mock())
    app.timeline = Mock()
    pixels = np.zeros((4, 8, 3), np.uint8) if readable else None
    with patch('dlss5tool.gui.read_still', return_value=(pixels, None)), \
            patch('dlss5tool.gui.messagebox.showerror'):
        assert app._load_image('image.png') == readable
    if readable:
        app._begin_source_load.assert_called_once_with(reuse_composition=True)
        assert app.video == 'image.png'
        assert app._source_kind == 'image'
    else:
        app._begin_source_load.assert_not_called()
