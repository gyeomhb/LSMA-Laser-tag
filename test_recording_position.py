import csv
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from PIL import Image
from dataset_recorder import DatasetRecorder, COZMO_FIELDS
from recording_position import POSITION_FIELDS, position_row
from wasd_misty import FIELDS


class PositionRecordingTests(unittest.TestCase):
    def tracker(self, age=0):
        return Mock(snapshot=Mock(return_value=({'frame_age_seconds': age,
            'frame_number': 42, 'markers': [
                {'id': 5, 'center_pixels': [123, 234]},
                {'id': 8, 'center_pixels': [456, 567]}]}, 0.1)))

    def test_each_robot_gets_own_tag(self):
        self.assertEqual(position_row(self.tracker(), 5)['position_x_px'], 123)
        self.assertEqual(position_row(self.tracker(), 8)['position_x_px'], 456)

    def test_unavailable_stale_and_ambiguous_are_blank(self):
        tracker = self.tracker()
        for sample in (None, {'error': 'offline'}, {'frame_age_seconds': 2},
                       {'frame_age_seconds': 0, 'markers': []},
                       {'frame_age_seconds': 0, 'markers': [
                           {'id': 5, 'center_pixels': [1, 2]}]*2}):
            tracker.snapshot.return_value = sample, 0
            row = position_row(tracker, 5)
            self.assertFalse(row['position_valid'])
            self.assertEqual(row['position_x_px'], '')
            self.assertEqual(row['position_y_px'], '')

    def test_positions_written_to_both_csv_schemas(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            for tag, fields in ((5, COZMO_FIELDS+POSITION_FIELDS), (8, FIELDS)):
                recorder = DatasetRecorder(folder, fields=fields)
                frame = Image.new('RGB', (2, 2))
                row = position_row(self.tracker(), tag)
                if tag == 5:
                    recorder.offer(SimpleNamespace(image_number=1, image_recv_time=0,
                                   raw_image=frame), {'w'}, (90, 90), -5, position=row)
                else:
                    recorder.offer_frame(frame, dict(row, command='forward'))
                recorder.close()
                self.assertIsNone(recorder.error)
                with (recorder.path/'labels.csv').open(newline='') as handle:
                    saved = list(csv.DictReader(handle))[0]
                self.assertEqual(saved['position_tag_id'], str(tag))
                self.assertEqual(saved['position_valid'], 'True')
                self.assertEqual(float(saved['position_x_px']), row['position_x_px'])
                self.assertEqual(saved['command'], 'forward')
