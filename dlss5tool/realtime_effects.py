"""Presentation-only recipes and groups; native effect identities stay intact."""
from copy import deepcopy
import re

from dlss5tool.i18n import tr
from dlss5tool.realtime import NR
from dlss5tool.realtime_labels import effect_category, effect_title
from dlss5tool.realtime_readiness import chain_summary


RECIPES = ('detail', 'enlarge', 'anime', 'custom')
PURPOSES = ('enhance', 'scale', 'sharpen', 'antialias', 'color', 'frames', 'anime', 'pixel', 'crt', 'utility', 'other')
RECIPE_STEPS = {
    'detail': ((NR, 1),),
    'enlarge': ((NR, 1), ('Lanczos', 1.5)),
    'anime': ((r'Anime4K\Anime4K_Restore_S', 1),),
}


def is_frame_generation(name):
    return name.replace('\\', '/').split('/')[0] in ('DLSSFG', 'XeSSFG')


def new_effect(name, scale=1):
    return dict(name=name, parameters={'multiPass': 1} if name.replace('/', '\\') == NR else {},
                scaling_type=0, scale=[scale, scale])


def recipe_effects(key, catalog, current):
    """Explicit recipe, never a guessed backend fallback or a runtime command."""
    if key == 'custom':
        return deepcopy(current)
    normalized = {name.replace('/', '\\'): name for name in catalog}
    effects = []
    for name, scale in RECIPE_STEPS[key]:
        actual = normalized.get(name)
        if actual is None or not catalog[actual].get('available', True):
            raise ValueError(tr('realtime.workflow.recipe_missing', effect=effect_title(name)))
        effects.append(new_effect(actual, scale))
    return effects + deepcopy([e for e in current if is_frame_generation(e['name'])])


def algorithm_group(name):
    """Group known variants only, not unrelated third-party algorithms."""
    normalized = name.replace('\\', '/')
    family, _, leaf = normalized.rpartition('/')
    if family in ('CuNNy', 'CuNNy2'):
        return family + (' · DN' if leaf.endswith('-DN') else '')
    if family == 'Anime4K':
        # Preserve restore/upscale/denoise/GAN/3D as distinct operations.
        return re.sub(r'_(US|UL|VL|S|M|L)$', '', leaf)
    if family == 'NNEDI3':
        return 'NNEDI3'
    if family == 'RAVU':
        return re.sub(r'_R[234]', '', leaf)
    if family == 'FXAA' or (family == 'SMAA' and not leaf.endswith('Experimental')):
        return family
    if family == 'xBRZ' and re.fullmatch(r'xBRZ_[2-6]x', leaf):
        return 'xBRZ'
    return normalized


def grouped_algorithms(catalog, purpose):
    groups = {}
    for name in sorted(catalog):
        if effect_category(name) == purpose:
            groups.setdefault(algorithm_group(name), []).append(name)
    return groups


def step_title(name):
    category = 'interpolate' if is_frame_generation(name) else effect_category(name)
    return tr('realtime.workflow.step.' + category)


def step_subtitle(effect, catalog):
    name = effect['name']
    title = effect_title(name, catalog.get(name))
    if name.replace('/', '\\') == NR:
        title += ' · ' + chain_summary([effect])
    kind = effect.get('scaling_type', 0)
    x, y = effect.get('scale', [1, 1])
    if kind in (1, 3):
        size = tr('realtime.scale.fit' if kind == 1 else 'realtime.scale.fill')
    elif kind == 0 and x == y == 1:
        size = tr('realtime.workflow.size_original')
    else:
        size = tr('realtime.workflow.size_absolute' if kind == 2 else 'realtime.workflow.size_factor', x=x, y=y)
    return title + ' · ' + size


def choice_issue(name, catalog, effects, *, replacing=None):
    if name not in catalog or not catalog[name].get('available', True):
        return tr('realtime.workflow.unsupported'), True
    others = [effect for i, effect in enumerate(effects) if i != replacing]
    if is_frame_generation(name) and any(is_frame_generation(e['name']) for e in others):
        return tr('realtime.preflight.fg_conflict'), True
    if any(e['name'] == name for e in others):
        return tr('realtime.workflow.duplicate'), False
    if effect_category(name) in ('scale', 'sharpen') and any(effect_category(e['name']) == effect_category(name) for e in others):
        return tr('realtime.workflow.overlap'), False
    return tr('realtime.workflow.unverified'), False
