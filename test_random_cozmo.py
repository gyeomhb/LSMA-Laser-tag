import random
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from random_cozmo import choose_action, inner_bounds, run_segment


def position(x=400, y=300, tag=5):
    return {"error": None, "frame_age_seconds": 0.01,
            "markers": [{"id": tag, "center_pixels": [x, y]}]}, 0


class RandomPlanningTest(unittest.TestCase):
    def test_margin_and_actions(self):
        self.assertEqual(inner_bounds(40), (90, 860, 90, 560))
        for value in (-1, 275, float("nan")):
            with self.assertRaises(ValueError):
                inner_bounds(value)
        rng = random.Random(5)
        actions = [choose_action(rng) for _ in range(100)]
        self.assertTrue(all(0.2 <= action[3] <= 0.7 for action in actions))
        self.assertTrue(all(max(abs(x) for x in action[2]) <= 40 for action in actions))
        self.assertGreater(len({action[0] for action in actions}), 4)


class RandomMotionTest(unittest.IsolatedAsyncioTestCase):
    def robot(self):
        return SimpleNamespace(is_on_charger=False, is_picked_up=False,
                               drive_wheel_motors=Mock(), stop_all_motors=Mock())

    async def test_no_movement_outside_inner_boundary(self):
        robot = self.robot()
        tracker = Mock()
        tracker.snapshot.return_value = position(y=570)
        result = await run_segment(robot, tracker, 5, inner_bounds(40), (40, 40), 0.02)
        self.assertIn("boundary", result)
        robot.drive_wheel_motors.assert_not_called()
        robot.stop_all_motors.assert_called()

    async def test_tracking_loss_stops_an_active_segment(self):
        robot = self.robot()
        tracker = Mock()
        tracker.snapshot.side_effect = [position(), ({"error": "offline"}, 0)]
        result = await run_segment(robot, tracker, 5, inner_bounds(40), (40, 40), 0.1)
        self.assertIn("unavailable", result)
        robot.drive_wheel_motors.assert_called_once_with(40, 40)
        robot.stop_all_motors.assert_called_once()

    async def test_successful_segment_stops(self):
        robot = self.robot()
        tracker = Mock()
        tracker.snapshot.return_value = position()
        self.assertIsNone(await run_segment(robot, tracker, 5, inner_bounds(40), (30, -30), 0.01))
        robot.stop_all_motors.assert_called_once()

    async def test_missing_tag_does_not_use_manual_override(self):
        robot = self.robot()
        tracker = Mock()
        tracker.snapshot.return_value = position(tag=8)
        self.assertIsNotNone(await run_segment(robot, tracker, 5, inner_bounds(40), (40, 40), 0.1))
        robot.drive_wheel_motors.assert_not_called()

    async def test_keyboard_stop_and_pickup_prevent_start(self):
        for picked_up, abort in [(False, True), (True, False)]:
            robot = self.robot()
            robot.is_picked_up = picked_up
            tracker = Mock()
            tracker.snapshot.return_value = position()
            result = await run_segment(robot, tracker, 5, inner_bounds(40),
                                       (40, 40), 0.1, lambda: abort)
            self.assertIsNotNone(result)
            robot.drive_wheel_motors.assert_not_called()

    async def test_motor_exception_still_stops(self):
        robot = self.robot()
        robot.drive_wheel_motors.side_effect = RuntimeError("SDK error")
        tracker = Mock()
        tracker.snapshot.return_value = position()
        with self.assertRaises(RuntimeError):
            await run_segment(robot, tracker, 5, inner_bounds(40), (40, 40), 0.1)
        robot.stop_all_motors.assert_called_once()


if __name__ == "__main__":
    unittest.main()
