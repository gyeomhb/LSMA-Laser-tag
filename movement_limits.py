"""Strict pixel-space boundary checks for autonomous Cozmo movement."""

import math

BOUNDS = (50, 900, 50, 600)
MAX_POSITION_AGE = 0.5


def movement_block_reason(sample, elapsed, marker_id, bounds=BOUNDS):
    if marker_id is None:
        return "No robot tag assigned"
    if not isinstance(sample, dict) or sample.get("error"):
        return "Tracking unavailable"
    try:
        age = float(sample["frame_age_seconds"]) + max(0, elapsed)
        if not math.isfinite(age) or age < 0 or age > MAX_POSITION_AGE:
            return "Tracking stale"
        matches = [m for m in sample.get("markers", []) if int(m["id"]) == marker_id]
        if len(matches) != 1:
            return "Tag {} missing or ambiguous".format(marker_id)
        x, y = map(float, matches[0]["center_pixels"])
        if not math.isfinite(x) or not math.isfinite(y):
            return "Invalid coordinates"
    except (KeyError, TypeError, ValueError):
        return "Invalid tracking data"
    xmin, xmax, ymin, ymax = bounds
    if not (xmin < x < xmax and ymin < y < ymax):
        return "At/outside boundary - stopped (X {:.1f}, Y {:.1f})".format(x, y)
    return None

