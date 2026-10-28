"""Automatically drive Cozmo between waypoints inside the tracking boundary."""

import argparse
import asyncio
from functools import partial
import json
import math
import random
import time

import cozmo

from escape_cozmo import CALIBRATION, pose, wrap
from movement_limits import BOUNDS, movement_block_reason
from random_cozmo import keyboard_stop
from tracking_panel import DEFAULT_TRACKING_URL, TrackingClient

ARRIVAL_RADIUS = 25
GRID_X_SPACING = 205
GRID_Y_SPACING = 150
WAYPOINTS = (
    (130, 130), (335, 130), (540, 130), (745, 130), (950, 130),
    (130, 280), (950, 280),
    (130, 430), (950, 430),
    (130, 530), (335, 530), (540, 530), (745, 530), (950, 530),
)


def validate_points(points):
    xmin, xmax, ymin, ymax = BOUNDS
    result = []
    for point in points:
        if len(point) != 2:
            raise ValueError('Each waypoint needs X and Y')
        x, y = map(float, point)
        if not (math.isfinite(x) and math.isfinite(y) and xmin < x < xmax and ymin < y < ymax):
            raise ValueError('Waypoints must be inside X {}-{}, Y {}-{}'.format(xmin, xmax, ymin, ymax))
        if any(math.hypot(x-px, y-py) <= 2*ARRIVAL_RADIUS for px, py in result):
            raise ValueError('Keep waypoints more than 50 pixels apart')
        result.append((x, y))
    if len(result) < 2:
        raise ValueError('Choose at least two waypoints')
    return result


class WaypointPlan:
    def __init__(self, points, rng=None):
        self.points = validate_points(points)
        self.rng = rng or random.Random()
        self.index = None
        self.deadline = None

    def update(self, position, now=None):
        now = time.monotonic() if now is None else now
        arrived = self.index is not None and math.hypot(
            position[0]-self.points[self.index][0], position[1]-self.points[self.index][1]) <= ARRIVAL_RADIUS
        changed = self.index is None or arrived or (self.deadline is not None and now >= self.deadline)
        if changed:
            previous = self.points[self.index] if self.index is not None else None
            choices = [i for i, point in enumerate(self.points) if i != self.index
                       and (previous is None or abs(point[0]-previous[0]) > GRID_X_SPACING
                            or abs(point[1]-previous[1]) > GRID_Y_SPACING)
                       and math.hypot(position[0]-point[0], position[1]-point[1]) > ARRIVAL_RADIUS]
            if not choices:
                raise ValueError('No non-neighboring waypoint available')
            self.index = self.rng.choice(choices)
            self.deadline = now + self.rng.uniform(7, 10)
        return self.points[self.index], changed


class ForwardSteering:
    """Persistent turn/drive state prevents jitter around one angle threshold."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.turning = True
        self.turn = 0.0
        self.forward = 0.0
        self.last_time = None
        self.uturn_sign = None

    def wheels(self, coz, target, speed, now=None):
        now = time.monotonic() if now is None else now
        dt = 0.05 if self.last_time is None else max(0, min(0.1, now-self.last_time))
        self.last_time = now
        x, y, heading = coz
        error = wrap(math.atan2(target[1]-y, target[0]-x) - heading)
        # A target almost directly behind must not alternate left/right when
        # noisy headings cross the +/-180-degree wrap point.
        if abs(error) > math.radians(150):
            if self.uturn_sign is None:
                self.uturn_sign = 1 if error >= 0 else -1
            error = self.uturn_sign * abs(error)
        else:
            self.uturn_sign = None
        if self.turning:
            if abs(error) <= math.radians(8):
                self.turning = False
        elif abs(error) >= math.radians(30):
            self.turning = True
        desired_turn = 0 if abs(error) <= math.radians(3) else max(-60, min(60, 45*error))
        # Ramp angular commands, keeping the 60 mm/s maximum turn component.
        limit = 240*dt
        self.turn += max(-limit, min(limit, desired_turn-self.turn))
        if self.turning:
            self.forward = 0
            return self.turn, -self.turn
        self.forward = min(speed, self.forward+300*dt)
        # Both wheels remain forward once aligned; cruise speed is still 90.
        return tuple(max(0, min(150, v)) for v in
                     (self.forward+self.turn, self.forward-self.turn))


class HeadingHold:
    """Drive forward during tag loss, correcting yaw with the robot's own heading."""
    def __init__(self, robot):
        self.heading = self.read_heading(robot)

    @staticmethod
    def read_heading(robot):
        angle = getattr(robot, 'pose_angle', None)
        value = getattr(angle, 'radians', None)
        return value if isinstance(value, (int, float)) and math.isfinite(value) else None

    def wheels(self, robot, speed):
        current = self.read_heading(robot)
        if self.heading is None or current is None:
            return speed, speed
        # SDK yaw is counterclockwise-positive (opposite image-space yaw).
        error = wrap(self.heading-current)
        correction = max(-min(30, speed), min(min(30, speed), 45*error))
        return speed-correction, speed+correction


class ArrivalBrake:
    """Hold motors stopped until fresh tracking confirms position has settled."""
    def __init__(self, position, frame_id, now):
        self.started = now
        self.stable_since = now
        self.anchor = position[:2]
        self.frame_id = frame_id
        self.fresh_samples = 0

    def ready(self, position, frame_id, now):
        if now - self.started >= 2:
            raise ValueError('Cozmo did not settle after braking')
        if frame_id == self.frame_id or frame_id is None:
            return False
        self.frame_id = frame_id
        self.fresh_samples += 1
        if math.hypot(position[0]-self.anchor[0], position[1]-self.anchor[1]) > 3:
            self.anchor = position[:2]
            self.stable_since = now
            self.fresh_samples = 0
        return (now-self.started >= 0.4 and now-self.stable_since >= 0.2
                and self.fresh_samples >= 2)


def automatic_points():
    """Return the same fourteen fixed perimeter coordinates on every run."""
    return validate_points(WAYPOINTS)


async def run(robot, args, points, offset, abort_requested=keyboard_stop):
    plan = WaypointPlan(points)
    steering = ForwardSteering()
    brake = None
    tracking_lost = False
    heading_hold = None
    tracker = TrackingClient(args.tracking_url)
    try:
        robot.stop_all_motors()
        wait_until = time.monotonic()+3
        while tracker.snapshot()[0] is None and time.monotonic() < wait_until:
            if abort_requested():
                return
            await asyncio.sleep(0.05)
        end = time.monotonic()+args.seconds if args.seconds is not None else math.inf
        print('Waypoint run. Click this terminal: Space / Esc / Ctrl+C stops.', flush=True)
        while time.monotonic() < end:
            if abort_requested() or robot.is_picked_up or robot.is_on_charger:
                print('Stopped by keyboard or robot state.', flush=True)
                break
            sample, elapsed = tracker.snapshot()
            reason = movement_block_reason(sample, elapsed, 5, bounds=None)
            if reason:
                if plan.index is None:
                    raise ValueError(reason)
                if not tracking_lost:
                    heading_hold = HeadingHold(robot)
                    print('Tracking lost; holding heading until detected.', flush=True)
                tracking_lost = True
                if brake is None:
                    robot.drive_wheel_motors(*heading_hold.wheels(robot, args.speed))
                await asyncio.sleep(0.05)
                continue
            current = pose(sample, 5, offset)
            if tracking_lost:
                tracking_lost = False
                heading_hold = None
                steering.reset()
                print('Tracking restored; updating direction.', flush=True)
                if brake is not None:
                    brake = ArrivalBrake(current, sample.get('frame_number'), time.monotonic())
            if brake is not None:
                if not brake.ready(current, sample.get('frame_number'), time.monotonic()):
                    await asyncio.sleep(0.05)
                    continue
                brake = None
                steering.reset()
                print('Braking complete; turning toward next target.', flush=True)
            had_target = plan.index is not None
            target, changed = plan.update(current)
            if changed:
                robot.stop_all_motors()
                steering.reset()
                print('Target {}: ({:.0f}, {:.0f}); switch on arrival or after 7-10 seconds.'.format(
                    plan.index+1, *target), flush=True)
                if had_target:
                    brake = ArrivalBrake(current, sample.get('frame_number'), time.monotonic())
                    print('Target changed; holding stop until position settles.', flush=True)
                    await asyncio.sleep(0.05)
                    continue
            robot.drive_wheel_motors(*steering.wheels(current, target, args.speed))
            await asyncio.sleep(0.05)
    except ValueError as exc:
        print('Stopped:', exc, flush=True)
    finally:
        robot.stop_all_motors()
        tracker.close()
        print('Waypoint run finished; motors stopped.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tracking-url', default=DEFAULT_TRACKING_URL)
    parser.add_argument('--seconds', type=float, help='Optional total run duration; default: until stopped')
    parser.add_argument('--speed', type=float, default=90)
    args = parser.parse_args()
    if (args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds <= 0)) or not 1 <= args.speed <= 90:
        parser.error('Use positive finite seconds and speed 1-90 mm/s')
    try:
        offset = float(json.loads(CALIBRATION.read_text(encoding='utf-8'))['5'])
        if not math.isfinite(offset):
            raise ValueError('Invalid heading offset')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error('Calibrate headings first with escape_cozmo.py --calibrate-left: ' + str(exc))
    points = automatic_points()
    print('Automatic waypoints:', points, flush=True)
    cozmo.robot.Robot.drive_off_charger_on_connect = False
    cozmo.run_program(partial(run, args=args, points=points, offset=offset))


if __name__ == '__main__':
    main()
