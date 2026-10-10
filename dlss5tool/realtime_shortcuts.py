"""Portable shortcut names; local preferences, never part of effect presets."""
from dlss5tool.i18n import tr

DEFAULT_HOTKEYS = {'stop': 'Ctrl+Alt+F10', 'compare': 'Ctrl+Alt+C',
                   'profiler': 'Ctrl+Alt+F', 'parameters': 'Ctrl+Alt+P'}
ACTION_LABELS = {'stop': 'realtime.stop', 'compare': 'realtime.compare',
                 'profiler': 'realtime.profiler', 'parameters': 'realtime.overlay_parameters'}
MODIFIERS = {'Ctrl': 2, 'Alt': 1, 'Shift': 4}
KEYS = {**{chr(n): n for n in range(65, 91)}, **{str(n): 48 + n for n in range(10)},
        **{f'F{n}': 111 + n for n in range(1, 25) if n != 12}}


def parse_hotkey(text):
    """Canonical label, Win32 modifiers and VK; deliberately small safe grammar."""
    if not isinstance(text, str) or len(text) > 48:
        raise ValueError(tr('realtime.shortcuts.invalid'))
    parts = [p.strip().upper() for p in text.split('+')]
    modifiers, key = parts[:-1], parts[-1]
    if (key not in KEYS or not modifiers or len(modifiers) != len(set(modifiers))
            or set(modifiers) - {'CTRL', 'ALT', 'SHIFT'}
            or not set(modifiers) & {'CTRL', 'ALT'}
            or (key == 'F4' and 'ALT' in modifiers and 'CTRL' not in modifiers)):
        raise ValueError(tr('realtime.shortcuts.invalid'))
    selected = [name for name in MODIFIERS if name.upper() in modifiers]
    return '+'.join([*selected, key]), sum(MODIFIERS[n] for n in selected), KEYS[key]


def validate_hotkeys(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_HOTKEYS):
        raise ValueError(tr('realtime.shortcuts.invalid'))
    result = {name: parse_hotkey(value[name])[0] for name in DEFAULT_HOTKEYS}
    if len(set(result.values())) != len(result):
        raise ValueError(tr('realtime.shortcuts.duplicate'))
    return result


def native_hotkeys(value):
    return {name: dict(zip(('label', 'modifiers', 'key'), parse_hotkey(chord)))
            for name, chord in validate_hotkeys(value).items()}


def effective_bindings(ready=None):
    """Only advertise labels reported by the host; legacy hosts use fixed keys."""
    try:
        return validate_hotkeys((ready or {}).get('hotkey_bindings', DEFAULT_HOTKEYS))
    except ValueError:
        return dict(DEFAULT_HOTKEYS)
