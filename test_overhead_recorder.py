import csv
import io
import tempfile
import threading
import time
import unittest
from PIL import Image

from dataset_recorder import DatasetRecorder
from overhead_recorder import OverheadCamera, OVERHEAD_FIELDS


class OverheadTests(unittest.TestCase):
    def test_stale_or_missing_frames_are_not_paired(self):
        camera = OverheadCamera.__new__(OverheadCamera)
        camera.lock = threading.Lock()
        camera.latest = None
        self.assertEqual(camera.snapshot()[1]['overhead_valid'], False)
        camera.latest = b'image', time.time(), time.monotonic()-1
        self.assertIsNone(camera.snapshot()[0])
        camera.latest = b'image', time.time(), time.monotonic()
        self.assertEqual(camera.snapshot()[0], b'image')
        self.assertTrue(camera.snapshot()[1]['overhead_valid'])

    def test_csv_pairs_saved_images_and_marks_missing(self):
        frame = Image.new('RGB', (4, 3))
        buffer = io.BytesIO()
        frame.save(buffer, format='JPEG')
        data = buffer.getvalue()
        with tempfile.TemporaryDirectory() as folder:
            recorder = DatasetRecorder(folder, fields=['image']+OVERHEAD_FIELDS)
            recorder.offer_frame(frame, {'overhead_received_unix_s': 123, 'overhead_age_s': 0.1}, overhead=data)
            recorder.offer_frame(frame, {})
            recorder.close()
            self.assertIsNone(recorder.error)
            with (recorder.path/'labels.csv').open(newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]['overhead_image'], 'overhead_images/000000.jpg')
            self.assertEqual((recorder.path/rows[0]['overhead_image']).read_bytes(), data)
            self.assertTrue((recorder.path/rows[0]['image']).exists())
            self.assertEqual(rows[1]['overhead_image'], '')
            self.assertEqual(rows[1]['overhead_valid'], 'False')
