"""Regressions found while reviewing P0 cleanup and allocation boundaries."""
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest

from dlss5tool import memory_budget as mb, super_resolution as sr
from dlss5tool import dlss_host_process as host


GIB = 1024**3


def memory_with_headroom(size):
    return dict(total_physical_bytes=32*GIB,
                free_physical_bytes=4*GIB+size, free_commit_bytes=20*GIB)


def stubborn_nr():
    session = host._HostSession.__new__(host._HostSession)
    state = dict(alive=True)
    session._closed = False
    session._process = mock.Mock(pid=12345)
    session._process.is_alive.side_effect = lambda: state['alive']
    session._connection = mock.Mock()
    session._child_connection = None
    session._input_memory, session._output_memory = mock.Mock(), mock.Mock()
    session._input_frame = session._output_frame = object()
    session.log_path = 'not-created-review-test.log'
    live = host.ProcessLive.__new__(host.ProcessLive)
    live._session = session
    live.backend, live.max_in_flight, live.supports_async = 'v2', 1, False
    live.adapter_info = {}
    return live, session, state


@pytest.mark.parametrize('mode', ['sdr', 'hdr'])
def test_gui_export_cleanup_keeps_primary_failure_and_retries_failed_owner(mode):
    from dlss5tool import gui
    app = gui.App.__new__(gui.App)
    app.logln = mock.Mock()
    app._guidance_started = mock.Mock()
    app._raise_if_export_cancelled = mock.Mock()
    app._iter_frames = mock.Mock(side_effect=RuntimeError('injected decode failure'))
    live, session, state = stubborn_nr()
    writer, vsr, reader = mock.Mock(), mock.Mock(), mock.Mock()
    reader.read.side_effect = RuntimeError('injected decode failure')
    settings = dict(nvenc_preset='p5', rate_control='quality', quality_profile='high',
                    video_bitrate_mbps=20, super_resolution_scale=2)
    function = (gui.App._export_hdr_video if mode == 'hdr'
                else gui.App._export_sdr_upscaled_video)
    with mock.patch.object(gui, 'require_memory_headroom'), \
            mock.patch.object(gui, 'select_in_flight', return_value=1), \
            mock.patch.object(gui, 'query_gpu_memory', return_value=None), \
            mock.patch.object(gui, 'find_ffmpeg', return_value='unused'), \
            mock.patch.object(gui, 'FFmpegHDRVideoReader', return_value=reader), \
            mock.patch.object(gui, 'FFmpegVideoWriter', return_value=writer), \
            mock.patch.object(gui, 'ProcessSuperResolution', return_value=vsr), \
            mock.patch.object(gui, 'ProcessLive', return_value=live), \
            mock.patch.object(gui, 'release_native_composer') as composer:
        with pytest.raises(RuntimeError, match='injected decode failure') as primary:
            function(app, 'source', dict(is_hdr=True, profile='hdr10_pq'), 'out',
                     2, 24, 128, 128, {}, settings, 0, 1)
    composer.assert_called_once_with()
    vsr.close.assert_called_once_with()
    writer.abort.assert_called_once_with()
    if mode == 'hdr':
        reader.close.assert_called_once_with()
    session._input_memory.close.assert_not_called()
    assert live._session is session
    assert len(app._pending_export_cleanup) == 1
    assert any('尚未退出' in note for note in primary.value.__notes__)
    state['alive'] = False
    app._cleanup_video_export()
    assert not app._pending_export_cleanup
    assert live._session is None
    vsr.close.assert_called_once_with()
    writer.abort.assert_called_once_with()


def test_cleanup_only_failure_is_reported_after_all_resources_are_attempted():
    from dlss5tool.gui import App
    app = App.__new__(App)
    app.logln = mock.Mock()
    first = mock.Mock(side_effect=RuntimeError('first close failed'))
    second = mock.Mock(side_effect=OSError('second close failed'))
    last = mock.Mock()
    with pytest.raises(RuntimeError, match='first close failed'):
        app._cleanup_video_export([('NR', first), ('VSR', second), ('encoder', last)])
    second.assert_called_once_with()
    last.assert_called_once_with()
    assert len(app._pending_export_cleanup) == 2
    first.side_effect = second.side_effect = None
    app._cleanup_video_export()
    assert not app._pending_export_cleanup
    assert first.call_count == second.call_count == 2
    last.assert_called_once_with()


@pytest.mark.parametrize('mode', ['sdr', 'hdr'])
def test_pending_cleanup_prevents_allocating_another_export(mode):
    from dlss5tool import gui
    app = gui.App.__new__(gui.App)
    app.logln = mock.Mock()
    pending = mock.Mock(side_effect=RuntimeError('still closing'))
    app._pending_export_cleanup = [('NR', pending)]
    function = (gui.App._export_hdr_video if mode == 'hdr'
                else gui.App._export_sdr_upscaled_video)
    with mock.patch.object(gui, 'FFmpegVideoWriter') as writer, \
            mock.patch.object(gui, 'ProcessLive') as nr, \
            mock.patch.object(gui, 'ProcessSuperResolution') as vsr:
        with pytest.raises(RuntimeError, match='still closing'):
            function(app, 'source', dict(is_hdr=True, profile='hdr10_pq'), 'out',
                     2, 24, 128, 128, {}, {}, 0, 1)
    for constructor in (writer, nr, vsr):
        constructor.assert_not_called()
    assert app._pending_export_cleanup == [('NR', pending)]


def test_exit_retains_pending_owners_when_retry_still_fails():
    from dlss5tool.gui import App
    app = App.__new__(App)
    app.logln = app.set_status = mock.Mock()
    app._cancel_after = mock.Mock()
    app._diagnosing = app._exporting = app._queue_running = False
    pending = mock.Mock(side_effect=RuntimeError('still closing'))
    app._pending_export_cleanup = [('NR', pending)]
    app.root = mock.Mock()
    app._on_close()
    pending.assert_called_once_with()
    app.set_status.assert_called_with('still closing')
    app.root.destroy.assert_not_called()
    assert app._pending_export_cleanup == [('NR', pending)]


@pytest.mark.parametrize('active_stage', ['sr', 'nr', 'fg'])
def test_enabled_processing_stage_is_charged_before_creation(tmp_path, active_stage):
    from dlss5tool import frame_generation as fg
    source = tmp_path/'input.mp4'
    source.write_bytes(b'synthetic input')
    metadata = dict(is_hdr=False, profile='srgb', color_primaries='bt709')
    inspector = lambda *args, **kwargs: (metadata, Fraction(24), 1920, 1080, 2)
    # A plain 1080p export fits; enabled stages must still be checked before
    # creating owners when their buffers exceed this headroom.
    with mock.patch.object(mb, 'system_memory', return_value=memory_with_headroom(30*1024**2)), \
            mock.patch.object(sr, 'query_gpu_memory', return_value=None), \
            mock.patch.object(fg, 'open_capture') as capture, \
            mock.patch.object(fg, 'NativeStream') as native, \
            mock.patch.object(sr, 'ProcessSuperResolution') as vsr, \
            mock.patch.object(host, 'ProcessLive') as nr:
        with pytest.raises(RuntimeError) as error:
            fg.export_video(source, tmp_path/'output.mp4',
                multiplier=2 if active_stage == 'fg' else 1,
                scale=2 if active_stage == 'sr' else 1, enhance=active_stage == 'nr',
                settings={'intensity': 1}, source_inspector=inspector, log_dir=tmp_path/'logs')
        assert isinstance(error.value.__cause__, MemoryError)
    for constructor in (capture, native, vsr, nr):
        constructor.assert_not_called()


@pytest.mark.parametrize('enhance', [False, True])
def test_plain_export_fits_without_unused_processing_components(tmp_path, enhance):
    from dlss5tool import frame_generation as fg
    source = tmp_path/'input.mp4'
    source.write_bytes(b'synthetic input')
    pixels = np.zeros((128, 128, 3), np.uint8)
    capture = SimpleNamespace(read=mock.Mock(side_effect=[
        (True, pixels), (True, pixels), (False, None)]), release=mock.Mock())
    writers = []
    def writer(output, *args, **kwargs):
        Path(output).write_bytes(b'synthetic encoded result')
        result = mock.Mock()
        writers.append(result)
        return result
    metadata = dict(is_hdr=False, profile='srgb', color_primaries='bt709')
    inspector = lambda *args, **kwargs: (metadata, Fraction(24), 128, 128, 2)
    with mock.patch.object(mb, 'system_memory', return_value=memory_with_headroom(256*1024**2)), \
            mock.patch.object(sr, 'query_gpu_memory', return_value=None), \
            mock.patch.object(fg, 'open_capture', return_value=capture), \
            mock.patch.object(fg, 'FFmpegVideoWriter', side_effect=writer), \
            mock.patch.object(fg, 'NativeStream') as native, \
            mock.patch.object(sr, 'ProcessSuperResolution') as vsr, \
            mock.patch.object(host, 'ProcessLive') as nr:
        report = fg.export_video(source, tmp_path/'output.mp4', multiplier=1,
            enhance=enhance, settings={'output_mix': 0}, source_inspector=inspector,
            log_dir=tmp_path/'logs')
    assert report['status'] == 'complete' and report['real_frames'] == 2
    assert len(writers) == 1 and writers[0].write.call_count == 2
    writers[0].finish.assert_called_once_with()
    writers[0].abort.assert_not_called()
    capture.release.assert_called_once_with()
    for constructor in (native, vsr, nr):
        constructor.assert_not_called()


def test_cached_output_stage_does_not_charge_upstream_sr_or_nr(tmp_path):
    from dlss5tool import frame_generation as fg, video_export
    source = tmp_path/'input.mp4'
    source.write_bytes(b'synthetic input')
    metadata = dict(is_hdr=False, profile='srgb', color_primaries='bt709')
    rgba = np.zeros((1080, 1920, 4), np.uint8)
    upstream = SimpleNamespace(
        metadata={}, wait=mock.Mock(return_value=(rgba, rgba)),
        wait_metadata=mock.Mock(return_value=dict(source_metadata=metadata,
            source_rate='24', width=1920, height=1080, source_frames=1)))
    sink = mock.Mock()
    with mock.patch.object(mb, 'system_memory', return_value=memory_with_headroom(30*1024**2)), \
            mock.patch.object(sr, 'query_gpu_memory', return_value=None), \
            mock.patch.object(video_export, 'compose_sdr_rgba', side_effect=lambda original, processed, **kw: processed), \
            mock.patch.object(sr, 'ProcessSuperResolution') as vsr, \
            mock.patch.object(host, 'ProcessLive') as nr:
        report = fg.export_video(source, None, multiplier=1, scale=4, enhance=True,
            settings={'intensity': 1, '_render_stage': 'output'}, input_session=upstream,
            frame_sink=sink, log_dir=tmp_path/'logs')
    assert report['status'] == 'complete' and report['real_frames'] == 1
    sink.assert_called_once()
    vsr.assert_not_called()
    nr.assert_not_called()


@pytest.mark.parametrize('backend,reaches_allocation', [('legacy', True), ('v2', False)])
def test_host_admission_matches_backend_capacity(backend, reaches_allocation):
    settings = dict(host_backend=backend, host_in_flight=16)
    with mock.patch.object(mb, 'system_memory', return_value=memory_with_headroom(512*1024**2)), \
            mock.patch.object(host, '_open_shared_memory', side_effect=RuntimeError('allocation reached')) as allocate:
        expected = RuntimeError if reaches_allocation else MemoryError
        with pytest.raises(expected):
            host._HostSession(3840, 2160, settings, live_factory=mock.Mock())
    assert allocate.called == reaches_allocation
