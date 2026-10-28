"""Private Cozmo SDK process controlled by the Misty window over stdin/stdout."""

import argparse
import asyncio
import json
import queue
import sys
import threading
import time

import cozmo

from timed_cozmo import run
from cozmo_navigation import Navigation
from tracking_panel import DEFAULT_TRACKING_URL, TrackingClient


def emit(event, **values):
    print('COZMO_EVENT ' + json.dumps(dict(event=event, **values)), flush=True)


async def worker(robot):
    commands = queue.Queue()
    disconnected = threading.Event()
    def read_commands():
        try:
            for line in sys.stdin:
                commands.put(json.loads(line))
        finally:
            disconnected.set()
    threading.Thread(target=read_commands, daemon=True).start()
    original_stream = robot.camera.image_stream_enabled
    original_color = robot.camera.color_image_enabled
    job = None
    stop = True
    reverse_pending = False
    def take_reverse():
        nonlocal reverse_pending
        requested = reverse_pending
        reverse_pending = False
        return requested
    heartbeat = time.monotonic()
    tracker = None
    try:
        if robot.is_on_charger or robot.is_picked_up:
            raise ValueError('Place Cozmo on the floor, off its charger')
        robot.stop_all_motors()
        image_before = robot.world.latest_image
        robot.camera.color_image_enabled = True
        robot.camera.image_stream_enabled = True
        deadline = time.monotonic()+8
        while robot.world.latest_image is image_before:
            if disconnected.is_set() or time.monotonic() >= deadline:
                raise ValueError('No fresh Cozmo camera frame; check the Kindle app and SDK mode')
            await asyncio.sleep(0.05)
        tracker = TrackingClient(DEFAULT_TRACKING_URL)
        navigation = Navigation(tracker)
        deadline = time.monotonic()+8
        while not navigation.update(robot):
            if disconnected.is_set() or time.monotonic() >= deadline:
                raise ValueError('Initial position needs a fresh overhead reading of Cozmo tag 5')
            await asyncio.sleep(0.05)
        print('Position initialized from tag 5; odometry is primary.', flush=True)
        emit('ready')
        heartbeat = time.monotonic()
        while not disconnected.is_set():
            navigation.update(robot)
            while not commands.empty():
                command = commands.get_nowait().get('command')
                if command == 'ping':
                    heartbeat = time.monotonic()
                elif command == 'start' and job is None:
                    stop = False
                    reverse_pending = False
                    job = asyncio.create_task(run(robot, speed=90,
                        navigation=navigation,
                        reverse_requested=take_reverse,
                        abort_requested=lambda: stop or disconnected.is_set() or time.monotonic()-heartbeat > 2))
                    emit('running')
                elif command == 'reverse' and job is not None and not job.done() and not stop:
                    reverse_pending = True
                elif command == 'stop':
                    stop = True
                    robot.stop_all_motors()
                    if job is None:
                        emit('stopped')
                elif command == 'quit':
                    disconnected.set()
                    stop = True
                    robot.stop_all_motors()
            if time.monotonic()-heartbeat > 2:
                stop = True
                robot.stop_all_motors()
                emit('error', message='Misty controller heartbeat lost')
                break
            if job is not None and job.done():
                try:
                    job.result()
                    emit('stopped')
                except Exception as exc:
                    emit('error', message=str(exc))
                job = None
            await asyncio.sleep(0.02)
    except Exception as exc:
        emit('error', message=str(exc))
    finally:
        stop = True
        try:
            robot.stop_all_motors()
            if job is not None:
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)
        finally:
            if tracker is not None:
                tracker.close()
            robot.camera.image_stream_enabled = original_stream
            robot.camera.color_image_enabled = original_color


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    args = parser.parse_args()
    cozmo.robot.Robot.drive_off_charger_on_connect = False
    cozmo.run_program(worker)
