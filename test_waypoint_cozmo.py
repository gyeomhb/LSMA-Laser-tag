import random
import math
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from waypoint_cozmo import WaypointPlan, validate_points, run, automatic_points, ForwardSteering, ArrivalBrake, HeadingHold


class WaypointTests(unittest.TestCase):
    def test_heading_hold_corrects_drift_and_wrap(self):
        robot = SimpleNamespace(pose_angle=SimpleNamespace(radians=math.radians(179)))
        hold = HeadingHold(robot)
        self.assertEqual(hold.wheels(robot, 90), (90, 90))
        robot.pose_angle.radians = math.radians(-179)
        left, right = hold.wheels(robot, 90)
        self.assertGreater(left, right)
        self.assertLess(left-right, 4)
        robot.pose_angle.radians = math.radians(169)
        left, right = hold.wheels(robot, 90)
        self.assertGreater(right, left)
        self.assertGreater(min(left, right), 0)
        self.assertEqual(HeadingHold(SimpleNamespace()).wheels(SimpleNamespace(), 90), (90, 90))

    def test_arrival_brake_waits_for_stop_and_fresh_stable_positions(self):
        brake = ArrivalBrake((940, 430), 1, 0)
        self.assertFalse(brake.ready((940, 430), 2, 0.1))
        self.assertFalse(brake.ready((945, 430), 3, 0.35))
        self.assertFalse(brake.ready((945, 430), 3, 0.6))
        self.assertFalse(brake.ready((945, 430), 4, 0.65))
        self.assertTrue(brake.ready((946, 430), 5, 0.75))

    def test_arrival_brake_times_out_instead_of_driving_while_moving(self):
        brake = ArrivalBrake((940, 430), 1, 0)
        for i in range(1, 10):
            self.assertFalse(brake.ready((940+4*i, 430), i+1, i*0.2))
        with self.assertRaisesRegex(ValueError, 'did not settle'):
            brake.ready((980, 430), 11, 2)

    def test_automatic_points_are_valid_and_cover_area(self):
        points = automatic_points()
        self.assertEqual(len(points), 14)
        self.assertEqual(points, [(x, y) for y in (130, 280, 430, 530)
                                 for x in (130, 335, 540, 745, 950)
                                 if x in (130, 950) or y in (130, 530)])
        self.assertEqual(validate_points(points), points)
        self.assertGreater(max(x for x, y in points)-min(x for x, y in points), 500)
        self.assertGreater(max(y for x, y in points)-min(y for x, y in points), 200)

    def test_target_changes_on_arrival_or_random_deadline(self):
        plan = WaypointPlan([(200, 200), (600, 200)], random.Random(4))
        target, changed = plan.update((400, 350), now=0)
        self.assertTrue(changed)
        self.assertGreaterEqual(plan.deadline, 7)
        self.assertLessEqual(plan.deadline, 10)
        self.assertEqual(plan.update((400, 350), now=plan.deadline-0.001), (target, False))
        deadline = plan.deadline
        next_target, changed = plan.update((400, 350), now=deadline)
        self.assertTrue(changed)
        self.assertNotEqual(next_target, target)
        self.assertTrue(7 <= plan.deadline-deadline <= 10)
        target = next_target
        for _ in range(100):
            next_target, changed = plan.update(target, now=deadline)
            self.assertTrue(changed)
            self.assertNotEqual(target, next_target)
            target = next_target

    def test_forward_steering_turns_for_targets_behind(self):
        for heading in (math.pi, math.pi/2, -math.pi/2):
            left, right = ForwardSteering().wheels((400, 300, heading), (600, 300), 90, now=0)
            self.assertAlmostEqual(left + right, 0)
            self.assertGreater(abs(left), 0)
        steering = ForwardSteering()
        for i in range(20):
            wheels = steering.wheels((400, 300, 0), (600, 300), 90, now=i*0.05)
        self.assertEqual(wheels, (90, 90))

    def test_hysteresis_prevents_mode_flapping(self):
        steering = ForwardSteering()
        for i, degrees in enumerate((60, 25, 19, 21, 18, 9)):
            steering.wheels((400, 300, math.radians(degrees)), (600, 300), 90, now=i*0.05)
            self.assertTrue(steering.turning)
        steering.wheels((400, 300, math.radians(7)), (600, 300), 90, now=0.3)
        self.assertFalse(steering.turning)
        for i, degrees in enumerate((19, 21, 18, 22, 29)):
            left, right = steering.wheels((400, 300, math.radians(degrees)), (600, 300), 90, now=0.35+i*0.05)
            self.assertFalse(steering.turning)
            self.assertGreaterEqual(min(left, right), 0)
        steering.wheels((400, 300, math.radians(31)), (600, 300), 90, now=0.6)
        self.assertTrue(steering.turning)

    def test_wrap_noise_does_not_reverse_uturn(self):
        steering = ForwardSteering()
        commands = [steering.wheels((400, 300, math.radians(h)), (600, 300), 90, now=i*0.05)[0]
                    for i, h in enumerate((179, -179, 178, -178, 175))]
        self.assertTrue(all(v < 0 for v in commands))
        self.assertTrue(all(abs(b-a) <= 12.000001 for a, b in zip(commands, commands[1:])))
        steering.reset()
        self.assertIsNone(steering.uturn_sign)
        self.assertEqual(steering.forward, 0)

    def test_small_heading_noise_has_no_steering(self):
        steering = ForwardSteering()
        for i, degrees in enumerate((0, 2, -2, 1, -1)):
            left, right = steering.wheels((400, 300, math.radians(degrees)), (600, 300), 90, now=i*0.05)
            self.assertEqual(left, right)

    def test_every_grid_point_excludes_all_eight_neighbors(self):
        points = automatic_points()
        cells = [(row, col) for row in range(4) for col in range(5)
                 if row in (0, 3) or col in (0, 4)]
        for previous in range(len(points)):
            rng = Mock()
            rng.uniform.return_value = 8
            rng.choice.side_effect = lambda choices: choices[0]
            plan = WaypointPlan(points, rng)
            plan.index = previous
            plan.update(points[previous])
            choices = rng.choice.call_args[0][0]
            row, col = cells[previous]
            expected = [i for i, (r, c) in enumerate(cells)
                        if max(abs(r-row), abs(c-col)) > 1]
            self.assertEqual(choices, expected)

    def test_no_fallback_to_neighbor_if_no_valid_target(self):
        plan = WaypointPlan([(200, 200), (300, 200)])
        plan.index = 0
        with self.assertRaisesRegex(ValueError, 'non-neighboring'):
            plan.update((200, 200))

    def test_does_not_choose_start_position_as_target(self):
        plan = WaypointPlan([(200, 200), (600, 200)])
        self.assertEqual(plan.update((200, 200))[0], (600, 200))

    def test_invalid_points(self):
        for points in [[], [(200, 200)], [(200, 200), (200, 200)],
                       [(200, 200), (220, 220)], [(200, 200), (1000, 300)],
                       [(float('nan'), 200), (600, 300)]]:
            with self.assertRaises(ValueError):
                validate_points(points)


class WaypointMotionTests(unittest.IsolatedAsyncioTestCase):
    async def test_allows_motion_outside_boundary(self):
        for x, expected_drives in [(966, 2), (999, 2), (1000, 2), (1100, 2), (20, 2)]:
            robot = SimpleNamespace(is_on_charger=False, is_picked_up=False,
                                    drive_wheel_motors=Mock(), stop_all_motors=Mock())
            sample = {'frame_age_seconds': 0, 'markers': [{'id': 5,
                      'center_pixels': [x, 430],
                      'corners_pixels': [[x-10, 420], [x+10, 420], [x+10, 440], [x-10, 440]]}]}
            tracker = Mock()
            tracker.snapshot.side_effect = [(sample, 0), (sample, 0), ({'error': 'lost'}, 0)]
            args = SimpleNamespace(tracking_url='unused', seconds=1, speed=90)
            with patch('waypoint_cozmo.TrackingClient', return_value=tracker), \
                 patch('waypoint_cozmo.keyboard_stop', return_value=False):
                await run(robot, args, automatic_points(), 0,
                          abort_requested=lambda: tracker.snapshot.call_count >= 3)
            self.assertEqual(robot.drive_wheel_motors.call_count, expected_drives)

    async def test_tracking_failure_prevents_motion(self):
        robot = SimpleNamespace(is_on_charger=False, is_picked_up=False,
                                drive_wheel_motors=Mock(), stop_all_motors=Mock())
        tracker = Mock()
        tracker.snapshot.return_value = ({'error': 'offline'}, 0)
        args = SimpleNamespace(tracking_url='unused', seconds=1, speed=90)
        with patch('waypoint_cozmo.TrackingClient', return_value=tracker), \
             patch('waypoint_cozmo.keyboard_stop', return_value=False):
            await run(robot, args, [(200, 200), (600, 200)], 0)
        robot.drive_wheel_motors.assert_not_called()
        self.assertEqual(robot.stop_all_motors.call_count, 2)
        tracker.close.assert_called_once()

    async def test_switch_brakes_and_loss_keeps_braking(self):
        robot = SimpleNamespace(is_on_charger=False, is_picked_up=False,
                                drive_wheel_motors=Mock(), stop_all_motors=Mock())
        def sample(x):
            return {'frame_age_seconds': 0, 'markers': [{'id': 5, 'center_pixels': [x, 200],
                     'corners_pixels': [[x-10, 190], [x+10, 190], [x+10, 210], [x-10, 210]]}]}, 0
        tracker = Mock()
        tracker.snapshot.side_effect = [sample(200), sample(200), sample(600), ({'error': 'lost'}, 0)]
        args = SimpleNamespace(tracking_url='unused', seconds=5, speed=90)
        with patch('waypoint_cozmo.TrackingClient', return_value=tracker), \
             patch('waypoint_cozmo.keyboard_stop', return_value=False):
            await run(robot, args, [(200, 200), (600, 200)], 0,
                      abort_requested=lambda: tracker.snapshot.call_count >= 4)
        # Only the first target drives. Arrival's stop cannot be overwritten by
        # a turn command; subsequent tracking loss preserves the stopped state.
        self.assertEqual(robot.drive_wheel_motors.call_count, 1)
        self.assertEqual(robot.stop_all_motors.call_count, 4)

    async def test_loss_drives_straight_then_reacquisition_updates(self):
        robot = SimpleNamespace(is_on_charger=False, is_picked_up=False,
                                drive_wheel_motors=Mock(), stop_all_motors=Mock())
        sample = {'frame_age_seconds': 0, 'markers': [{'id': 5,
                  'center_pixels': [200, 200],
                  'corners_pixels': [[190, 190], [210, 190], [210, 210], [190, 210]]}]}
        tracker = Mock()
        def snapshots():
            yield sample, 0
            yield sample, 0
            for lost in ({'markers': [], 'frame_age_seconds': 0}, {'error': 'offline'}):
                yield lost, 0
                robot.drive_wheel_motors.assert_called_with(90, 90)
                self.assertEqual(robot.stop_all_motors.call_count, 2)
            yield sample, 0
            yield dict(sample, markers=[dict(sample['markers'][0], center_pixels=[1000, 200])]), 0
        tracker.snapshot.side_effect = snapshots()
        args = SimpleNamespace(tracking_url='unused', seconds=5, speed=90)
        with patch('waypoint_cozmo.TrackingClient', return_value=tracker):
            await run(robot, args, [(200, 200), (600, 200)], 0,
                      abort_requested=lambda: tracker.snapshot.call_count >= 6)
        self.assertEqual(robot.drive_wheel_motors.call_count, 5)
        self.assertEqual(robot.stop_all_motors.call_count, 3)


if __name__ == '__main__':
    unittest.main()
