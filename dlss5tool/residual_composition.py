"""Local vectorized reference for native residual/protection formulas.

Neutral settings bypass conversion. HDR global controls use linear light;
SDR fine controls operate on normalized stored RGB/HSL, as in the native shader.
"""
import numpy as np
from dlss5tool import appearance


def protection_mask(shape, q):
    h, w = shape[:2]
    mask = np.zeros((h, w), np.float32)
    if not q['protection']:
        return mask
    x = np.arange(w, dtype=np.float32)[None, :] + .5
    y = np.arange(h, dtype=np.float32)[:, None] + .5
    for a, b, c, d in q['regions']:
        edge = np.minimum(np.minimum(x-a*w, c*w-x), np.minimum(y-b*h, d*h-y))
        if q['feather']:
            t = np.clip(edge/q['feather'], 0, 1)
            edge = t*t*(3-2*t)
        else:
            edge = edge >= 0
        np.maximum(mask, edge, out=mask)
    return mask


def _hsl(rgb):
    hi, lo = rgb.max(-1), rgb.min(-1)
    delta = hi-lo
    safe = np.maximum(delta, 1e-6)
    light = (hi+lo)*.5
    r, g, b = np.moveaxis(rgb, -1, 0)
    hue = np.where(hi == r, (g-b)/safe, np.where(hi == g, (b-r)/safe+2, (r-g)/safe+4))/6
    saturation = delta/np.maximum(1-np.abs(2*light-1), 1e-6)
    return np.stack((np.where(delta > 1e-6, hue % 1, 0),
                     np.where(delta > 1e-6, np.clip(saturation, 0, 1), 0), light), -1)


def _rgb(hsl):
    h, s, l = np.moveaxis(hsl, -1, 0)
    q = np.where(l < .5, l*(1+s), l+s-l*s)
    p = 2*l-q
    def channel(offset):
        t = (h+offset) % 1
        return np.where(t < 1/6, p+(q-p)*6*t,
                        np.where(t < .5, q, np.where(t < 2/3, p+(q-p)*(2/3-t)*6, p)))
    return np.clip(np.stack((channel(1/3), channel(0), channel(-1/3)), -1), 0, 1)


def fine_controls(base, output, r):
    if all(v == 1 for v in r.values()):
        return output
    delta = (output-base)*r['residualMultiplier']
    candidate = np.clip(base+delta, 0, 1)
    def linear(x):
        return np.where(x <= .04045, x/12.92, (np.maximum(x+.055, 0)/1.055)**2.4)
    dy = (linear(candidate)-linear(base)) @ np.array([.2126, .7152, .0722], np.float32)
    direction = np.where(dy < 0, r['shadowStructureMultiplier'],
                         np.where(dy > 0, r['reflectionGlowMultiplier'], 1))
    candidate = np.clip(base+delta*direction[..., None], 0, 1)
    if r['residualSaturation'] != 1 or r['residualLightness'] != 1:
        original, adjusted = _hsl(base), _hsl(candidate)
        adjusted[..., 1:] = np.clip(original[..., 1:] + (adjusted[..., 1:]-original[..., 1:]) *
                                   [r['residualSaturation'], r['residualLightness']], 0, 1)
        candidate = _rgb(adjusted)
    return np.where(np.any(delta != 0, axis=-1, keepdims=True), candidate, base)


def global_controls(base, output, q):
    raw = output-base
    delta = np.minimum(raw, 0)*q['darken'] + np.maximum(raw, 0)*q['brighten']
    if q['color'] != 1 or q['luminance'] != 1:
        dy = (delta @ np.array([.2126, .7152, .0722], np.float32))[..., None]
        delta = dy*q['luminance']+(delta-dy)*q['color']
    delta *= q['total']*(1-protection_mask(base.shape, q)[..., None])
    anchor_delta = np.minimum(raw, 0)
    anchor = base+anchor_delta
    result = base+delta
    guard = (base >= 0) & (anchor > 0) & (delta < anchor_delta)
    result[guard] = anchor[guard]/(1+(anchor_delta[guard]-delta[guard])/anchor[guard])
    return result


def compose(original, processed, settings=None, *, order='rgb', profile='srgb'):
    if not settings or not appearance.active(settings):
        return processed
    hdr = profile != 'srgb'
    values = appearance.preflight(settings, hdr=hdr)
    if original.shape != processed.shape or original.dtype != processed.dtype:
        raise ValueError('NR composition requires matching frames')
    divisor = np.iinfo(original.dtype).max if original.dtype.kind == 'u' else 1.0
    base = original[..., :3].astype(np.float32)/divisor
    output = processed[..., :3].astype(np.float32)/divisor
    if order == 'bgr':
        base, output = base[..., ::-1], output[..., ::-1]
    if hdr:
        from dlss5tool.video_export import _pq_eotf, _pq_oetf, _hlg_eotf, _hlg_oetf
        if profile not in ('hdr10_pq', 'hdr10_hlg', 'scrgb'):
            raise ValueError('Unsupported HDR composition profile')
        decode, encode = (_pq_eotf, _pq_oetf) if profile == 'hdr10_pq' else (_hlg_eotf, _hlg_oetf)
        if profile != 'scrgb':
            base, output = decode(base), decode(output)
    else:
        output = fine_controls(base, output, values['nr_residual'])
    output = global_controls(base, output, values['nr_quality'])
    if hdr and profile != 'scrgb':
        output = encode(np.maximum(output, 0))
    if profile != 'scrgb':
        output = np.clip(output, 0, 1)
    if order == 'bgr':
        output = output[..., ::-1]
    result = original.copy()  # Preserve source alpha.
    result[..., :3] = (np.rint(output*divisor) if divisor != 1 else output).astype(original.dtype)
    return result
