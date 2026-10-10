"""Portable appearance contract, independent of GUI, capture and model workers."""
from copy import deepcopy
import math
from dlss5tool.i18n import tr

VERSION = 1
QUALITY_FIELDS = ('total', 'darken', 'brighten', 'color', 'luminance')
DEFAULT_QUALITY = dict.fromkeys(QUALITY_FIELDS, 1.0) | {
    'protection': False, 'feather': 12.0, 'regions': []}
RESIDUAL_FIELDS = ('residualMultiplier', 'shadowStructureMultiplier',
                   'reflectionGlowMultiplier', 'residualSaturation', 'residualLightness')
DEFAULT_RESIDUAL = dict.fromkeys(RESIDUAL_FIELDS, 1.0)
DEFAULTS = {'nr_quality': DEFAULT_QUALITY, 'nr_residual': DEFAULT_RESIDUAL}
GROUPS = ('basic', 'residual', 'quality', 'regions')


def number(value, low, high, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(tr('realtime.error.quality_value', field=name))
    return float(value)


def quality(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - DEFAULT_QUALITY.keys():
        raise ValueError(tr('realtime.error.quality'))
    result = deepcopy(DEFAULT_QUALITY) | deepcopy(value)
    for key in (*QUALITY_FIELDS, 'feather'):
        result[key] = number(result[key], 0, 256 if key == 'feather' else 2, key)
    if type(result['protection']) is not bool:
        raise ValueError(tr('realtime.error.regions'))
    rects = result['regions']
    if not isinstance(rects, list) or len(rects) > 4:
        raise ValueError(tr('realtime.error.regions'))
    for r in rects:
        if not isinstance(r, list) or len(r) != 4:
            raise ValueError(tr('realtime.error.rectangles'))
        for v in r:
            number(v, 0, 1, 'region')
        if r[2] <= r[0] or r[3] <= r[1]:
            raise ValueError(tr('realtime.error.rectangles'))
    return result


def residual(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - DEFAULT_RESIDUAL.keys():
        raise ValueError('Invalid NR residual fields')
    return {k: number(value.get(k, 1.0), 1 if k == 'residualMultiplier' else 0, 2, k)
            for k in RESIDUAL_FIELDS}


def settings(values, *, strict=True):
    result = {}
    for key, validate in (('nr_quality', quality), ('nr_residual', residual)):
        try:
            result[key] = validate(values.get(key))
        except (ValueError, TypeError):
            if strict:
                raise
            result[key] = validate()
    return result


def active(values):
    q, r = quality(values.get('nr_quality')), residual(values.get('nr_residual'))
    return (any(q[k] != 1 for k in QUALITY_FIELDS) or
            bool(q['protection'] and q['regions']) or any(v != 1 for v in r.values()))


def raw_settings(values):
    """Single-pass raw NR cache excludes all post-NR appearance controls."""
    return dict(values, **deepcopy(DEFAULTS))


def preflight(values, *, hdr=False):
    checked = settings(values)
    if hdr and any(v != 1 for v in checked['nr_residual'].values()):
        from dlss5tool.i18n import tr
        raise ValueError(tr('appearance.hdr_residual_unavailable'))
    return checked
