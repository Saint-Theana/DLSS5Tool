"""Explicit, lossless first-pass NR transfer, never a rendering-pipeline merge."""
from copy import deepcopy

from dlss5tool.i18n import tr
from dlss5tool.parameter_values import parse_number, format_number
from dlss5tool.realtime import NR, validate_config, nr_extended_range


COMMON_FIELDS = (
    ('style', 'style', 'style'),
    ('intensity', 'intensity', 'strength'),
    ('local_tone', 'localToneStrength', 'local_tone'),
    ('local_struct', 'localStructureStrength', 'local_structure'),
    ('skin_struct', 'skinStructureStrength', 'skin_mask'),
)


def nr_target(config, catalog):
    matches = [(i, e) for i, e in enumerate(config['effects']) if e['name'].replace('/', '\\') == NR]
    if len(matches) != 1:
        raise ValueError(tr('parameter.copy_one_nr'))
    index, effect = matches[0]
    descriptors = {p['name']: p for p in catalog.get(effect['name'], {}).get('parameters', [])}
    if not {'style', 'intensity', 'localToneStrength', 'localStructureStrength', 'skinStructureStrength', 'useAutoMask'} <= descriptors.keys():
        raise ValueError(tr('parameter.copy_metadata'))
    return index, effect, descriptors


def checked(raw, minimum, maximum, label, *, integer=False):
    value = parse_number(raw, percent=not integer)
    if not minimum <= value <= maximum or (integer and not value.is_integer()):
        raise ValueError(tr('parameter.copy_range', name=tr('label.' + label), minimum=minimum, maximum=maximum))
    return int(value) if integer else value


def from_realtime(config, catalog, local_limit):
    _, effect, descriptors = nr_target(config, catalog)
    values = {}
    params = effect.get('parameters', {})
    for local, native, label in COMMON_FIELDS:
        value = params.get(native, descriptors[native]['default'])
        value = checked(value, 0, 2 if local == 'style' else local_limit, label, integer=local == 'style')
        enabled = (None if local == 'style' else
                   bool(params.get('useAutoMask', descriptors['useAutoMask']['default'])) if local == 'skin_struct'
                   else native not in effect.get('disabled_parameters', []))
        values[local] = (str(value), enabled)
    return values


def to_realtime(snapshot, config, catalog):
    result = deepcopy(config)
    index, effect, descriptors = nr_target(result, catalog)
    params = effect.setdefault('parameters', {})
    disabled = set(effect.get('disabled_parameters', []))
    extended = nr_extended_range(effect)
    for local, native, label in COMMON_FIELDS:
        raw, enabled = snapshot[local]
        desc = descriptors[native]
        maximum = desc['max'] if local == 'style' or extended else min(1, desc['max'])
        params[native] = checked(raw, desc['min'], maximum, label, integer=local == 'style')
        if local == 'skin_struct':
            params['useAutoMask'] = int(enabled)
        elif local != 'style':
            disabled.discard(native)
            if not enabled:
                disabled.add(native)
    if disabled:
        effect['disabled_parameters'] = sorted(disabled)
    else:
        effect.pop('disabled_parameters', None)
    return index, validate_config(result)


def describe(values):
    lines = []
    for local, _, label in COMMON_FIELDS:
        raw, enabled = values[local]
        if local == 'style':
            value = tr(('style.default', 'style.natural', 'style.cinema')[int(float(raw))])
        else:
            value = tr('parameter.copy_value', state=tr('parameter.on' if enabled else 'parameter.off'),
                       value=format_number(raw))
        lines.append(tr('label.' + label) + ': ' + value)
    return '\n'.join(lines)
