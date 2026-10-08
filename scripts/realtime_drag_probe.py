"""Profile one mocked realtime pane, without starting the full app or capture."""
import cProfile
import json
from pathlib import Path
import pstats
import statistics
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_realtime_inspector import RealtimeInspectorTests


def main():
    fixture = RealtimeInspectorTests('test_all_parameters_kept_and_control_types_match_metadata')
    fixture.setUp()
    try:
        fixture.catalog()
        ui, root = fixture.ui, fixture.root
        root.title('Isolated realtime drag measurement')
        root.geometry('1280x800')
        root.update()
        # Keep the measurement to layout; no periodic host/session polling.
        ui.window.after_cancel(ui._after)
        ui._after = None
        fixture.client.reset_mock()
        samples = {}
        profile = cProfile.Profile()

        def measure(name, action):
            elapsed = []
            for index in range(12):
                started = time.perf_counter()
                action(index)
                root.update_idletasks()
                elapsed.append((time.perf_counter() - started) * 1000)
            samples[name] = dict(median_ms=round(statistics.median(elapsed), 2),
                                 max_ms=round(max(elapsed), 2), steps=len(elapsed))

        initial_width = ui.inspector.winfo_width()
        ui._splitter_start(SimpleNamespace(x_root=600))
        move = lambda i: ui._splitter_move(SimpleNamespace(x_root=600 - (i % 20) * 4))
        profile.enable()
        measure('splitter_cold', move)
        profile.disable()
        measure('splitter_warm', move)
        unchanged_during_drag = ui.inspector.winfo_width() == initial_width
        started = time.perf_counter()
        ui._splitter_end()
        root.update_idletasks()
        release_ms = round((time.perf_counter()-started)*1000, 2)
        ui._splitter_reset()
        ui.presets_section.toggle()
        root.update_idletasks()
        measure('vertical_scroll', lambda i: ui.stage_canvas.yview_moveto((i % 20) / 20))
        stats = pstats.Stats(profile)
        total_profile_ms = round(stats.total_tt * 1000, 2)
        hotspots = []
        for (filename, line, name), (primitive, calls, own, cumulative, _) in sorted(
                stats.stats.items(), key=lambda item: item[1][3], reverse=True):
            if 'dlss5tool' in filename:
                hotspots.append(dict(file=Path(filename).name, line=line, function=name,
                                     calls=calls, own_ms=round(own * 1000, 2),
                                     cumulative_ms=round(cumulative * 1000, 2)))
            if len(hotspots) >= 10:
                break
        print(json.dumps(dict(samples=samples, cold_profile_ms=total_profile_ms, hotspots=hotspots,
                              unchanged_during_drag=unchanged_during_drag, release_ms=release_ms,
                              native_started=fixture.client.start.called,
                              commands_sent=fixture.client.send.call_count), ensure_ascii=False, indent=2))
        assert not fixture.client.start.called and not fixture.client.send.called
    finally:
        fixture.tearDown()


if __name__ == '__main__':
    main()
