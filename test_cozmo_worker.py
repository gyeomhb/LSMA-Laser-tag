import asyncio
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cozmo_waypoint_worker import worker


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, lose_heartbeat=False):
        commands = queue.Queue()
        world = SimpleNamespace(latest_image=None)
        robot = SimpleNamespace(world=world, camera=SimpleNamespace(
            image_stream_enabled=False, color_image_enabled=False),
            is_on_charger=False, is_picked_up=False, stop_all_motors=Mock())
        clock = [0.0]
        events = []
        aborts = []
        original_sleep = asyncio.sleep

        def emit(event, **kwargs):
            events.append(event)
            if event == 'ready':
                commands.put({'command': 'start'})
            if event == 'running' and not lose_heartbeat:
                commands.put({'command': 'stop'})
            if event == 'stopped':
                commands.put({'command': 'quit'})

        async def fake_sleep(seconds):
            clock[0] += seconds
            world.latest_image = object()
            await original_sleep(0)

        async def drive(robot, speed, abort_requested, reverse_requested, navigation):
            while not abort_requested():
                await fake_sleep(0.02)
            aborts.append(True)

        with patch('cozmo_waypoint_worker.queue.Queue', return_value=commands), \
             patch('cozmo_waypoint_worker.TrackingClient'), \
             patch('cozmo_waypoint_worker.Navigation'), \
             patch('cozmo_waypoint_worker.threading.Thread'), \
             patch('cozmo_waypoint_worker.time', SimpleNamespace(monotonic=lambda: clock[0])), \
             patch('cozmo_waypoint_worker.asyncio.sleep', side_effect=fake_sleep), \
             patch('cozmo_waypoint_worker.emit', side_effect=emit), \
             patch('cozmo_waypoint_worker.run', side_effect=drive):
            await worker(robot)
        self.assertIn('ready', events)
        self.assertIn('running', events)
        self.assertGreaterEqual(robot.stop_all_motors.call_count, 2)
        self.assertFalse(robot.camera.image_stream_enabled)
        return events, aborts

    async def test_stop_request_interrupts_motion_and_quits(self):
        events, aborts = await self.exercise()
        self.assertEqual(aborts, [True])
        self.assertIn('stopped', events)

    async def test_lost_parent_heartbeat_stops_worker(self):
        events, _ = await self.exercise(lose_heartbeat=True)
        self.assertIn('error', events)
