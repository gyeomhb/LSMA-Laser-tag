"""Nonblocking overhead-camera coordinate display for both robot controllers."""

import json
import math
import threading
import time
import tkinter as tk
from tkinter import ttk
from urllib.request import ProxyHandler, build_opener

DEFAULT_TRACKING_URL = "http://192.168.1.37:8088/status"
STALE_SECONDS = 2.0
MAX_FRAME_STALL = 0.5


def coordinate_text(sample, elapsed=0, marker_id=None):
    """Display only fresh coordinates; never infer a tag-to-robot mapping."""
    if not isinstance(sample, dict):
        return "Waiting for tracking data..."
    if sample.get("error"):
        return "Tracking unavailable: " + str(sample["error"])
    age = sample.get("frame_age_seconds")
    if age is None:
        return "Waiting for an overhead camera frame..."
    age = float(age) + max(elapsed, 0)
    if not math.isfinite(age) or age < 0 or age > STALE_SECONDS:
        return "Tracking stale - no current coordinates"
    lines = []
    for marker in sample.get("markers", []):
        tag = int(marker["id"])
        if marker_id is not None and tag != marker_id:
            continue
        x, y = (float(value) for value in marker["center_pixels"])
        if not math.isfinite(x) or not math.isfinite(y):
            continue
        lines.append("Tag {}:  X = {:.1f} px    Y = {:.1f} px".format(tag, x, y))
    if not lines:
        return "Tag {} not visible".format(marker_id) if marker_id is not None else "No tags visible"
    return "\n".join(lines)


class TrackingClient:
    def __init__(self, url):
        self.url = url
        self.lock = threading.Lock()
        self.sample = None
        self.received_at = time.monotonic()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()

    def _poll(self):
        opener = build_opener(ProxyHandler({}))
        last_frame = None
        last_change = time.monotonic()
        while not self.stopped.is_set():
            try:
                with opener.open(self.url, timeout=1) as response:
                    sample = json.loads(response.read(1024 * 1024))
                coordinate_text(sample)  # Validate fields before handing them to Tk.
                now = time.monotonic()
                frame = sample.get("frame_number")
                if frame != last_frame:
                    last_frame, last_change = frame, now
                elif now - last_change > MAX_FRAME_STALL:
                    sample = {"error": "Overhead camera frames stopped updating"}
            except Exception as exc:
                sample = {"error": str(exc)}
            with self.lock:
                self.sample = sample
                self.received_at = time.monotonic()
            self.stopped.wait(0.1)

    def text(self, marker_id=None):
        with self.lock:
            return coordinate_text(self.sample, time.monotonic() - self.received_at, marker_id)

    def snapshot(self):
        with self.lock:
            return self.sample, time.monotonic() - self.received_at

    def close(self):
        self.stopped.set()


class TrackingPanel:
    def __init__(self, parent, url=DEFAULT_TRACKING_URL, marker_id=None):
        self.parent = parent
        self.marker_id = marker_id
        self.client = TrackingClient(url)
        self.frame = tk.LabelFrame(parent, text="Overhead tracking - image coordinates")
        self.frame.pack(fill="x", padx=20, pady=(0, 8))
        self.value = tk.StringVar(value="Waiting for tracking data...")
        tk.Label(self.frame, textvariable=self.value, font=("Segoe UI", 11),
                 justify="left", wraplength=600).pack(anchor="w", padx=8, pady=4)
        tk.Label(self.frame, text="Origin: top-left | X right, Y down | IDs are marker IDs",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=8, pady=(0, 4))
        row = tk.Frame(self.frame)
        row.pack(fill="x", padx=8)
        tk.Label(row, text="This robot's tag:").pack(side="left")
        self.selection = tk.StringVar(value=str(marker_id) if marker_id is not None else "Select tag")
        self.selector = ttk.Combobox(row, textvariable=self.selection, state="readonly", width=12)
        self.selector.pack(side="left", padx=6)
        self.selector.bind("<<ComboboxSelected>>", self._select_marker)
        self.timer = None
        self._refresh()

    def _refresh(self):
        self.value.set(self.client.text(self.marker_id))
        sample, _ = self.client.snapshot()
        ids = {self.marker_id} if self.marker_id is not None else set()
        if isinstance(sample, dict) and not sample.get("error"):
            ids.update(int(m["id"]) for m in sample.get("markers", []))
        self.selector.configure(values=["Select tag"] + [str(i) for i in sorted(ids)])
        self.timer = self.parent.after(100, self._refresh)

    def _select_marker(self, event=None):
        selected = self.selection.get()
        self.marker_id = int(selected) if selected != "Select tag" else None

    def close(self):
        self.client.close()
        if self.timer is not None:
            self.parent.after_cancel(self.timer)
            self.timer = None
