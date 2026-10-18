"""Exact device choice and owner-thread lifetime; no real GPU needed."""
import ctypes
import threading
import time
from unittest import mock

import numpy as np
import pytest

from dlss5tool import residual_composition as rc
from dlss5tool.preview_jobs import LatestPreviewJob


def until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(.002)


def test_persistent_worker_reuses_thread_and_cleans_up_on_owner():
    calls, cleanup = [], []
    job = LatestPreviewJob(persistent=True, cleanup=lambda: cleanup.append(threading.get_ident()))
    try:
        for i in range(8):
            job.request(i, lambda: calls.append(threading.get_ident()) or len(calls))
            until(job.ready)
        assert len(set(calls)) == 1
        assert cleanup == []
        job.invalidate()
        until(lambda: len(cleanup) == 1)
        assert cleanup == [calls[0]]
        job.request('new', lambda: 9)
        until(job.ready)
    finally:
        job.close()
        until(lambda: not job.is_alive())
    assert cleanup == [calls[0], calls[0]]
    assert job.request('closed', lambda: pytest.fail('closed worker')) is None


def test_invalidation_and_close_do_not_release_active_device_or_publish_old_result():
    entered, leave = threading.Event(), threading.Event()
    cleanup = []
    job = LatestPreviewJob(persistent=True, cleanup=lambda: cleanup.append(threading.get_ident()))
    def slow():
        entered.set()
        assert leave.wait(3)
        return 42
    job.request('old', slow)
    assert entered.wait(1)
    job.invalidate()
    job.close()
    assert cleanup == []
    leave.set()
    until(lambda: not job.is_alive())
    assert len(cleanup) == 1
    assert not job.ready()


def test_idle_releases_resources_without_killing_worker():
    cleanup = []
    job = LatestPreviewJob(persistent=True, idle_seconds=.02, cleanup=lambda: cleanup.append(1))
    try:
        job.request(0, lambda: 'pixels')
        until(job.ready)
        until(lambda: cleanup == [1])
        assert job.is_alive()
        time.sleep(.03)
        assert cleanup == [1]
        assert job.request(0, None) == 'pixels'
    finally:
        job.close()
        until(lambda: not job.is_alive())


def test_adapter_resolution_matches_nr_policy_and_never_substitutes_missing_choice():
    from dlss5tool import dlss_engine
    records = [dict(id='A', luid_high=0, luid_low=1), dict(id='B', luid_high=-1, luid_low=2)]
    with mock.patch.object(rc, '_native_state', threading.local()), \
            mock.patch.object(dlss_engine, 'available_render_adapters', return_value=records) as scan:
        assert rc._composition_adapter({}) == (0, 1)
        assert rc._composition_adapter({}) == (0, 1)
        assert scan.call_count == 1
        assert rc._composition_adapter({'render_gpu': 'B'}) == (-1, 2)
        with pytest.raises(ValueError):
            rc._composition_adapter({'render_gpu': 'missing'})
        assert rc._composition_adapter({'_composition_adapter': records[1]}) == (-1, 2)
        rc.release_native_composer()
        rc._composition_adapter({'render_gpu': 'B'})
        assert scan.call_count == 4


def test_exact_bridge_creation_and_device_switch():
    lib = mock.Mock()
    lib.dlss5_quality_create_on_adapter.side_effect = [10, 11]
    current = [(0, 7)]
    def actual(handle, high, low):
        ctypes.cast(high, ctypes.POINTER(ctypes.c_int32))[0] = current[0][0]
        ctypes.cast(low, ctypes.POINTER(ctypes.c_uint32))[0] = current[0][1]
        return 1
    lib.dlss5_quality_adapter.side_effect = actual
    with mock.patch.object(rc, '_native_state', threading.local()), \
            mock.patch.object(rc, '_native_library_path', return_value='quality.dll'), \
            mock.patch.object(rc.ctypes, 'CDLL', return_value=lib):
        a = rc._native_bridge((0, 7))
        assert rc._native_bridge((0, 7)) is a
        current[0] = (-1, 8)
        b = rc._native_bridge((-1, 8))
        assert b.adapter_luid == (-1, 8)
        lib.dlss5_quality_destroy.assert_called_once_with(10)
        lib.dlss5_quality_create.assert_not_called()
        rc.release_native_composer()
        assert lib.dlss5_quality_destroy.call_count == 2


@pytest.mark.parametrize('old_library', [True, False])
def test_old_dll_and_wrong_luid_are_not_accepted(old_library):
    lib = mock.Mock()
    if old_library:
        del lib.dlss5_quality_create_on_adapter
    else:
        lib.dlss5_quality_create_on_adapter.return_value = 10
        lib.dlss5_quality_adapter.return_value = 1  # Returns default 0/0, not requested.
    with mock.patch.object(rc, '_native_state', threading.local()), \
            mock.patch.object(rc, '_native_library_path', return_value='old.dll'), \
            mock.patch.object(rc.ctypes, 'CDLL', return_value=lib):
        assert rc._native_bridge((0, 7)) is None
        lib.dlss5_quality_create.assert_not_called()
        if not old_library:
            lib.dlss5_quality_destroy.assert_called_once_with(10)


def test_missing_selected_adapter_falls_back_to_cpu():
    source = np.full((8, 8, 3), 30, np.uint8)
    output = np.full_like(source, 60)
    with mock.patch.object(rc, '_composition_adapter', side_effect=ValueError('missing')), \
            mock.patch.object(rc, '_native_compose') as native:
        result = rc.compose(source, output, {'nr_quality': {'total': .5}})
    native.assert_not_called()
    assert np.array_equal(result, np.full_like(source, 45))
