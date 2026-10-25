import base64
import csv
import io
import json
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock

from PIL import Image
from dataset_recorder import DatasetRecorder
from wasd_misty import FIELDS, MistyController, command_name, decode_frame, unwrap, velocities


class MistyTest(unittest.TestCase):
    def test_controls(self):
        for keys, expected in [({"w"}, (10, 0)), ({"s"}, (-10, 0)),
                               ({"a"}, (0, 10)), ({"d"}, (0, -10)),
                               ({"w", "space"}, (0, 0)), ({"w", "s"}, (0, 0))]:
            self.assertEqual(velocities(keys), expected)
        self.assertEqual(command_name((10, 10)), "forward_left")
        self.assertEqual(command_name((-10, -10)), "backward_right")

    def test_decode_and_record(self):
        source = Image.new("RGB", (32, 24), (255, 0, 0))
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode()
        for payload in [buffer.getvalue(), encoded, "data:image/png;base64," + encoded,
                        json.dumps({"result": {"base64": encoded}})]:
            frame = decode_frame(payload)
            self.assertEqual(frame.getpixel((0, 0)), (255, 0, 0))
        with tempfile.TemporaryDirectory() as directory:
            recorder = DatasetRecorder(directory, fields=FIELDS,
                                        metadata={"robot": "Misty 4", "velocity_units": "percent"})
            row = dict.fromkeys(FIELDS, "")
            row.update(command="forward", linear_velocity_percent=10, angular_velocity_percent=0)
            for i in range(4):
                row["frame_number"] = i
                recorder.offer_frame(source, row)
            recorder.close()
            self.assertIsNone(recorder.error)
            with (recorder.path / "labels.csv").open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([r["frame_number"] for r in rows], ["0", "1", "2", "3"])
            self.assertTrue(all((recorder.path / r["image"]).exists() for r in rows))

    def test_api_failure(self):
        self.assertEqual(unwrap({"status": "Success", "result": True}), True)
        with self.assertRaises(RuntimeError):
            unwrap({"status": "Failed", "error": "blocked"})


class MistyAsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_connect_uses_ip_without_serial_gate(self):
        controller = MistyController.__new__(MistyController)
        controller.ip = "192.168.1.38"
        controller.connection = Mock()
        controller.record_button = Mock()
        controller.request = AsyncMock(return_value={"serialNumber": "99999"})
        controller.send_drive = AsyncMock()
        await controller.connect()
        controller.send_drive.assert_awaited_once_with((0, 0))
        self.assertTrue(controller.connected)
        self.assertTrue(controller.stream_started)

    async def test_timed_drive_and_stop(self):
        controller = MistyController.__new__(MistyController)
        controller.request = AsyncMock(return_value=True)
        await controller.send_drive((10, -10))
        controller.request.assert_awaited_with("POST", "drive/time", {
            "LinearVelocity": 10, "AngularVelocity": -10, "TimeMs": 500}, timeout=1)
        self.assertEqual(controller.ack_values, (10, -10))
        await controller.send_drive((0, 0))
        controller.request.assert_awaited_with("POST", "drive/stop", {"Hold": False}, timeout=1)
        controller.keys = {"w"}
        controller.frame_number = 1
        self.assertEqual(controller.label(time.time())["command_state"], "transition")


if __name__ == "__main__":
    unittest.main()
