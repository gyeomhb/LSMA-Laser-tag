"""Fetch overhead snapshots in the background for pairing with Misty frames."""

import io
import threading
import time
from urllib.request import ProxyHandler, build_opener

from PIL import Image

OVERHEAD_FIELDS = ['overhead_image', 'overhead_valid', 'overhead_received_unix_s', 'overhead_age_s']


class OverheadCamera:
    def __init__(self, url):
        self.url = url
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.latest = None
        self.thread = threading.Thread(target=self.poll, daemon=True)
        self.thread.start()

    def poll(self):
        opener = build_opener(ProxyHandler({}))
        while not self.stopped.is_set():
            start = time.monotonic()
            try:
                with opener.open(self.url, timeout=1) as response:
                    data = response.read(8*1024*1024)
                with Image.open(io.BytesIO(data)) as frame:
                    if frame.format != 'JPEG':
                        raise ValueError('Overhead image is not JPEG')
                    frame.verify()
                latest = data, time.time(), time.monotonic()
            except Exception:
                latest = None
            with self.lock:
                self.latest = latest
            self.stopped.wait(max(0, 1/15-(time.monotonic()-start)))

    def snapshot(self):
        row = dict(zip(OVERHEAD_FIELDS, ('', False, '', '')))
        with self.lock:
            latest = self.latest
        if latest is None:
            return None, row
        data, received, monotonic = latest
        age = time.monotonic()-monotonic
        row.update(overhead_received_unix_s=received, overhead_age_s=age)
        if age > 0.5:
            return None, row
        row['overhead_valid'] = True
        return data, row

    def close(self):
        self.stopped.set()
