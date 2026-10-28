"""Arena position from SDK odometry, anchored and corrected by overhead tag 5."""

import json
import math
from pathlib import Path

WIDTH_MM, HEIGHT_MM = 2050.0, 1200.0
MARGIN_MM = 150.0


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


class Navigation:
    def __init__(self, tracker, offset=None):
        self.tracker = tracker
        if offset is None:
            offset = float(json.loads(Path(__file__).with_name(
                'escape_calibration.json').read_text(encoding='utf-8'))['5'])
        if not math.isfinite(offset):
            raise ValueError('Invalid tag 5 facing calibration')
        self.offset = offset
        self.position = None
        self.previous = None
        self.last_frame = None
        self.latched = set()

    def observation(self):
        sample, elapsed = self.tracker.snapshot()
        try:
            if sample.get('error'):
                return None
            age = float(sample['frame_age_seconds']) + elapsed
            frame = sample['frame_number']
            if not math.isfinite(age) or not 0 <= age <= 0.5 or frame == self.last_frame:
                return None
            markers = [m for m in sample['markers'] if m['id'] == 5]
            if len(markers) != 1:
                return None
            marker = markers[0]
            x, y = map(float, marker['center_pixels'])
            corners = marker['corners_pixels']
            dx = (corners[0][0]+corners[1][0])/2-x
            dy = (corners[0][1]+corners[1][1])/2-y
            if not all(math.isfinite(v) for v in (x, y, dx, dy)) or math.hypot(dx, dy) < 2:
                return None
            heading = wrap(math.atan2(dy, dx)+self.offset)
            self.last_frame = frame
            return ((x-50)*WIDTH_MM/950, (y-50)*HEIGHT_MM/550, heading)
        except (AttributeError, KeyError, TypeError, ValueError, IndexError):
            return None

    def update(self, robot):
        pose = robot.pose
        if pose is None or not pose.is_valid:
            raise ValueError('Cozmo odometry unavailable; put it down and restart Cozmo')
        odom = (pose.position.x, pose.position.y, pose.rotation.angle_z.radians, pose.origin_id)
        if not all(math.isfinite(v) for v in odom[:3]):
            raise ValueError('Invalid Cozmo odometry')
        observed = self.observation()
        if self.position is None:
            if observed is None:
                return False
            self.position = observed
        elif self.previous[3] != odom[3]:
            if observed is None:
                raise ValueError('Cozmo odometry reset; show tag 5 and restart Cozmo')
            self.position = observed
            self.latched.clear()
        else:
            x, y, heading = self.position
            px, py, yaw, _ = self.previous
            # SDK Y is left; arena Y is down. Reflect Y while aligning headings.
            angle = heading+yaw
            dx, dy = odom[0]-px, odom[1]-py
            x += math.cos(angle)*dx + math.sin(angle)*dy
            y += math.sin(angle)*dx - math.cos(angle)*dy
            heading = wrap(heading-wrap(odom[2]-yaw))
            if observed is not None:
                ox, oy, oh = observed
                error = wrap(oh-heading)
                # Ignore large outliers. Apply each fresh frame only once.
                if math.hypot(ox-x, oy-y) <= 300 and abs(error) <= math.radians(35):
                    x += 0.15*(ox-x)
                    y += 0.15*(oy-y)
                    heading = wrap(heading+0.10*error)
            self.position = x, y, heading
        self.previous = odom
        return True

    def should_reverse(self, direction):
        x, y, heading = self.position
        vx, vy = direction*math.cos(heading), direction*math.sin(heading)
        edges = {'left': (x, -vx), 'right': (WIDTH_MM-x, vx),
                 'top': (y, -vy), 'bottom': (HEIGHT_MM-y, vy)}
        trigger = False
        for edge, (distance, outward) in edges.items():
            if distance > MARGIN_MM+50 or outward < -0.1:
                self.latched.discard(edge)
            if distance <= MARGIN_MM and outward > 0.1 and edge not in self.latched:
                self.latched.add(edge)
                trigger = True
        return trigger
