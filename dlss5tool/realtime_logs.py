"""User-facing summaries only; raw protocol events stay in the diagnostic journal."""
from dlss5tool.i18n import tr, tr_for


_NATIVE_ERRORS = {
    'No active session': 'no_session',
    'Invalid or replaced target window': 'target_changed',
    'Command belongs to an expired session': 'expired',
    'Only one frame generation effect per chain': 'fg_conflict',
    'Emergency stop hotkey is occupied; use windowed output or release Ctrl+Alt+F10': 'stop_hotkey',
    'Emergency stop hotkey unavailable; configure shortcuts or use windowed output': 'stop_hotkey',
    'AMD optical flow SDK is not present in this build; choose NVOF or explicitly None': 'amd_flow',
    'Parameter is unavailable or requires a session restart; no live change applied': 'restart',
    'Cannot enqueue scaling start': 'start_failed',
}
_NATIVE_LOCALIZED = ('hdr_source', 'hdr_display', 'hdr_capture', 'ngx_restart', 'nr',
                     'fg', 'capture', 'permission', 'source_closed', 'flow')


def compact(text, limit=500):
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[:limit] + '…'


def native_message(event):
    """Translate known host failures, preserving unknown text and error codes."""
    raw = str(event.get('message') or '')
    key = _NATIVE_ERRORS.get(raw)
    if key is None:
        key = next((k for k in _NATIVE_LOCALIZED if raw == tr_for('zh_CN', 'realtime.native.' + k)), None)
    message = tr('realtime.native.' + key) if key else compact(raw)
    if not message:
        message = tr('realtime.host_exited') if event.get('event') == 'exited' else tr('realtime.log.failed')
    codes = ', '.join(f'{key}={event[key]}' for key in ('code', 'hresult', 'system_error', 'returncode')
                      if key in event and event[key] is not None)
    return message + (tr('realtime.log.error_code', code=compact(codes, 150)) if codes else '')


def event_summary(event):
    """Suppress ACKs, telemetry and protocol internals; never infer rendering success."""
    kind = event.get('event')
    if kind == 'ready':
        names = {'stop': 'stop', 'compare': 'compare', 'profiler': 'profiler', 'parameters': 'overlay_parameters'}
        failed = [tr('realtime.' + names[key]) if key in names else compact(key, 40)
                  for key, ok in event.get('hotkeys', {}).items() if not ok]
        if failed:
            return tr('realtime.log.ready') + ' ' + tr('realtime.log.hotkeys', actions=', '.join(failed))
        return tr('realtime.log.ready')
    if kind == 'devices':
        return tr('realtime.log.devices', monitors=len(event.get('monitors', [])),
                  adapters=sum(not a.get('software', False) for a in event.get('adapters', [])))
    if kind == 'catalog':
        return tr('realtime.catalog_loaded', count=len(event.get('effects', [])))
    if kind in ('notice', 'log'):
        message = compact(event.get('message', ''))
        return tr('realtime.log.engine', message=message) if message else None
    return None
