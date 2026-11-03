"""Tag-center separation in source-image pixels."""

import math


def tag_distance(markers, first=5, second=8):
    centers = []
    for tag in (first, second):
        matches = [m for m in markers if m.get('id') == tag]
        if len(matches) != 1:
            return {'distance_pixels': None, 'message': 'Tag {} missing or ambiguous'.format(tag)}
        try:
            x, y = map(float, matches[0]['center_pixels'])
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError('Nonfinite center')
        except (KeyError, TypeError, ValueError):
            return {'distance_pixels': None, 'message': 'Invalid tag center'}
        centers.append((x, y))
    dx = (centers[1][0]-centers[0][0])
    dy = (centers[1][1]-centers[0][1])
    return {'distance_pixels': math.hypot(dx, dy), 'centers_pixels': centers,
            'message': 'Approximate tag-center distance'}
