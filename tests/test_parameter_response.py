"""Interaction latency contracts without inference, native capture, or user media."""
from copy import deepcopy
import threading
import time
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest

from dlss5tool.preview_jobs import LatestPreviewJob
from dlss5tool.gui import App, compose_preview_frame
from tests import test_parameter_unification as local, test_realtime_inspector as realtime


def wait_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(.002)


def test_worker_latest_only_bounded_and_never_runs_on_ui():
    job = LatestPreviewJob()
    entered, release = threading.Event(), threading.Event()
    calls = []
    def slow():
        calls.append(('first', threading.get_ident()))
        entered.set()
        assert release.wait(3)
        return 'old'
    assert job.request(0, slow) is None
    assert entered.wait(1)
    for i in range(1, 100):
        assert job.request(i, lambda n=i: calls.append((n, threading.get_ident())) or n) is None
    release.set()
    wait_until(job.ready)
    assert job.request(99, lambda: pytest.fail('must be cached')) == 99
    assert [c[0] for c in calls] == ['first', 99]
    assert all(c[1] != threading.get_ident() for c in calls)


def test_worker_retirement_and_error_are_revision_scoped():
    job = LatestPreviewJob()
    entered, release = threading.Event(), threading.Event()
    def fail():
        entered.set()
        assert release.wait(3)
        raise ValueError('retired')
    job.request('A', fail)
    assert entered.wait(1)
    job.invalidate()
    job.request('A', lambda: 'new')
    release.set()
    wait_until(job.ready)
    assert job.request('A', None) == 'new'
    job.request('error', lambda: 1/0)
    wait_until(job.ready)
    with pytest.raises(ZeroDivisionError):
        job.request('error', None)


def app_stub():
    app = App.__new__(App)
    app.video, app._frame = 'synthetic', 0
    app.root = SimpleNamespace(after=mock.Mock(return_value='timer'), after_cancel=mock.Mock())
    app._cancel_after = mock.Mock()
    app._uses_shared_render = lambda: False
    app.playing = False
    app._show_preview_wait = mock.Mock()
    app._clear_preview_wait = mock.Mock()
    app.display_view = mock.Mock()
    app.set_status = mock.Mock()
    app.logln = mock.Mock()
    return app


def test_local_composition_keeps_last_picture_and_exact_full_resolution_result():
    app = app_stub()
    source = np.full((80, 48, 3), 50, np.uint8)
    processed = np.full_like(source, 100)
    settings = {'output_mix': .5, 'nr_residual': {'residualSaturation': 1.2}}
    expected = compose_preview_frame(source, processed, output_mix=.5, settings=settings)
    assert app._local_compose_preview(0, source, processed, {}) is processed
    entered, release = threading.Event(), threading.Event()
    def slow(*a, **kw):
        entered.set()
        assert release.wait(3)
        return compose_preview_frame(*a, **kw)
    with mock.patch('dlss5tool.gui.compose_preview_frame', side_effect=slow):
        assert app._local_compose_preview(0, source, processed, settings) is processed
        assert entered.wait(1)
        assert app._local_composition_busy
        app._show_preview_wait.assert_called()
        release.set()
        wait_until(app._local_composition_job.ready)
        result = app._local_compose_preview(0, source, processed, settings)
    assert result.shape == processed.shape
    np.testing.assert_array_equal(result, expected)
    assert not app._local_composition_busy


@pytest.mark.parametrize('state,value', [('_exporting', True), ('_queue_running', True),
    ('_workbench_mode', 'realtime'), ('_shared_closing', True), ('_clear_preview_pending', True),
    ('video', 'different'), ('_frame', 3), ('playing', True)])
def test_local_result_never_repaints_after_lifecycle_change(state, value):
    app = app_stub()
    pixels = np.full((8, 8, 3), 20, np.uint8)
    app._local_compose_preview(0, pixels, pixels.copy(), {'output_mix': .3})
    wait_until(app._local_composition_job.ready)
    setattr(app, state, value)
    app._poll_local_composition()
    app.display_view.assert_not_called()
    assert app._local_composition_request is None


class TestLocalResponse:
    def setup_method(self):
        self.fixture = local.LocalAdjustmentTests()
        self.fixture.setUp()

    def teardown_method(self):
        self.fixture.tearDown()

    def test_drag_fast_path_release_undo_and_read_does_not_commit_mid_gesture(self):
        f = self.fixture
        row = f.editor.rows['intensity']
        before = f.editor.snapshot()
        slider = row.slider
        with mock.patch.object(f.editor, 'refresh', wraps=f.editor.refresh) as refresh:
            slider._on_down(SimpleNamespace(x=20))
            for x in range(25, 180, 5):
                slider._on_drag(SimpleNamespace(x=x))
                assert not f.editor.commit(notify=False)
            refresh.assert_not_called()
            assert f.settings['v_intensity'].get() == 1
            assert float(row.number_text.get()) == pytest.approx(slider.get())
            f.model.assert_not_called()
            slider._on_up(SimpleNamespace(x=175))
            f.model.assert_called_once()
            assert f.settings['v_intensity'].get() == slider.get()
        f.editor.undo()
        assert f.editor.snapshot() == before

    def test_unchanged_collect_is_read_only(self):
        f = self.fixture
        with mock.patch.object(f.editor, '_apply') as apply, mock.patch.object(f.editor, 'refresh') as refresh:
            for _ in range(20):
                assert f.editor.commit(notify=False)
            apply.assert_not_called()
            refresh.assert_not_called()


    def test_tk_heartbeat_and_controls_work_during_slow_composition(self):
        f = self.fixture
        app = app_stub()
        app.root = f.root
        pixels = np.full((8, 8, 3), 30, np.uint8)
        entered, release = threading.Event(), threading.Event()
        def slow(*a, **kw):
            entered.set()
            assert release.wait(3)
            return compose_preview_frame(*a, **kw)
        ticks = []
        with mock.patch('dlss5tool.gui.compose_preview_frame', side_effect=slow):
            try:
                app._local_compose_preview(0, pixels, pixels.copy(), {'output_mix': .3})
                assert entered.wait(1)
                f.root.after(0, lambda: ticks.append('responsive'))
                row = f.editor.rows['intensity']
                row.slider._nudge(-1)
                f.root.update()
                assert ticks == ['responsive']
                assert row.value() == .99
                assert not app._local_composition_job.ready()
            finally:
                release.set()
                wait_until(app._local_composition_job.ready)
                if app._local_composition_after:
                    f.root.after_cancel(app._local_composition_after)
                app._invalidate_local_composition()


class TestRealtimeResponse:
    def setup_method(self):
        self.fixture = realtime.RealtimeInspectorTests()
        self.fixture.setUp()
        self.fixture.running()
        self.fixture.root.update()

    def teardown_method(self):
        self.fixture.tearDown()

    def test_poll_and_pending_receipt_do_not_apply_half_finished_drag(self):
        f = self.fixture
        row = f.ui.parameter_rows['intensity']
        row.variable.set('1.2'); row.commit()
        row.variable.set('1.4'); row.commit()
        assert f.client.send.call_count == 1
        slider = row.slider
        slider._on_down(SimpleNamespace(x=30))
        with mock.patch.object(f.ui, 'collect', wraps=f.ui.collect) as collect:
            f.ui._refresh_editor_state()
            collect.assert_not_called()
        applied = deepcopy(f.ui._applied_effects)
        applied[0]['parameters']['intensity'] = 1.2
        f.status(applied)
        assert f.client.send.call_count == 1
        slider._on_drag(SimpleNamespace(x=120))
        slider._on_up(SimpleNamespace(x=120))
        assert f.client.send.call_count == 2
        assert f.client.send.call_args.kwargs['value'] == row.value()
        assert f.ui._editor_state == 'applying'

    def test_quality_gesture_commits_once_and_waits_for_render_confirmation(self):
        f = self.fixture
        row = f.ui.quality_rows['total']
        slider = row.slider
        with mock.patch.object(f.ui, '_refresh_editor_state', wraps=f.ui._refresh_editor_state) as refresh:
            slider._on_down(SimpleNamespace(x=25))
            slider._on_drag(SimpleNamespace(x=70))
            refresh.assert_not_called()
            f.client.send.assert_not_called()
            slider._on_up(SimpleNamespace(x=70))
        f.client.send.assert_called_once()
        assert f.client.send.call_args.args == ('quality',)
        assert f.ui._pending_quality['quality']['total'] == row.value()
        assert f.ui._editor_state == 'applying'


def test_shared_feedback_does_not_compose_in_commit_callback():
    app = app_stub()
    app._shared_interim = mock.Mock(side_effect=AssertionError('must not compose on Tk'))
    for _ in range(20):
        app._shared_feedback()
    app._shared_interim.assert_not_called()
    assert app._shared_revision == 20


def test_compare_async_completion_clears_wait_and_rechecks_latest_settings():
    app = app_stub()
    app.display_view = lambda **kw: App.display_view(app, **kw)
    app._guidance_context = app._hold_original = False
    app.view_var = SimpleNamespace(get=lambda: 'compare')
    app._canvas_size = lambda: (48, 80)
    app._blit_split = mock.Mock()
    source = np.full((80, 48, 3), 40, np.uint8)
    raw = np.full_like(source, 120)
    app._source_cache_get = lambda frame: source
    app._cached_dlss = app._cached_display_dlss = lambda frame: raw
    settings = {'output_mix': .2}
    app._collect_settings = lambda: dict(settings)
    app.display_view()
    wait_until(app._local_composition_job.ready)
    assert app._dlss_pending
    # A new value arrives before the previous completed result is consumed.
    settings['output_mix'] = .7
    app._poll_local_composition()
    wait_until(app._local_composition_job.ready)
    app._poll_local_composition()
    np.testing.assert_array_equal(app._split_dlss,
        compose_preview_frame(source, raw, output_mix=.7))
    assert not app._dlss_pending
    assert not app._local_composition_busy
    app._clear_preview_wait.assert_called()


def test_legacy_output_edit_pauses_transport_but_keeps_inference_cache():
    app = app_stub()
    app.playing = True
    app.pause = mock.Mock(side_effect=lambda: setattr(app, 'playing', False))
    app._cache_clear = mock.Mock()
    app._update_dlss_control_states = mock.Mock()
    app._schedule_settings_save = mock.Mock()
    app.view_var = SimpleNamespace(get=lambda: 'compare')
    app.on_output_settings_change()
    app.pause.assert_called_once()
    app._cache_clear.assert_not_called()
    app._show_preview_wait.assert_called()
    assert app.root.after.call_args.args[0] == 120


def test_shared_interim_composition_is_nonblocking_and_discards_old_revision():
    from tests.test_preview_feedback import app_stub as shared_stub, renderer
    from dlss5tool import render_cache as rc
    from dlss5tool.shared_render_preview import compose_sdr_rgba
    app = shared_stub()
    config = {'frame_generation_multiplier': 2, 'output_mix': .25}
    app._shared_config = lambda: dict(config)
    base = rc.RenderSession('source', {'frame_generation_multiplier': 1,
        'output_mix': 1, 'output_size': None}, 100000, renderer=renderer)
    entered, release = threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return compose_sdr_rgba(*args, **kwargs)
    try:
        base.wait(0, threading.Event())
        app._render_cache_manager = SimpleNamespace(base=base)
        app._shared_paint = mock.Mock()
        # Instrument the direct RGBA path, now that redundant BGR roundtrips
        # have been removed. The retirement/non-blocking assertions are unchanged.
        with mock.patch('dlss5tool.shared_render_preview.compose_sdr_rgba', side_effect=slow):
            try:
                assert not app._shared_interim()
                assert entered.wait(1)
                config['output_mix'] = .75
                app._shared_revision = 2
                assert not app._shared_interim()
                app._shared_paint.assert_not_called()
            finally:
                release.set()
            wait_until(app._shared_interim_job.ready)
            assert app._shared_interim()
        assert app._shared_display_config['output_mix'] == .75
        app._shared_paint.assert_called_once()
        assert app._shared_interim()
        app._shared_paint.assert_called_once()  # No redundant waiting-frame repaint.
        app._preview_zoom = 2
        assert app._shared_interim()
        assert app._shared_paint.call_count == 2  # Display-only gestures still work.
    finally:
        release.set()
        base.close()


def test_shared_result_does_not_paint_over_realtime_workspace():
    app = app_stub()
    app._workbench_mode = 'realtime'
    app._shared_ready = mock.Mock(side_effect=AssertionError('inactive mode'))
    assert not app._shared_display()
    app._shared_ready.assert_not_called()
