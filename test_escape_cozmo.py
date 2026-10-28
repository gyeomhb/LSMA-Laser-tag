import math
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from escape_cozmo import choose_target, wheels_for, run, validate
from random_cozmo import inner_bounds


class EscapeTests(unittest.TestCase):
    def test_forward_reverse_and_turn_direction(self):
        self.assertEqual(wheels_for((400, 300, 0), (600, 300), 90), (90, 90))
        self.assertEqual(wheels_for((400, 300, math.pi), (200, 300), 40), (40, 40))
        left, right = wheels_for((400, 300, math.pi), (600, 300), 40)
        self.assertAlmostEqual(left, -40)
        self.assertAlmostEqual(right, -40)
        left, right = wheels_for((400, 300, 0), (400, 500), 40)
        self.assertGreater(left, right)

    def test_escape_paths_stay_in_bounds_and_clear_of_misty(self):
        for coz in [(614, 481, math.pi), (120, 120, 0), (820, 520, 0)]:
            misty = (602, 368, math.pi)
            tx, ty = choose_target(coz, misty)
            xmin, xmax, ymin, ymax = inner_bounds(60)
            self.assertTrue(xmin < tx < xmax and ymin < ty < ymax)
            self.assertAlmostEqual(math.hypot(tx-coz[0], ty-coz[1]), 140)
            for i in range(1, 11):
                x = coz[0]+(tx-coz[0])*i/10
                y = coz[1]+(ty-coz[1])*i/10
                self.assertGreaterEqual(math.hypot(x-misty[0], y-misty[1]), 85)

    def test_missing_misty_and_stale_tracking_block(self):
        sample = {'error': None, 'frame_age_seconds': 0.01,
                  'markers': [{'id': 5, 'center_pixels': [400, 300]}]}
        with self.assertRaisesRegex(ValueError, '8 missing'):
            validate(sample, 0)
        with self.assertRaisesRegex(ValueError, 'stale'):
            validate(sample, 1)


class EscapeRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_tracking_failure_stops_without_drive(self):
        robot = SimpleNamespace(stop_all_motors=Mock(), drive_wheel_motors=Mock(),
                                is_picked_up=False, is_on_charger=False)
        tracker = Mock()
        tracker.snapshot.return_value = ({'error': 'offline'}, 0)
        args = SimpleNamespace(tracking_url='unused', seconds=1, speed=40)
        with patch('escape_cozmo.TrackingClient', return_value=tracker), \
             patch('escape_cozmo.keyboard_stop', return_value=False), \
             patch('escape_cozmo.Path.read_text', return_value='{"5": 0, "8": 0}'):
            await run(robot, args)
        robot.drive_wheel_motors.assert_not_called()
        self.assertEqual(robot.stop_all_motors.call_count, 2)
        tracker.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
