"""Record native camera frames with the command active at SDK receipt time."""

import csv
import json
from pathlib import Path
import queue
import threading
import time
from datetime import datetime, timezone


def command_name(speeds):
    left, right = speeds
    if left == right == 0:
        return "stop"
    forward, turn = left + right, left - right
    parts = []
    if forward:
        parts.append("forward" if forward > 0 else "backward")
    if turn:
        parts.append("right" if turn > 0 else "left")
    return "_".join(parts)


class DatasetRecorder:
    def __init__(self, root, fps=None, *, metadata=None, fields=None):
        if fps is not None and fps <= 0:
            raise ValueError("fps must be positive or None for every camera frame")
        self.path = Path(root) / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        (self.path / "images").mkdir(parents=True)
        self.interval = 0 if fps is None else 1 / fps
        self.started_at = time.monotonic()
        self.last_time = float("-inf")
        self.count = 0
        self.dropped = 0
        self.error = None
        self.pending = queue.Queue(maxsize=30)
        self.closed = False
        self.fields = fields
        metadata = metadata if metadata is not None else {
            "schema_version": 1, "target_fps": fps, "color": True,
            "sampling": "every received frame" if fps is None else "rate limited",
            "head_angle_degrees": -5, "image_format": "PNG, native resolution",
            "label_alignment": "Last PC-issued wheel command at SDK image receipt; not measured motion or exposure-time synchronization.",
            "stopped_frames_included": True,
            "wheel_speed_units": "mm/s",
        }
        (self.path / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def offer(self, image, keys, speeds, head_angle):
        row = {
            "image": "", "image_number": image.image_number,
            "image_received_unix_s": image.image_recv_time,
            "label_sampled_unix_s": time.time(),
            "keys": "+".join(sorted(keys)), "command": command_name(speeds),
            "left_wheel_mmps": speeds[0], "right_wheel_mmps": speeds[1],
            "head_angle_degrees": head_angle,
        }
        self.offer_frame(image.raw_image, row)

    def offer_frame(self, frame, row):
        now = time.monotonic()
        if self.closed or self.error or now - self.last_time < self.interval:
            return
        self.last_time = now
        try:
            self.pending.put_nowait((frame.copy(), dict(row)))
        except queue.Full:
            self.dropped += 1

    def _write(self):
        fields = self.fields or ["image", "image_number", "image_received_unix_s", "label_sampled_unix_s",
                  "keys", "command", "left_wheel_mmps", "right_wheel_mmps", "head_angle_degrees"]
        try:
            with (self.path / "labels.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                handle.flush()
                while True:
                    item = self.pending.get()
                    if item is None:
                        break
                    frame, row = item
                    row["image"] = "images/{:06d}.png".format(self.count)
                    frame.save(self.path / row["image"], compress_level=1)
                    writer.writerow(row)
                    handle.flush()
                    self.count += 1
        except Exception as exc:
            self.error = str(exc)

    def close(self):
        if self.closed:
            return
        self.closed = True
        while self.thread.is_alive():
            try:
                self.pending.put(None, timeout=0.1)
                break
            except queue.Full:
                continue
        self.thread.join()
