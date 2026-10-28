"""Escape Misty using overhead tags and calibrated forward directions.

Calibration assumes BOTH robots face image-left and Misty's laser faces forward.
Recalibrate after moving either tag relative to its robot.
"""

import argparse
import asyncio
from functools import partial
import json
import math
from pathlib import Path
import time
from urllib.request import ProxyHandler, build_opener

import cozmo

from movement_limits import movement_block_reason
from random_cozmo import inner_bounds, keyboard_stop
from tracking_panel import DEFAULT_TRACKING_URL, TrackingClient

CALIBRATION = Path(__file__).with_name('escape_calibration.json')


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def pose(sample, tag, offset=0):
    matches = [m for m in sample['markers'] if m['id'] == tag]
    if len(matches) != 1:
        raise ValueError('Tag {} missing or ambiguous'.format(tag))
    marker = matches[0]
    x, y = map(float, marker['center_pixels'])
    corners = marker['corners_pixels']
    dx = (corners[0][0] + corners[1][0]) / 2 - x
    dy = (corners[0][1] + corners[1][1]) / 2 - y
    if not all(math.isfinite(v) for v in (x, y, dx, dy, offset)) or math.hypot(dx, dy) < 2:
        raise ValueError('Invalid tag geometry')
    return x, y, wrap(math.atan2(dy, dx) + offset)


def validate(sample, elapsed):
    reason = movement_block_reason(sample, elapsed, 5, inner_bounds(40))
    if reason:
        raise ValueError(reason)
    # Misty must be tracked, but may stand outside Cozmo's movement area.
    reason = movement_block_reason(sample, elapsed, 8,
                                   (-math.inf, math.inf, -math.inf, math.inf))
    if reason:
        raise ValueError(reason)


def calibrated_poses(sample, elapsed, calibration):
    validate(sample, elapsed)
    return pose(sample, 5, calibration['5']), pose(sample, 8, calibration['8'])


def choose_target(coz, misty, previous=None):
    """Choose a substantial safe waypoint, rewarding separation from the aim ray."""
    x, y, _ = coz
    mx, my, heading = misty
    xmin, xmax, ymin, ymax = inner_bounds(60)
    candidates = []
    for index in range(32):
        angle = index * math.tau / 32
        tx, ty = x + 140 * math.cos(angle), y + 140 * math.sin(angle)
        if not (xmin < tx < xmax and ymin < ty < ymax):
            continue
        points = [(x + (tx-x)*t/10, y + (ty-y)*t/10) for t in range(1, 11)]
        if min(math.hypot(px-mx, py-my) for px, py in points) < 85:
            continue
        scores = []
        for px, py in points:
            dx, dy = px-mx, py-my
            along = dx*math.cos(heading) + dy*math.sin(heading)
            lateral = abs(-dx*math.sin(heading) + dy*math.cos(heading))
            danger = max(0, 55 + max(0, along)*0.25 - lateral) if along > 0 else 0
            scores.append(math.hypot(dx, dy) - 4*danger)
        clearance = min(tx-xmin, xmax-tx, ty-ymin, ymax-ty)
        score = sum(scores)/len(scores) + 0.5*min(clearance, 80)
        if previous is not None:
            score -= 0.15*math.hypot(tx-previous[0], ty-previous[1])
        candidates.append((score, (tx, ty)))
    if not candidates:
        raise ValueError('No safe escape waypoint')
    return max(candidates)[1]


def wheels_for(coz, target, speed):
    x, y, heading = coz
    error = wrap(math.atan2(target[1]-y, target[0]-x) - heading)
    direction = 1
    if abs(error) > math.pi/2:
        direction = -1
        error = wrap(error - math.pi)
    turn = max(-60, min(60, 70*error))
    forward = direction*speed*max(0, 1-abs(error)/0.8)
    # Image Y points down: clockwise turn => left wheel faster.
    return tuple(max(-150, min(150, v)) for v in (forward+turn, forward-turn))


def calibrate(url):
    opener = build_opener(ProxyHandler({}))
    with opener.open(url, timeout=3) as response:
        sample = json.load(response)
    validate(sample, 0)
    offsets = {str(tag): wrap(math.pi-pose(sample, tag)[2]) for tag in (5, 8)}
    CALIBRATION.write_text(json.dumps(offsets, indent=2), encoding='utf-8')
    print('Saved left-facing calibration:', offsets, flush=True)


async def run(robot, args):
    calibration = json.loads(CALIBRATION.read_text(encoding='utf-8'))
    tracker = TrackingClient(args.tracking_url)
    try:
        robot.stop_all_motors()
        deadline = time.monotonic()+3
        while tracker.snapshot()[0] is None and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        print('Escape run: {} seconds. Space / Esc / Ctrl+C stops.'.format(args.seconds), flush=True)
        end = time.monotonic()+args.seconds
        target = None
        next_plan = 0
        next_log = 0
        while time.monotonic() < end:
            if keyboard_stop() or robot.is_picked_up or robot.is_on_charger:
                print('Stopped by keyboard or robot state.', flush=True)
                break
            sample, elapsed = tracker.snapshot()
            coz, misty = calibrated_poses(sample, elapsed, calibration)
            if math.hypot(coz[0]-misty[0], coz[1]-misty[1]) < 85:
                raise ValueError('Too close to Misty')
            now = time.monotonic()
            if target is None or now >= next_plan or math.hypot(coz[0]-target[0], coz[1]-target[1]) < 30:
                target = choose_target(coz, misty, target)
                next_plan = now+1.0
            wheels = wheels_for(coz, target, args.speed)
            robot.drive_wheel_motors(*wheels)
            if now >= next_log:
                print('Cozmo ({:.0f}, {:.0f}) -> ({:.0f}, {:.0f}), wheels ({:.0f}, {:.0f})'.format(
                    coz[0], coz[1], *target, *wheels), flush=True)
                next_log = now+0.5
            await asyncio.sleep(0.05)
    except ValueError as exc:
        print('Stopped:', exc, flush=True)
    finally:
        robot.stop_all_motors()
        tracker.close()
        print('Escape run finished; motors stopped.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calibrate-left', action='store_true')
    parser.add_argument('--tracking-url', default=DEFAULT_TRACKING_URL)
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--speed', type=float, default=90)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 300:
        parser.error('--seconds must be between 0 and 300')
    if not 1 <= args.speed <= 90:
        parser.error('--speed must be between 1 and 90')
    if args.calibrate_left:
        calibrate(args.tracking_url)
    else:
        if not CALIBRATION.exists():
            parser.error('Face both robots left, then run with --calibrate-left first')
        cozmo.robot.Robot.drive_off_charger_on_connect = False
        cozmo.run_program(partial(run, args=args))
