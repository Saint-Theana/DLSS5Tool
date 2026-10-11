"""Passive start checks and chain summaries; never load DLLs or capture pixels."""
from dataclasses import dataclass
from pathlib import Path

from dlss5tool import mod_paths
from dlss5tool.i18n import tr
from dlss5tool.realtime import NR
from dlss5tool.realtime_labels import effect_title
from dlss5tool.optical_flow_contract import REALTIME_METHODS


@dataclass(frozen=True)
class StartIssue:
    code: str
    route: str
    message: str
    blocking: bool = True
    detail: str = ''
    effect_index: int | None = None


def chain_summary(effects, catalog=None, *, max_items=4):
    """Compact ordered summary, with the unabridged form available on demand."""
    catalog = catalog or {}
    parts = []
    aliases = {'DLSS': 'DLSS SR', 'DLSSFG': 'DLSS FG'}
    for effect in effects:
        name = effect.get('name', '')
        if name.replace('/', '\\') == NR:
            passes = effect.get('parameters', {}).get('multiPass', 1)
            try:
                count = float(passes)
                value = str(int(count)) if count in (1, 2, 3) else '?'
            except (TypeError, ValueError, OverflowError):
                value = '?'
            label = tr('realtime.summary.nr_single') if value == '1' else tr('realtime.summary.nr_passes', count=value)
        else:
            label = aliases.get(name.replace('\\', '/').split('/')[0], effect_title(name, catalog.get(name)))
        if max_items is not None and len(label) > 28:
            label = label[:27] + '…'
        parts.append(label)
    if not parts:
        return tr('realtime.summary.empty')
    if max_items is not None and len(parts) > max_items:
        parts = parts[:max_items] + [tr('realtime.summary.more', count=len(parts) - max_items)]
    return ' → '.join(parts)


def check_start(config, selected, *, settings, catalog, host, ready=None,
                runtime_selection=None, target_state=None, devices=None):
    """Check known blockers. Unknown driver/feature availability stays advisory.

    config is already validated. ready and runtime_selection must belong to the
    current host generation; the UI discards stale handshake information.
    """
    issues = []
    def add(code, route, *, blocking=True, detail='', index=None, **values):
        issues.append(StartIssue(code, route, tr('realtime.preflight.' + code, **values),
                                 blocking, detail, index))
    if not selected:
        add('target', 'target')
    elif target_state == 'missing':
        add('target_gone', 'target')
    elif target_state == 'minimized':
        add('target_minimized', 'target', blocking=False)
    if not Path(host).is_file():
        add('host', 'diagnostics', detail=str(host))
    if ready is None:
        add('handshake', 'check', blocking=False)
    elif not config['windowed']:
        registered = ready.get('stop_hotkey_registered', ready.get('hotkeys', {}).get('stop'))
        if registered is False:
            add('hotkey', 'display')
        elif registered is None:
            add('handshake', 'check', blocking=False)
    if not catalog:
        add('catalog_wait', 'check', blocking=False)
    names = [e['name'].replace('/', '\\') for e in config['effects']]
    normalized_catalog = {name.replace('/', '\\'): item for name, item in catalog.items()}
    if sum(name.startswith(('DLSSFG\\', 'XeSSFG\\')) for name in names) > 1:
        add('fg_conflict', 'effects')
    for index, name in enumerate(names):
        descriptor = normalized_catalog.get(name)
        if catalog and (descriptor is None or not descriptor.get('available', True)):
            add('effect_unavailable', 'effects', index=index,
                effect=effect_title(name), detail=name)
    # NR is loaded from an exact file by the native host; feature libraries may
    # also be resolved by NGX, so an absent local SR/FG DLL is only a warning.
    selection = runtime_selection or mod_paths.runtime_info(settings)
    nr_path = Path(selection['path'])
    feature_root = Path(selection.get('feature_directory') or settings.get('realtime_runtime_directory') or nr_path.parent)
    if NR in names:
        if not nr_path.is_file():
            add('nr_missing', 'nr_runtime', detail=str(nr_path))
        elif selection.get('ambiguous') or selection.get('fallback'):
            add('nr_fallback', 'nr_runtime', blocking=False, detail=str(nr_path))
    missing = []
    for family, filename in (('DLSS\\', 'nvngx_dlss.dll'), ('DLSSFG\\', 'nvngx_dlssg.dll')):
        if any(name.startswith(family) for name in names) and not (feature_root / filename).is_file():
            missing.append(filename)
    if missing:
        add('features', 'runtime', blocking=False, files=', '.join(missing), detail=str(feature_root))
    if config['hdr'] and config['capture_method'] != 0:
        add('hdr_capture', 'display')
    if config['hdr']:
        from dlss5tool.parameter_contract import RESIDUAL, capabilities
        for index, effect in enumerate(config['effects']):
            if effect['name'].replace('/', '\\') != NR:
                continue
            params = effect.get('parameters', {})
            enabled = params.get('enableResidualControls') or params.get('enableInputResolutionScaling')
            if enabled and any(params.get(k, 1) != 1 for k in RESIDUAL) and not capabilities(
                    mode='realtime', hdr=True, ready=ready)['residual']:
                add('hdr_residual', 'effects', index=index)
            if params.get('enableInputResolutionScaling') and params.get('inputResolutionPercent', 100) != 100:
                add('hdr_resolution', 'effects', index=index)
    # A snapshot is evidence of enumeration, not proof of hardware backend support.
    # Unknown/stale snapshots must not invent a compatibility failure.
    if devices is not None:
        adapters = devices.get('adapters')
        monitors = devices.get('monitors')
        if adapters is not None and config['gpu_index'] >= 0:
            adapter = next((a for a in adapters if a['index'] == config['gpu_index']), None)
            if adapter is None:
                add('gpu_missing', 'display')
            elif adapter.get('software'):
                add('gpu_software', 'display')
            elif any(n.startswith(('DLSS\\', 'DLSSNR\\', 'DLSSFG\\')) for n in names) and adapter.get('vendor') not in (None, 0x10de):
                add('gpu_vendor', 'display')
        if monitors is not None:
            chosen = next((m for m in monitors if m['id'] == config['monitor_id']), None)
            # Explicit output monitor selection applies to fullscreen only.
            if not config['windowed'] and config['monitor_mode'] == 3 and chosen is None:
                add('monitor_missing', 'display')
            if config['hdr'] and monitors and all(m.get('hdr_active') is False for m in monitors):
                add('hdr_display', 'display')
        capabilities = devices.get('capabilities', {})
        for index, effect in enumerate(config['effects']):
            method = effect.get('parameters', {}).get('opticalFlowMethod', 0)
            capability, backend = REALTIME_METHODS.get(method, (None, None))
            if capability and capabilities.get(capability) is False:
                add('flow_unavailable', 'effects', index=index,
                    backend=backend)
    return issues
