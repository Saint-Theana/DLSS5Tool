"""Explicit, lossless first-pass NR transfer, never a rendering-pipeline merge."""
from copy import deepcopy

from dlss5tool.i18n import tr
from dlss5tool.parameter_values import parse_number, format_number
from dlss5tool.realtime import NR, validate_config, nr_extended_range
from dlss5tool import appearance
from dlss5tool.parameter_contract import BASIC, PARAMETERS, native_descriptor
import json


COMMON_FIELDS = tuple((p.key, p.native, p.label.removeprefix('label.')) for p in BASIC)


def nr_target(config, catalog):
    matches = [(i, e) for i, e in enumerate(config['effects']) if e['name'].replace('/', '\\') == NR]
    if len(matches) != 1:
        raise ValueError(tr('parameter.copy_one_nr'))
    index, effect = matches[0]
    descriptors = {p['name']: native_descriptor(p) for p in catalog.get(effect['name'], {}).get('parameters', [])}
    if not {'style', 'intensity', 'localToneStrength', 'localStructureStrength', 'skinStructureStrength', 'useAutoMask'} <= descriptors.keys():
        raise ValueError(tr('parameter.copy_metadata'))
    return index, effect, descriptors


def checked(raw, minimum, maximum, label, *, integer=False):
    value = parse_number(raw, percent=not integer)
    if not minimum <= value <= maximum or (integer and not value.is_integer()):
        raise ValueError(tr('parameter.copy_range', name=tr('label.' + label), minimum=minimum, maximum=maximum))
    return int(value) if integer else value


def from_realtime(config, catalog, local_limit, groups=('basic',)):
    _, effect, descriptors = nr_target(config, catalog)
    values = {}
    params = effect.get('parameters', {})
    for local, native, label in COMMON_FIELDS if 'basic' in groups else ():
        value = params.get(native, descriptors[native]['default'])
        spec = PARAMETERS[local]
        value = checked(value, spec.minimum, spec.maximum if spec.integer else min(spec.maximum, local_limit),
                        label, integer=spec.integer)
        enabled = (None if local == 'style' else
                   bool(params.get('useAutoMask', descriptors['useAutoMask']['default'])) if local == 'skin_struct'
                   else native not in effect.get('disabled_parameters', []))
        values[local] = (str(value), enabled)
    if 'residual' in groups:
        if not set(appearance.RESIDUAL_FIELDS) <= descriptors.keys():
            raise ValueError(tr('parameter.copy_metadata'))
        r = appearance.residual({k: params.get(k, descriptors[k]['default']) for k in appearance.RESIDUAL_FIELDS})
        values.update({'nr_residual.' + k: (str(v), None) for k, v in r.items()})
    q = appearance.quality(config.get('quality'))
    if 'quality' in groups:
        values.update({'nr_quality.' + k: (str(q[k]), None) for k in appearance.QUALITY_FIELDS})
    if 'regions' in groups:
        values.update({'nr_quality.feather': (str(q['feather']), None),
                       'nr_quality.protection': (str(int(q['protection'])), None),
                       '_regions': (json.dumps(q['regions']), None)})
    return values


def to_realtime(snapshot, config, catalog, groups=('basic',)):
    result = deepcopy(config)
    index, effect, descriptors = nr_target(result, catalog)
    params = effect.setdefault('parameters', {})
    disabled = set(effect.get('disabled_parameters', []))
    extended = nr_extended_range(effect)
    for local, native, label in COMMON_FIELDS if 'basic' in groups else ():
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
    if 'residual' in groups:
        values = appearance.residual({k: parse_number(snapshot['nr_residual.' + k][0]) for k in appearance.RESIDUAL_FIELDS})
        if not set(values) <= descriptors.keys():
            raise ValueError(tr('parameter.copy_metadata'))
        for key, value in values.items():
            desc = descriptors[key]
            if not desc['min'] <= value <= desc['max']:
                raise ValueError(tr('parameter.copy_range', name=tr('appearance.' + key),
                                    minimum=desc['min'], maximum=desc['max']))
        params.update(values)
        if 'enableResidualControls' in descriptors:
            params['enableResidualControls'] = 1
    q = result['quality']
    if 'quality' in groups:
        q.update({k: parse_number(snapshot['nr_quality.' + k][0]) for k in appearance.QUALITY_FIELDS})
    if 'regions' in groups:
        switch = parse_number(snapshot['nr_quality.protection'][0])
        if switch not in (0, 1):
            raise ValueError('Invalid protection switch')
        q.update(feather=parse_number(snapshot['nr_quality.feather'][0]), protection=bool(switch),
                 regions=json.loads(snapshot['_regions'][0]))
    return index, validate_config(result)


def describe(values):
    lines = []
    for local, _, label in COMMON_FIELDS:
        if local not in values:
            continue
        raw, enabled = values[local]
        if local == 'style':
            value = tr(('style.default', 'style.natural', 'style.cinema')[int(float(raw))])
        else:
            value = tr('parameter.copy_value', state=tr('parameter.on' if enabled else 'parameter.off'),
                       value=format_number(raw))
        lines.append(tr('label.' + label) + ': ' + value)
    for key, (raw, _) in values.items():
        if key.startswith('nr_'):
            lines.append(tr('appearance.' + key.split('.')[1]) + ': ' + str(raw))
        elif key == '_regions':
            lines.append(tr('realtime.workspace.regions', count=len(json.loads(raw))))
    return '\n'.join(lines)


def portable_preset(snapshot, groups):
    """Strict, grouped values only; never executable paths or capture settings."""
    if (not isinstance(groups, (tuple, list)) or not groups or
            any(type(g) is not str or g not in appearance.GROUPS for g in groups) or
            len(set(groups)) != len(groups)):
        raise ValueError('Invalid appearance groups')
    keys = set()
    if 'basic' in groups:
        keys.update(k for k, _, _ in COMMON_FIELDS)
    if 'residual' in groups:
        keys.update('nr_residual.' + k for k in appearance.RESIDUAL_FIELDS)
    if 'quality' in groups:
        keys.update('nr_quality.' + k for k in appearance.QUALITY_FIELDS)
    if 'regions' in groups:
        keys.update(('nr_quality.feather', 'nr_quality.protection', '_regions'))
    if not isinstance(snapshot, dict) or not keys <= snapshot.keys():
        raise ValueError('Missing appearance fields')
    if any(not isinstance(snapshot[k], (list, tuple)) or len(snapshot[k]) != 2 for k in keys):
        raise ValueError('Invalid appearance value')
    values = {k: list(snapshot[k]) for k in sorted(keys)}
    for key, pair in values.items():
        if len(pair) != 2:
            raise ValueError('Invalid appearance value')
        raw, enabled = pair
        if key == '_regions':
            if not isinstance(raw, str):
                raise ValueError('Invalid region encoding')
            appearance.quality({'regions': json.loads(raw)})
        else:
            v = parse_number(raw, percent=key != 'style')
            if key.startswith('nr_'):
                group, name = key.split('.')
                if name == 'protection':
                    if v not in (0, 1):
                        raise ValueError('Invalid protection switch')
                else:
                    (appearance.quality if group == 'nr_quality' else appearance.residual)({name: v})
            else:
                spec = PARAMETERS[key]
                if not spec.minimum <= v <= spec.maximum or (spec.integer and v != int(v)):
                    raise ValueError('Invalid basic NR value')
            pair[0] = str(v)  # Canonical numbers also round-trip percentage input.
        if key in {k for k, _, _ in COMMON_FIELDS if k != 'style'}:
            if type(enabled) is not bool:
                raise ValueError('Invalid NR switch')
        elif enabled is not None:
            raise ValueError('Unexpected appearance switch')
    return {'version': appearance.VERSION, 'kind': 'portable-appearance', 'groups': list(groups), 'values': values}


def read_portable(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'kind', 'groups', 'values'}
            or type(value['version']) is not int or value['version'] != appearance.VERSION
            or value['kind'] != 'portable-appearance' or not isinstance(value['values'], dict)
            or not isinstance(value['groups'], list)):
        raise ValueError('Invalid portable appearance preset')
    checked = portable_preset(value['values'], value['groups'])
    if set(checked['values']) != set(value['values']):
        raise ValueError('Unexpected appearance fields')
    return checked
