import math
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from cozmo_navigation import Navigation, WIDTH_MM, HEIGHT_MM


def robot(x=0, y=0, yaw=0, origin=1):
    return SimpleNamespace(pose=SimpleNamespace(is_valid=True, origin_id=origin,
        position=SimpleNamespace(x=x, y=y),
        rotation=SimpleNamespace(angle_z=SimpleNamespace(radians=yaw))))


def sample(frame=1, x=525, y=325, heading=0):
    dx, dy = 10*math.cos(heading), 10*math.sin(heading)
    return {'frame_number': frame, 'frame_age_seconds': 0,
            'markers': [{'id': 5, 'center_pixels': [x, y],
                         'corners_pixels': [[x+dx, y+dy], [x+dx, y+dy], [x, y], [x, y]]}]}


class NavigationTests(unittest.TestCase):
    def setup_nav(self, heading=0, yaw=0):
        tracker = Mock()
        tracker.snapshot.return_value = (sample(heading=heading), 0)
        nav = Navigation(tracker, offset=0)
        self.assertTrue(nav.update(robot(yaw=yaw)))
        tracker.snapshot.return_value = ({'error': 'offline'}, 0)
        return nav, tracker

    def test_initialization_requires_unique_fresh_tag5(self):
        tracker = Mock()
        nav = Navigation(tracker, offset=0)
        for data in (None, {'error': 'offline'}, dict(sample(), frame_age_seconds=2),
                     dict(sample(), markers=[]),
                     dict(sample(), markers=sample()['markers']*2)):
            tracker.snapshot.return_value = (data, 0)
            self.assertFalse(nav.update(robot()))
        tracker.snapshot.return_value = (sample(), 0)
        self.assertTrue(nav.update(robot()))
        self.assertEqual(nav.position, (WIDTH_MM/2, HEIGHT_MM/2, 0))

    def test_odometry_continues_with_tracking_absent_and_reflects_y(self):
        nav, _ = self.setup_nav()
        nav.update(robot(x=100, y=50, yaw=math.pi/2))
        self.assertAlmostEqual(nav.position[0], 1125)
        self.assertAlmostEqual(nav.position[1], 550)
        self.assertAlmostEqual(nav.position[2], -math.pi/2)
        nav.update(robot(x=100, y=150, yaw=math.pi/2))
        self.assertAlmostEqual(nav.position[1], 450)

    def test_alignment_for_nonzero_initial_yaw_and_heading(self):
        nav, _ = self.setup_nav(heading=math.pi, yaw=math.pi/2)
        nav.update(robot(y=100, yaw=math.pi/2))
        self.assertAlmostEqual(nav.position[0], 925)
        self.assertAlmostEqual(nav.position[1], 600)

    def test_correction_is_small_once_per_frame_and_outliers_ignored(self):
        nav, tracker = self.setup_nav()
        tracker.snapshot.return_value = (sample(frame=2, x=545), 0)
        nav.update(robot())
        corrected = nav.position
        self.assertTrue(1025 < corrected[0] < (545-50)*2050/950)
        nav.update(robot())
        self.assertEqual(nav.position, corrected)
        tracker.snapshot.return_value = (sample(frame=3, x=950), 0)
        nav.update(robot())
        self.assertEqual(nav.position, corrected)

    def test_pose_reset_needs_tracking_instead_of_applying_origin_jump(self):
        nav, tracker = self.setup_nav()
        with self.assertRaisesRegex(ValueError, 'odometry reset'):
            nav.update(robot(x=9999, origin=2))
        tracker.snapshot.return_value = (sample(frame=2), 0)
        nav.update(robot(x=9999, origin=2))
        self.assertEqual(nav.position, (1025, 600, 0))

    def test_all_edges_forward_backward_and_rearming(self):
        for x, y, heading in ((100, 600, math.pi), (1950, 600, 0),
                              (1025, 100, -math.pi/2), (1025, 1100, math.pi/2)):
            nav, _ = self.setup_nav()
            nav.position = x, y, heading
            self.assertTrue(nav.should_reverse(1))
            self.assertFalse(nav.should_reverse(1))
            self.assertFalse(nav.should_reverse(-1))
            self.assertTrue(nav.should_reverse(1))
            nav.position = x, y, heading+math.pi
            nav.latched.clear()
            self.assertFalse(nav.should_reverse(1))
            self.assertTrue(nav.should_reverse(-1))

    def test_outside_can_move_inward_and_corner_triggers_once(self):
        nav, _ = self.setup_nav()
        nav.position = -50, 600, 0
        self.assertFalse(nav.should_reverse(1))
        self.assertTrue(nav.should_reverse(-1))
        nav.position = 100, 100, -3*math.pi/4
        nav.latched.clear()
        self.assertTrue(nav.should_reverse(1))
        self.assertFalse(nav.should_reverse(1))
        self.assertFalse(nav.should_reverse(-1))
