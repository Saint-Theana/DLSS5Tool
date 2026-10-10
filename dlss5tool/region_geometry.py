"""Image-coordinate geometry, independent of Windows capture."""
def fitted_rect(size, width, height):
    """Letterboxed pixel bounds; normalized region coordinates exclude margins."""
    ratio = min(max(1, width)/size[0], max(1, height)/size[1])
    w, h = max(1, round(size[0]*ratio)), max(1, round(size[1]*ratio))
    x, y = (width-w)/2, (height-h)/2
    return x, y, x+w, y+h


def normalized_point(x, y, bounds, *, clamp=False):
    left, top, right, bottom = bounds
    if right <= left or bottom <= top: return None
    if not clamp and not (left <= x <= right and top <= y <= bottom): return None
    return max(0, min(1, (x-left)/(right-left))), max(0, min(1, (y-top)/(bottom-top)))
