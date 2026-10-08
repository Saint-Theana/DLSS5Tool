"""Localize bundled effect metadata without changing native IDs or values."""
import re
from dlss5tool.i18n import tr


def effect_key(text):
    normalized = str(text).replace('\\n', '\n').strip()
    slug = re.sub(r'[^a-z0-9]+', '_', normalized.lower().replace('+', ' plus ')).strip('_')
    return 'realtime.effect.' + slug


def effect_text(text):
    # Unknown third-party effects retain their own label, never a raw i18n key.
    normalized = str(text).replace('\\n', '\n').strip()
    key = effect_key(normalized)
    translated = tr(key)
    return normalized if translated == key else translated


def parameter_label(item):
    # Upstream calls both distinct backend settings "OF Quality".
    key = {'amdOpticalFlowMode': 'realtime.parameter.amd_flow',
           'nvidiaOpticalFlowQuality': 'realtime.parameter.nvidia_flow'}.get(item['name'])
    return tr(key) if key else effect_text(item.get('label') or item['name'])


def parameter_hint(name):
    """Help for the curated NR inspector, not arbitrary third-party IDs."""
    field = re.sub(r'^pass[23]_', '', name)
    shared = {'style': 'parameter.hint.style', 'intensity': 'tooltip.strength',
              'localToneStrength': 'tooltip.local_tone', 'localStructureStrength': 'tooltip.local_structure'}
    if field in shared:
        return tr(shared[field]) + ('\n' + tr('parameter.switch_hint') if field != 'style' else '')
    return tr('realtime.parameter.hint.' + field) if field in (
        'style', 'intensity', 'localToneStrength', 'localStructureStrength',
        'skinStructureStrength', 'useAutoMask', 'uiCorrection', 'residualMultiplier',
        'residualSaturation', 'residualLightness', 'shadowStructureMultiplier',
        'reflectionGlowMultiplier',
    ) else ''


def effect_title(name, descriptor=None):
    """Display alias only; the original effect path remains the config identity."""
    if name.replace('/', '\\') == 'DLSSNR\\DLSSNR_AI_Filter':
        return 'DLSS NR'
    return (descriptor or {}).get('label') or name.replace('\\', '/').rsplit('/', 1)[-1]


EFFECT_CATEGORIES = ('all', 'enhance', 'scale', 'anime', 'pixel', 'sharpen', 'antialias', 'color', 'crt', 'frames', 'utility', 'other')


def effect_category(name):
    family = name.replace('\\', '/').split('/')[0]
    if family == 'DLSSNR':
        return 'enhance'
    if family in ('DLSSFG', 'XeSSFG', 'FrameRate_Filter'):
        return 'frames'
    if family in ('Anime4K', 'CuNNy', 'CuNNy2', 'ACNet', 'k7_modernAnime_FHD_x2'):
        return 'anime'
    if family in ('Pixel Art', 'xBRZ', 'Nearest'):
        return 'pixel'
    if name.replace('\\', '/') == 'CAS/CAS_Scaling':
        return 'scale'
    if family in ('CAS', 'Sharpen') or name.replace('\\', '/').endswith(('RCAS', 'NIS_Sharpen', 'NVSharpen')):
        return 'sharpen'
    if family in ('FXAA', 'MLAA', 'SMAA'):
        return 'antialias'
    if family in ('Color', 'Deband', 'ImageAdjustment'):
        return 'color'
    if family == 'CRT':
        return 'crt'
    if family == 'Diagnostics':
        return 'utility'
    if family in ('DLSS', 'FSR', 'FSR2', 'FSR3', 'FSR4', 'FSRCNNX', 'NIS', 'NNEDI3', 'RAVU',
                  'RTXVideo', 'XeSS', 'Bicubic', 'Bilinear', 'Jinc', 'Lanczos', 'SGSR', 'SSimDownscaler'):
        return 'scale'
    return 'other'


def effect_description(name, *, brief=False):
    family = name.replace('\\', '/').split('/')[0]
    special = {'DLSSNR': 'nr', 'DLSS': 'dlss', 'DLSSFG': 'fg', 'FrameRate_Filter': 'rate',
               'SSimDownscaler': 'downscale', 'Diagnostics': 'diagnostic'}
    key = special.get(family, effect_category(name))
    return tr(('realtime.effects.brief.' if brief else 'realtime.effects.description.') + key)


def inspector_groups(name, parameters):
    """Curate the bundled NR; keep every third-party parameter and group."""
    groups = {}
    nr = name.replace('/', '\\') == 'DLSSNR\\DLSSNR_AI_Filter'
    for item in parameters:
        field = item['name']
        if nr:
            if field.startswith(('pass2_', 'pass3_')):
                group = field.split('_')[0]
            elif field in ('enableInputResolutionScaling', 'inputResolutionPercent'):
                group = 'resolution'
            elif field in ('residualMultiplier', 'shadowStructureMultiplier', 'reflectionGlowMultiplier'):
                group = 'detail'
            elif field in ('residualSaturation', 'residualLightness'):
                group = 'color'
            elif field in ('opticalFlowMethod', 'amdOpticalFlowMode', 'nvidiaOpticalFlowQuality', 'multiPass', 'antiFlicker'):
                group = 'advanced'
            elif field in ('style', 'intensity', 'localToneStrength', 'localStructureStrength', 'skinStructureStrength', 'useAutoMask', 'uiCorrection'):
                group = 'look'
            else:
                group = 'native:' + (item.get('group') or '')
        else:
            group = 'native:' + (item.get('group') or '')
        groups.setdefault(group, []).append(item)
    order = ('look', 'detail', 'color', 'resolution', 'advanced', 'pass2', 'pass3')
    if nr:
        common = ('style', 'intensity', 'localToneStrength', 'localStructureStrength',
                  'skinStructureStrength', 'useAutoMask', 'uiCorrection')
        for key in ('look', 'pass2', 'pass3'):
            groups.get(key, []).sort(key=lambda p: common.index(re.sub(r'^pass[23]_', '', p['name']))
                                    if re.sub(r'^pass[23]_', '', p['name']) in common else len(common))
    keys = [key for key in order if key in groups] + [key for key in groups if key not in order]
    return [(key, (effect_text(key[7:]) or tr('realtime.parameters')) if key.startswith('native:')
             else tr('realtime.editor.group.' + key), groups[key]) for key in keys]
