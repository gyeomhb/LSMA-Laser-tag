import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from timed_cozmo import run


class TimedMovementTests(unittest.IsolatedAsyncioTestCase):
    async def test_boundary_and_manual_reversal_together_reverse_only_once(self):
        clock = [0.0]
        robot = SimpleNamespace(is_picked_up=False, is_on_charger=False,
                                drive_wheel_motors=Mock(), stop_all_motors=Mock())
        navigation = Mock()
        navigation.should_reverse.side_effect = [True, False, False]
        rng = Mock()
        rng.uniform.side_effect = [5, 8]
        async def sleep(seconds):
            clock[0] += seconds
        with patch('timed_cozmo.time', SimpleNamespace(monotonic=lambda: clock[0])), \
             patch('timed_cozmo.asyncio.sleep', side_effect=sleep):
            await run(robot, navigation=navigation, rng=rng,
                      reverse_requested=lambda: clock[0] == 0,
                      abort_requested=lambda: clock[0] >= 0.1)
        self.assertTrue(all(call.args == (-90, -90)
                            for call in robot.drive_wheel_motors.call_args_list))
        self.assertEqual(navigation.should_reverse.call_args_list[0].args, (1,))
        self.assertEqual(navigation.should_reverse.call_args_list[1].args, (-1,))
        self.assertEqual(rng.uniform.call_count, 2)

    async def test_reverse_interrupts_drive_or_turn_and_resets_timer(self):
        for reverse_at in (1.0, 5.1):
            clock = [0.0]
            requested = [False]
            robot = SimpleNamespace(is_picked_up=False, is_on_charger=False,
                                    drive_wheel_motors=Mock(), stop_all_motors=Mock())
            rng = Mock()
            rng.uniform.side_effect = lambda low, high: low
            rng.choice.return_value = 60
            observed = []
            def reverse():
                if clock[0] >= reverse_at and not requested[0]:
                    requested[0] = True
                    return True
                return False
            async def sleep(seconds):
                observed.append((clock[0], robot.drive_wheel_motors.call_args.args))
                clock[0] += seconds
            with patch('timed_cozmo.time', SimpleNamespace(monotonic=lambda: clock[0])), \
                 patch('timed_cozmo.asyncio.sleep', side_effect=sleep):
                await run(robot, rng=rng, reverse_requested=reverse,
                          abort_requested=lambda: clock[0] >= reverse_at+5.2)
            reversed_commands = [(t, wheels) for t, wheels in observed if t >= reverse_at]
            self.assertEqual(reversed_commands[0][1], (-90, -90))
            start = reversed_commands[0][0]
            self.assertTrue(all(w == (-90, -90) for t, w in reversed_commands if t < start+5))
            self.assertIn((60, -60), [w for t, w in reversed_commands if t >= start+5])
            robot.stop_all_motors.assert_called_once()

    async def test_forward_then_turn_and_stop(self):
        for direction in (-60, 60):
            clock = [0.0]
            robot = SimpleNamespace(is_picked_up=False, is_on_charger=False,
                                    drive_wheel_motors=Mock(), stop_all_motors=Mock())
            rng = Mock()
            rng.uniform.side_effect = [5.0, 0.4, 10.0]
            rng.choice.return_value = direction

            async def sleep(seconds):
                clock[0] += seconds

            with patch('timed_cozmo.time', SimpleNamespace(monotonic=lambda: clock[0])), \
                 patch('timed_cozmo.asyncio.sleep', side_effect=sleep):
                await run(robot, abort_requested=lambda: clock[0] >= 5.6, rng=rng)
            commands = [call.args for call in robot.drive_wheel_motors.call_args_list]
            self.assertEqual(commands[0], (90, 90))
            self.assertIn((direction, -direction), commands)
            self.assertEqual(commands[-1], (90, 90))
            self.assertEqual(robot.stop_all_motors.call_count, 1)
            self.assertEqual(rng.uniform.call_args_list[0].args, (5, 10))

    async def test_abort_and_pickup_prevent_movement(self):
        for picked_up in (False, True):
            robot = SimpleNamespace(is_picked_up=picked_up, is_on_charger=False,
                                    drive_wheel_motors=Mock(), stop_all_motors=Mock())
            await run(robot, abort_requested=lambda: not picked_up)
            robot.drive_wheel_motors.assert_not_called()
            robot.stop_all_motors.assert_called_once()
