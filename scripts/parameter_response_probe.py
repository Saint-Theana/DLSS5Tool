"""Synthetic Tk drag timing; no native capture, models, or user media.

Run each --mode in a fresh process to isolate Tcl teardown.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('local', 'realtime', 'compose'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'compose':
        compose_probe(args.output)
        return
    if args.mode == 'local':
        from tests.test_parameter_unification import LocalAdjustmentTests
        fixture = LocalAdjustmentTests()
        fixture.setUp()
        editor = fixture.editor
        row = editor.rows['nr_residual.residualSaturation']
        refresh = 'refresh'
    else:
        from tests.test_realtime_inspector import RealtimeInspectorTests
        fixture = RealtimeInspectorTests()
        fixture.setUp()
        fixture.running()
        editor = fixture.ui
        row = editor.parameter_rows['intensity']
        refresh = '_refresh_editor_state'
    try:
        fixture.root.update()
        slider = row.slider
        samples = []
        with mock.patch.object(editor, refresh, wraps=getattr(editor, refresh)) as repaint:
            slider._on_down(SimpleNamespace(x=10))
            for i in range(180):
                event = SimpleNamespace(x=10+(i % 90)/90*max(slider.winfo_width()-20, 1))
                started = time.perf_counter()
                slider._on_drag(event)
                fixture.root.update_idletasks()
                samples.append((time.perf_counter()-started)*1000)
            drag_refreshes = repaint.call_count
            slider._on_up(event)
        ordered = sorted(samples)
        report = dict(mode=args.mode, samples=len(samples), p50_ms=ordered[len(ordered)//2],
                      p95_ms=ordered[int(len(ordered)*.95)], max_ms=max(samples),
                      panel_refreshes_during_drag=drag_refreshes, final_value=row.value())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
    finally:
        fixture.tearDown()


def compose_probe(output):
    import tkinter as tk
    import numpy as np
    from dlss5tool.gui import compose_preview_frame
    from dlss5tool.preview_jobs import LatestPreviewJob
    root = tk.Tk()
    root.withdraw()
    # 1088x1920 portrait input at 2x, as in the reported screenshot.
    source = np.full((3840, 2176, 3), (70, 110, 160), np.uint8)
    processed = np.full_like(source, (85, 118, 175))
    settings = {'nr_residual': {'residualSaturation': 1.2, 'shadowStructureMultiplier': .65,
                               'reflectionGlowMultiplier': 1.44}}
    ticks = []
    def heartbeat():
        ticks.append(time.perf_counter())
        root.after(10, heartbeat)
    try:
        root.after(0, heartbeat)
        root.update()
        started = time.perf_counter()
        expected = compose_preview_frame(source, processed, settings=settings)
        sync_ms = (time.perf_counter()-started)*1000
        root.update()
        sync_gap = (ticks[-1]-ticks[-2])*1000
        ticks.clear()
        job = LatestPreviewJob()
        started = time.perf_counter()
        assert job.request('test', lambda: compose_preview_frame(source, processed, settings=settings)) is None
        dispatch_ms = (time.perf_counter()-started)*1000
        deadline = time.perf_counter()+30
        while not job.ready():
            root.update()
            time.sleep(.001)
            assert time.perf_counter() < deadline
        result = job.request('test', None)
        np.testing.assert_array_equal(result, expected)
        gaps = sorted((b-a)*1000 for a, b in zip(ticks, ticks[1:]))
        report = dict(mode='compose', resolution=[2176, 3840], synchronous_callback_ms=sync_ms,
                      synchronous_heartbeat_gap_ms=sync_gap, async_dispatch_ms=dispatch_ms,
                      async_heartbeats=len(ticks), async_heartbeat_p95_ms=gaps[int(len(gaps)*.95)],
                      async_heartbeat_max_ms=max(gaps), identical_pixels=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
    finally:
        root.destroy()


if __name__ == '__main__':
    main()
