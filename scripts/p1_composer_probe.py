"""Compare existing ephemeral/persistent composer lifetimes without app edits."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import diagnose_composer_lifetime as lifetime
from dlss5tool import residual_composition as composition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', type=Path, required=True)
    args = parser.parse_args()
    if not (args.task/'TASK.md').is_file():
        raise ValueError('Register task first')
    results = []
    invoke, compose = lifetime.CountedCall.__call__, composition.compose
    # Two opposite orders reduce the risk of treating a one-time driver warmup
    # as a persistent-worker improvement. Same 1000x1000 data in every case.
    for index, persistent in enumerate((False, True, True, False)):
        calls, frames = {}, []
        def counted(self, *values):
            name = self.function.__name__
            started = time.perf_counter()
            try:
                return invoke(self, *values)
            finally:
                calls.setdefault(name, []).append((time.perf_counter()-started)*1000)
        def composed(*values, **kwargs):
            started = time.perf_counter()
            try:
                return compose(*values, **kwargs)
            finally:
                frames.append((time.perf_counter()-started)*1000)
        with mock.patch.object(lifetime.CountedCall,'__call__',counted), \
                mock.patch.object(composition,'compose',composed):
            report = lifetime.run(SimpleNamespace(native=True,cycles=6,
                persistent_thread=persistent,verify_pixels=False,release_each_cycle=False))
        results.append({'order':index,'persistent_thread':persistent,
            'frame_call_ms':frames,'warm_frame_mean_ms':statistics.mean(frames[1:]),
            'native_api_ms':calls,'before_probe_cleanup':report['before_probe_cleanup'],
            'after_probe_cleanup':report['after_probe_cleanup']})
    destination=args.task/'composer-abba.json'
    with destination.open('x',encoding='utf-8') as stream:
        json.dump(results,stream,indent=2)
    print(json.dumps([{key:value for key,value in row.items()
        if key in ('order','persistent_thread','warm_frame_mean_ms','before_probe_cleanup')}
        for row in results]),flush=True)


if __name__=='__main__':
    main()
