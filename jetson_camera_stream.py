"""Run on the Jetson: color MJPEG stream with optional ArUco pixel tracking.

Uses the Jetson's existing OpenCV installation, not the Windows environment.
"""

import argparse
import json
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2


def draw_boundaries(frame):
    """Display Cozmo's movement area after marker detection (pixel coordinates)."""
    color = (0, 220, 255)
    cv2.rectangle(frame, (50, 50), (900, 600), (0, 0, 0), 5)
    cv2.rectangle(frame, (50, 50), (900, 600), color, 2)
    for text, position in [
        ("Cozmo boundary: X 50-900 | Y 50-600", (50, 35)),
        ("(50, 50)", (58, 72)),
        ("(900, 600)", (760, 590)),
    ]:
        cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                    0.65, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                    0.65, color, 1, cv2.LINE_AA)


class Camera:
    def __init__(self, device):
        self.condition = threading.Condition()
        self.jpeg = None
        self.sequence = 0
        self.markers = []
        self.timestamp = None
        self.error = None
        self.stopped = threading.Event()
        self.device = device
        self.thread = threading.Thread(target=self.capture, daemon=True)
        self.thread.start()

    def capture(self):
        capture = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        try:
            if not capture.isOpened():
                raise RuntimeError("Cannot open camera " + self.device)
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            capture.set(cv2.CAP_PROP_FPS, 30)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            detector = cv2.aruco.ArucoDetector(
                cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
                cv2.aruco.DetectorParameters())
            while not self.stopped.is_set():
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError("Camera stopped delivering frames")
                timestamp = time.time()
                corners, ids, _ = detector.detectMarkers(frame)
                markers = []
                if ids is not None:
                    cv2.aruco.drawDetectedMarkers(frame, corners, ids)
                    for marker_id, points in zip(ids.flatten(), corners):
                        points = points.reshape(4, 2)
                        markers.append({
                            "id": int(marker_id),
                            "center_pixels": points.mean(axis=0).tolist(),
                            "corners_pixels": points.tolist(),
                        })
                draw_boundaries(frame)
                ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    raise RuntimeError("JPEG encoding failed")
                with self.condition:
                    self.jpeg = encoded.tobytes()
                    self.sequence += 1
                    self.timestamp = timestamp
                    self.markers = markers
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                self.error = str(exc)
                self.condition.notify_all()
            print("Camera error:", exc, flush=True)
        finally:
            capture.release()

    def status(self):
        with self.condition:
            return {
                "frame_number": self.sequence, "received_unix_s": self.timestamp,
                "dictionary": "DICT_4X4_50", "coordinates": "image pixels, not 3D pose",
                "markers": self.markers, "error": self.error,
                "frame_age_seconds": None if self.timestamp is None else time.time() - self.timestamp,
            }


def handler_for(camera):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/status":
                data = json.dumps(camera.status()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            if self.path not in ("/", "/stream.mjpg", "/snapshot.jpg"):
                self.send_error(404)
                return
            with camera.condition:
                camera.condition.wait_for(lambda: camera.jpeg is not None or camera.error, timeout=5)
                jpeg = camera.jpeg
                error = camera.error
            if jpeg is None or error:
                self.send_error(503, error or "Camera not ready")
                return
            if self.path == "/snapshot.jpg":
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(jpeg)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = -1
            try:
                while not camera.stopped.is_set():
                    with camera.condition:
                        ready = camera.condition.wait_for(
                            lambda: camera.sequence != last or camera.error or camera.stopped.is_set(),
                            timeout=5)
                        if not ready or camera.error or camera.stopped.is_set():
                            return
                        jpeg, last = camera.jpeg, camera.sequence
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="/dev/video6")
    parser.add_argument("--bind", default="192.168.1.37")
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()
    camera = Camera(args.device)
    server = ThreadingHTTPServer((args.bind, args.port), handler_for(camera))
    def stop_server(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_server)
    print("Camera stream: http://{}:{}/stream.mjpg".format(args.bind, args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        camera.stopped.set()
        with camera.condition:
            camera.condition.notify_all()
        server.server_close()
        camera.thread.join(timeout=3)


if __name__ == "__main__":
    main()
