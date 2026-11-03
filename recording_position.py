"""Latest overhead tag position sampled when a robot camera frame arrives."""

import math

POSITION_FIELDS = ['position_x_px', 'position_y_px', 'position_valid',
                   'position_tag_id', 'position_age_s', 'position_frame_number']
COZMO_POSITION_FIELDS = ['cozmo_' + field for field in POSITION_FIELDS]
POSITION_METADATA = {
    'position_source': 'overhead ArUco tag center',
    'position_units': 'pixels; origin top-left, X right, Y down',
    'position_alignment': 'Latest tracking sample at robot image receipt; not synchronized exposures',
    'position_max_age_s': 0.5,
    'position_missing': 'Blank X/Y and position_valid=False for missing, stale, ambiguous or invalid tracking',
}


def position_row(tracker, tag):
    sample, elapsed = tracker.snapshot() if tracker is not None else (None, 0)
    return position_from_sample(sample, elapsed, tag)


def misty_positions(tracker):
    sample, elapsed = tracker.snapshot() if tracker is not None else (None, 0)
    row = position_from_sample(sample, elapsed, 8)
    row.update({'cozmo_' + key: value for key, value in
                position_from_sample(sample, elapsed, 5).items()})
    return row


def position_from_sample(sample, elapsed, tag):
    row = dict(zip(POSITION_FIELDS, ('', '', False, tag, '', '')))
    try:
        if sample.get('error'):
            return row
        age = float(sample['frame_age_seconds']) + max(0, elapsed)
        if not math.isfinite(age) or age < 0:
            return row
        row['position_age_s'] = age
        row['position_frame_number'] = sample.get('frame_number', '')
        if age > 0.5:
            return row
        matches = [m for m in sample['markers'] if m['id'] == tag]
        if len(matches) != 1:
            return row
        x, y = map(float, matches[0]['center_pixels'])
        if not all(math.isfinite(v) for v in (x, y)):
            return row
        row.update(position_x_px=x, position_y_px=y, position_valid=True)
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    return row
