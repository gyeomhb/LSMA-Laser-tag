"""Timed random driving with manual and optional arena-edge reversal."""

import asyncio
import random
import time


async def run(robot, speed=90, abort_requested=lambda: False, rng=None,
              reverse_requested=lambda: False, navigation=None):
    rng = rng or random.Random()
    direction = 1
    turning = False
    left = right = speed
    deadline = time.monotonic() + rng.uniform(5, 10)
    try:
        while True:
            if abort_requested() or robot.is_picked_up or robot.is_on_charger:
                return
            now = time.monotonic()
            manual_reverse = reverse_requested()
            edge_reverse = navigation is not None and navigation.should_reverse(direction)
            if manual_reverse or edge_reverse:
                direction *= -1
                turning = False
                left = right = direction * speed
                deadline = now + rng.uniform(5, 10)
                if edge_reverse:
                    print('Near boundary; reversing for a new 5-10 second drive.', flush=True)
            elif now >= deadline:
                if turning:
                    turning = False
                    left = right = direction * speed
                    deadline = now + rng.uniform(5, 10)
                else:
                    turning = True
                    left = rng.choice((-60, 60))
                    right = -left
                    deadline = now + rng.uniform(0.4, 1.2)
            robot.drive_wheel_motors(left, right)
            await asyncio.sleep(0.05)
    finally:
        robot.stop_all_motors()
