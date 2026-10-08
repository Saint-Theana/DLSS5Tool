"""Bounded, redacted support snapshots. Quick exports never start GPU probes."""
from collections import deque
from copy import deepcopy
from datetime import datetime
import json
import math
import os
from pathlib import Path
import platform
import re
import stat
import sys
import tempfile
import time

from dlss5tool import diagnostics, mod_paths
from dlss5tool.app_version import APP_VERSION
from dlss5tool.i18n import tr_for


def bounded(value, depth=0):
    if depth > 14:
        return '[depth limit]'
    if isinstance(value, dict):
        result = {str(k): bounded(v, depth + 1) for k, v in list(value.items())[:256]}
        if len(value) > 256:
            result['_omitted_fields'] = len(value) - 256
        return result
    if isinstance(value, (list, tuple, deque)):
        result = [bounded(v, depth + 1) for v in list(value)[:600]]
        if len(value) > 600:
            result.append({'omitted_items': len(value) - 600})
        return result
    if isinstance(value, str):
        return value if len(value) <= 16384 else value[:16384] + '\n[truncated]'
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:1024]


class EventJournal:
    """Telemetry cannot evict errors or lifecycle events. No disk writes."""
    def __init__(self):
        self.errors = deque(maxlen=96)
        self.lifecycle = deque(maxlen=160)
        self.logs = deque(maxlen=160)
        self.latest = {}
        self.dropped = {'errors': 0, 'lifecycle': 0, 'logs': 0}

    def append(self, event):
        item = bounded({'time': time.time(), **event})
        kind = item.get('event', '')
        error_message = kind in ('ui_status', 'log') and re.search(
            r'失败|错误|超时|无法|未构建|\berror\b|\bfail(?:ed|ure)?\b|\binvalid\b|\bmissing\b|\bcannot\b|not built|timed?\s*out',
            str(item.get('message', '')), re.I)
        if kind in ('catalog', 'devices', 'status', 'gpu_load') or (kind == 'ack' and item.get('ok')):
            # Catalog details remain in the installed effects; don't duplicate
            # hundreds of descriptors in the journal on every discovery.
            if kind == 'catalog':
                item = {'event': kind, 'time': item['time'], 'effect_count': len(event.get('effects', []))}
            self.latest[kind] = item
            return
        bucket = ('errors' if error_message or kind in ('error', 'fatal', 'exited', 'ui_error', 'recovery') or
                  (kind == 'ack' and not item.get('ok')) else 'logs' if kind == 'log' else 'lifecycle')
        target = getattr(self, bucket)
        if len(target) == target.maxlen:
            self.dropped[bucket] += 1
        # Bound an individual event as well as the number of events.
        if len(json.dumps(item, ensure_ascii=False)) > 12000:
            item = {k: v for k, v in item.items() if k in ('time', 'event', 'run_id', 'id', 'message', 'state')}
            item['truncated'] = True
        target.append(item)

    def snapshot(self):
        return deepcopy({'errors': list(self.errors), 'lifecycle': list(self.lifecycle),
                         'logs': list(self.logs), 'latest': self.latest, 'dropped': self.dropped})


_WINDOWS_PATH = re.compile(r'(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n\t"<>|]+')
_POSIX_PATH = re.compile(r'(?<![\w:/])/(?:[^\s/"<>]+/)+[^\s"<>]*')


class Redactor:
    def __init__(self, context):
        self.titles = set()
        self._find_titles(context)

    def _find_titles(self, value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('title', 'window_title') and isinstance(item, str) and item:
                    self.titles.add(item)
                self._find_titles(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._find_titles(item)

    def text(self, text):
        for title in sorted(self.titles, key=len, reverse=True):
            text = text.replace(title, '%WINDOW_TITLE%')
            text = text.replace(json.dumps(title, ensure_ascii=False)[1:-1], '%WINDOW_TITLE%')
        def shorten(match):
            # Preserve the last component/error suffix, not user directories.
            return '%PATH%/' + re.split(r'[\\/]', match[0])[-1]
        return _POSIX_PATH.sub(shorten, _WINDOWS_PATH.sub(shorten, text))

    def clean(self, value):
        if isinstance(value, dict):
            return {str(k): '%REDACTED%' if str(k).lower() in ('password', 'token', 'api_key') else
                    '%WINDOW_TITLE%' if k in ('title', 'window_title') and v else self.clean(v)
                    for k, v in value.items()}
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        return self.text(value) if isinstance(value, str) else value


def read_native_logs(directory, limit=256 * 1024):
    """Fixed filenames only; no recursion, following junctions, or whole reads."""
    root = Path(directory)
    result = []
    for name in ('realtime.3.log', 'realtime.2.log', 'realtime.1.log', 'realtime.log'):
        path = root / name
        try:
            for part in (root.parent, root, path):
                info = part.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise OSError('linked log path omitted')
            if not stat.S_ISREG(info.st_mode):
                raise OSError('not a regular log file')
            with path.open('rb') as handle:
                handle.seek(max(0, info.st_size - limit))
                text = handle.read(limit).decode('utf-8', errors='replace')
            result.append({'file': name, 'bytes': info.st_size, 'truncated': info.st_size > limit, 'text': text})
        except FileNotFoundError:
            continue
        except OSError as error:
            result.append({'file': name, 'error': str(error)})
    return result


def runtime_summary(settings):
    info = mod_paths.runtime_info(settings)
    path = Path(info['path'])
    result = {**info, 'selection_kind': 'path-discovery, not GPU compatibility selection'}
    try:
        result.update(exists=path.is_file(), file_version=diagnostics._windows_file_version(str(path)))
        if result['exists']:
            result['bytes'] = path.stat().st_size
    except OSError as error:
        result['error'] = str(error)
    return result


def suggested_name(mode='local', deep=False):
    return f'DLSS5Tool-{mode}-{"deep" if deep else "diagnostic"}-{datetime.now():%Y%m%d-%H%M%S}.log'


def write_report(output_path, context, on_progress=None, *, deep=False):
    """Called off the UI thread with an immutable snapshot; writes atomically."""
    context = deepcopy(context)
    output = Path(output_path).absolute()
    if not output.parent.is_dir():
        raise FileNotFoundError(str(output.parent))
    def progress(completed, stage):
        if on_progress:
            on_progress(completed, 6, stage)
    progress(0, 'collecting')
    private_io = context.pop('_diagnostic_io', {})
    runtime = runtime_summary(context.get('settings', {}))
    native_logs = read_native_logs(private_io['realtime_logs']) if private_io.get('realtime_logs') else []
    language = context.get('settings', {}).get('ui_language')
    redactor = Redactor(context)
    report = {'schema': 1, 'generated': datetime.now().astimezone().isoformat(timespec='seconds'),
              'app_version': APP_VERSION, 'workbench_mode': context.get('workbench_mode', 'local'),
              'diagnostic_kind': 'deep' if deep else 'snapshot-no-GPU-probes',
              'environment': {'system': platform.platform(), 'python': platform.python_version(),
                              'packaged': bool(getattr(sys, 'frozen', False))},
              'nr_runtime': runtime, 'context': bounded(context), 'realtime_native_logs': native_logs,
              'privacy': tr_for(language, 'diagnostics.privacy')}
    if deep:
        # Keep the old full local diagnostic path, but never write its raw
        # intermediate report to the user's final destination.
        with tempfile.TemporaryDirectory(prefix='dlss5-support-') as work:
            legacy = Path(work) / 'deep.log'
            diagnostics.write_diagnostic_report(legacy, context, on_progress=on_progress)
            with legacy.open('rb') as handle:
                data = handle.read(8 * 1024 * 1024 + 1)
            report['deep_report'] = data[:8 * 1024 * 1024].decode('utf-8', errors='replace')
            report['deep_report_truncated'] = len(data) > 8 * 1024 * 1024
            report['deep_scope'] = tr_for(language, 'diagnostics.deep_scope')
    progress(5, 'saving')
    clean = redactor.clean(report)
    text = json.dumps(clean, ensure_ascii=False, indent=2, allow_nan=False)
    if output.suffix.lower() != '.json':
        text = tr_for(language, 'diagnostics.report_title') + '\n' + '=' * 72 + '\n' + text
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=output.parent, prefix='.dlss5-diagnostic-', suffix='.tmp', delete=False) as handle:
            temp_name = handle.name
            handle.write(text)
        os.replace(temp_name, output)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    progress(6, 'done')
    return {'path': str(output), 'kind': report['diagnostic_kind']}
