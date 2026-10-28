import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from dataset_recorder import DatasetRecorder
from frame_rate import CAMERA_FPS, FrameLimiter


class FrameRateTest(unittest.TestCase):
    def test_preview_caps_fast_source_and_preserves_slow_source(self):
        for source_fps, expected in [(30, 15), (15, 15), (10, 10)]:
            limiter = FrameLimiter()
            with patch('frame_rate.time.monotonic', side_effect=[i/source_fps for i in range(source_fps)]):
                self.assertEqual(sum(limiter.ready() for _ in range(source_fps)), expected)

    def test_recording_30_to_15_keeps_matching_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = DatasetRecorder(directory, fps=CAMERA_FPS, fields=['image', 'command'])
            frame = Image.new('RGB', (2, 2))
            with patch('dataset_recorder.time.monotonic', side_effect=[i/30 for i in range(30)]):
                for i in range(30):
                    recorder.offer_frame(frame, {'command': str(i)})
            recorder.close()
            self.assertIsNone(recorder.error)
            self.assertEqual(recorder.count, 15)
            import csv
            with (recorder.path / 'labels.csv').open(newline='') as handle:
                self.assertEqual([int(row['command']) for row in csv.DictReader(handle)], list(range(0, 30, 2)))
