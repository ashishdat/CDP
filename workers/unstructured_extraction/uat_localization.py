"""Bound recovery crops to recorded field labels, with explicit fallback reasons."""
import re


def field_region(layout, aliases, width, height):
    matches = []
    for line in layout.lines:
        text = ' '.join(re.sub(r'[^a-z0-9 ]', ' ', line.text.casefold()).split())
        if any(re.search(r'\b' + re.escape(alias.casefold()) + r'\b', text) for alias in aliases):
            box = line.bbox
            matches.append((box.x0, box.y0, box.x1, box.y1))
    if len(matches) != 1:
        return None  # Ambiguous labels must not silently choose the first match.
    x0, y0, x1, y1 = matches[0]
    pad = max(24, 3 * (y1 - y0))
    return [max(.01, (x0 - pad) / width), max(.01, (y0 - pad) / height),
            min(.99, max(x1 + pad, x0 + .65 * width) / width), min(.99, (y1 + pad) / height)]
