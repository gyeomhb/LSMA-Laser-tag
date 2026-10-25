import csv
import tempfile
import unittest
from types import SimpleNamespace

from PIL import Image

from dataset_recorder import DatasetRecorder, command_name


class RecorderTest(unittest.TestCase):
    def test_frame_and_label_pairing_and_rate_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = DatasetRecorder(directory, fps=5)
            frame = Image.new("RGB", (320, 240), (255, 0, 0))
            image = SimpleNamespace(raw_image=frame, image_number=7, image_recv_time=123.0)
            recorder.offer(image, {"w", "a"}, (20, 100), -5)
            # This second frame is within the sampling interval and must be skipped.
            recorder.offer(image, {"s"}, (-60, -60), -5)
            frame.paste((0, 0, 255), (0, 0, 320, 240))
            recorder.close()
            recorder.close()
            self.assertIsNone(recorder.error)
            self.assertEqual(recorder.count, 1)
            with (recorder.path / "labels.csv").open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["command"], "forward_left")
            self.assertEqual(row["keys"], "a+w")
            self.assertEqual(row["image_received_unix_s"], "123.0")
            self.assertEqual(row["left_wheel_mmps"], "20")
            with Image.open(recorder.path / row["image"]) as saved:
                self.assertEqual(saved.size, (320, 240))
                self.assertEqual(saved.getpixel((0, 0)), (255, 0, 0))

    def test_uncapped_records_every_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = DatasetRecorder(directory)
            for number in range(10):
                image = SimpleNamespace(raw_image=Image.new("RGB", (32, 24)),
                                        image_number=number, image_recv_time=123 + number / 30)
                recorder.offer(image, set(), (0, 0), -5)
            recorder.close()
            self.assertIsNone(recorder.error)
            self.assertEqual(recorder.count, 10)
            self.assertEqual(recorder.dropped, 0)
            with (recorder.path / "labels.csv").open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([int(row["image_number"]) for row in rows], list(range(10)))
            self.assertTrue(all((recorder.path / row["image"]).exists() for row in rows))

    def test_command_labels(self):
        for speeds, expected in [((0, 0), "stop"), ((60, 60), "forward"),
                                 ((-60, -60), "backward"), ((-40, 40), "left"),
                                 ((40, -40), "right"), ((-20, -100), "backward_right")]:
            self.assertEqual(command_name(speeds), expected)


if __name__ == "__main__":
    unittest.main()
