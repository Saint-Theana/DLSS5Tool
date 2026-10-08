"""Shared numeric input rules; presentation never rounds valid fine values."""
import math
import struct
from decimal import Decimal


def parse_number(raw, *, percent=False):
    text = str(raw).strip()
    value = float(text[:-1].strip()) / 100 if percent and text.endswith('%') else float(text)
    if not math.isfinite(value):
        raise ValueError('non-finite number')
    return value


def clean_step(step):
    """Strip float32 serialization noise from metadata, not from input values."""
    value = parse_number(step)
    return float(format(value, '.7g'))


def format_number(raw, step=.01):
    try:
        value = parse_number(raw)
        digits = min(8, max(0, -Decimal(str(clean_step(step))).normalize().as_tuple().exponent))
        rounded = round(value, digits)
        native = struct.unpack('f', struct.pack('f', rounded))[0]
        if abs(value - rounded) < 1e-9 or value == native:
            return f'{value:.{digits}f}'
    except (ValueError, TypeError, OverflowError):
        pass
    return str(raw)
