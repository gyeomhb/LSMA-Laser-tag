"""Short random Cozmo movements constrained by overhead tracking of tag 5."""

import argparse
import asyncio
from functools import partial
import math
from pathlib import Path
import random
import time

import cozmo

from dataset_recorder import DatasetRecorder
from frame_rate import CAMERA_FPS
from movement_limits import BOUNDS, movement_block_reason
from tracking_panel import DEFAULT_TRACKING_URL, TrackingClient


def inner_bounds(margin):
    xmin, xmax, ymin, ymax = BOUNDS
    if not math.isfinite(margin) or margin < 0 or 2 * margin >= min(xmax - xmin, ymax - ymin):
        raise ValueError("Margin must be nonnegative and leave a nonempty movement area")
    return xmin + margin, xmax - margin, ymin + margin, ymax - margin


def choose_action(rng, speed=90, turn_speed=60):
    """Return a label, equivalent WASD keys, wheel commands, and duration."""
    action = rng.choice([
        ("forward", {"w"}, (speed, speed)),
        ("backward", {"s"}, (-speed, -speed)),
        ("left", {"a"}, (-turn_speed, turn_speed)),
        ("right", {"d"}, (turn_speed, -turn_speed)),
        ("forward_left", {"w", "a"}, (speed / 2, speed)),
        ("forward_right", {"w", "d"}, (speed, speed / 2)),
        ("stop", set(), (0, 0)),
    ])
    return (*action, rng.uniform(0.2, 0.7))


def stop_reason(robot, tracker, marker_id, bounds, abort_requested):
    if abort_requested():
        return "Stopped by keyboard"
    if robot.is_picked_up:
        return "Robot was picked up"
    if robot.is_on_charger:
        return "Place Cozmo off the charger before starting"
    sample, elapsed = tracker.snapshot()
    return movement_block_reason(sample, elapsed, marker_id, bounds)


async def run_segment(robot, tracker, marker_id, bounds, wheels, duration,
                      abort_requested=lambda: False):
    """Never start without a valid position; recheck while each segment runs."""
    try:
        reason = stop_reason(robot, tracker, marker_id, bounds, abort_requested)
        if reason:
            return reason
        if wheels != (0, 0):
            robot.drive_wheel_motors(*wheels)
        else:
            robot.stop_all_motors()
        until = time.monotonic() + duration
        while time.monotonic() < until:
            reason = stop_reason(robot, tracker, marker_id, bounds, abort_requested)
            if reason:
                return reason
            await asyncio.sleep(min(0.02, max(0, until - time.monotonic())))
        return None
    finally:
        robot.stop_all_motors()


def keyboard_stop():
    import msvcrt
    while msvcrt.kbhit():
        if msvcrt.getwch() in (" ", "\x1b", "\x03"):
            return True
    return False


async def main(robot, args):
    tracker = TrackingClient(args.tracking_url)
    bounds = inner_bounds(args.margin)
    rng = random.Random(args.seed)
    recorder = None
    handler = None
    active_keys, active_wheels = set(), (0, 0)
    original_stream = robot.camera.image_stream_enabled
    original_color = robot.camera.color_image_enabled

    def on_image(evt, *, image, **kwargs):
        if recorder is not None:
            recorder.offer(image, active_keys, active_wheels, robot.head_angle.degrees)

    try:
        robot.stop_all_motors()
        # Wait for the first HTTP response without moving.
        deadline = time.monotonic() + 3
        while tracker.snapshot()[0] is None and time.monotonic() < deadline:
            if keyboard_stop():
                return
            await asyncio.sleep(0.05)
        reason = stop_reason(robot, tracker, args.marker_id, bounds, keyboard_stop)
        if reason:
            print("Not starting:", reason, flush=True)
            return
        if args.record:
            await robot.set_head_angle(cozmo.util.degrees(-5)).wait_for_completed()
            recorder = DatasetRecorder(Path(__file__).parent / "dataset_cozmo", fps=CAMERA_FPS)
            # Add automation settings to the standard Cozmo session metadata.
            import json
            path = recorder.path / "metadata.json"
            metadata = json.loads(path.read_text(encoding="utf-8"))
            metadata.update(controller="random_cozmo", marker_id=args.marker_id,
                            bounds_pixels=BOUNDS, inner_bounds_pixels=bounds,
                            random_seed=args.seed, requested_duration_seconds=args.seconds)
            path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            handler = robot.world.add_event_handler(cozmo.world.EvtNewCameraImage, on_image)
            robot.camera.color_image_enabled = True
            robot.camera.image_stream_enabled = True
            print("Recording:", recorder.path, flush=True)
        print("Random movement for up to {} seconds; tag {}; inner bounds {}.".format(
            args.seconds, args.marker_id, bounds), flush=True)
        print("Press Space, Esc, or Ctrl+C in this terminal to stop.", flush=True)
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            if recorder is not None and recorder.error:
                print("Recording failed:", recorder.error, flush=True)
                break
            name, active_keys, active_wheels, duration = choose_action(rng, args.speed, args.turn_speed)
            duration = min(duration, max(0, end - time.monotonic()))
            print(name, "|", tracker.text(args.marker_id), flush=True)
            reason = await run_segment(robot, tracker, args.marker_id, bounds, active_wheels,
                                       duration, keyboard_stop)
            active_keys, active_wheels = set(), (0, 0)
            if reason:
                print("Stopped:", reason, flush=True)
                break
        print("Random movement finished.", flush=True)
    finally:
        try:
            robot.stop_all_motors()
        finally:
            active_keys, active_wheels = set(), (0, 0)
            tracker.close()
            if handler is not None:
                handler.disable()
            if recorder is not None:
                await asyncio.get_running_loop().run_in_executor(None, recorder.close)
                print("Saved {} frames; {} dropped.{}".format(
                    recorder.count, recorder.dropped,
                    " ERROR: " + recorder.error if recorder.error else ""), flush=True)
            robot.camera.image_stream_enabled = original_stream
            robot.camera.color_image_enabled = original_color


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking-url", default=DEFAULT_TRACKING_URL)
    parser.add_argument("--marker-id", type=int, default=5)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--speed", type=float, default=90, help="Straight wheel speed in mm/s (1-90)")
    parser.add_argument("--turn-speed", type=float, default=60, help="Turn wheel speed in mm/s (1-60)")
    parser.add_argument("--margin", type=float, default=40, help="Stop buffer inside the boundary, in pixels")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--record", action="store_true", help="Record camera images and active commands")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error("--seconds must be positive and finite")
    if not 1 <= args.speed <= 90 or not 1 <= args.turn_speed <= 60:
        parser.error("--speed must be 1-90 and --turn-speed must be 1-60")
    try:
        inner_bounds(args.margin)
    except ValueError as exc:
        parser.error(str(exc))
    return args


if __name__ == "__main__":
    args = parse_args()
    cozmo.robot.Robot.drive_off_charger_on_connect = False
    cozmo.run_program(partial(main, args=args))
