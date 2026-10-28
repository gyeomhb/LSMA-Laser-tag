"""Misty 4: WASD, color camera, and image/command recording capped at 15 FPS.

Run with .venv/Scripts/python.exe wasd_misty.py.
Labels describe requested/acknowledged commands, not measured motion.
"""

import argparse
import asyncio
import base64
from contextlib import suppress
import io
import json
from pathlib import Path
import time
import tkinter as tk

import aiohttp
from PIL import Image, ImageTk

from dataset_recorder import DatasetRecorder
from frame_rate import CAMERA_FPS, FrameLimiter
from robot_startup import preflight, open_misty_camera

DEFAULT_IP = "192.168.1.38"
FIELDS = ["image", "frame_number", "received_unix_s", "keys", "requested_command",
          "command", "linear_velocity_percent", "angular_velocity_percent",
          "command_sent_unix_s", "command_ack_unix_s", "command_state"]


def velocities(keys):
    if "space" in keys:
        return 0, 0
    return 15 * (("w" in keys) - ("s" in keys)), 15 * (("a" in keys) - ("d" in keys))


def command_name(values):
    linear, angular = values
    parts = []
    if linear:
        parts.append("forward" if linear > 0 else "backward")
    if angular:
        parts.append("left" if angular > 0 else "right")
    return "_".join(parts) or "stop"


def unwrap(response):
    if isinstance(response, list) and len(response) == 1:
        response = response[0]
    if not isinstance(response, dict):
        raise ValueError("Unexpected Misty API response")
    if str(response.get("status", "")).lower() != "success":
        raise RuntimeError(str(response.get("error", response)))
    return response.get("result")


def decode_frame(payload):
    if isinstance(payload, str):
        if payload.lstrip().startswith(("{", "[", '"')):
            payload = json.loads(payload)
        if isinstance(payload, dict):
            for key in ("base64", "image", "data", "result"):
                if key in payload:
                    return decode_frame(payload[key])
            raise ValueError("Camera message does not contain an image")
        if isinstance(payload, str):
            payload = base64.b64decode(payload.split(",", 1)[-1], validate=True)
    if isinstance(payload, dict):
        return decode_frame(json.dumps(payload))
    with Image.open(io.BytesIO(payload)) as image:
        return image.convert("RGB")


class MistyController:
    def __init__(self, ip, cozmo=None):
        self.ip = ip
        self.cozmo = cozmo
        self.cozmo_tasks = []
        self.cozmo_pending = False
        self.window = tk.Tk()
        self.window.title("Misty 4 - WASD + camera + dataset")
        self.window.minsize(780, 1)
        self.connection = tk.StringVar(value="Connecting to " + ip)
        tk.Label(self.window, textvariable=self.connection, wraplength=740).pack(pady=8)
        controls = tk.Frame(self.window)
        controls.pack()
        self.record_button = tk.Button(controls, text="Start recording", state="disabled",
                                       takefocus=False, command=self.toggle_recording)
        self.record_button.grid(row=0, column=1, padx=8)
        self.record_status = tk.StringVar(value="Recording off")
        tk.Label(self.window, textvariable=self.record_status, wraplength=740).pack(pady=8)
        self.cozmo_enabled = tk.BooleanVar(value=False)
        self.cozmo_toggle = tk.Checkbutton(controls, text="Cozmo OFF",
            variable=self.cozmo_enabled, command=self.toggle_cozmo, takefocus=False,
            indicatoron=False,
            state='normal' if cozmo is not None else 'disabled')
        if cozmo is not None:
            self.cozmo_toggle.grid(row=0, column=0, padx=8)
        self.cozmo_status = tk.StringVar(value='Cozmo ready - OFF' if cozmo else 'Cozmo unavailable')
        if cozmo is not None:
            tk.Label(self.window, textvariable=self.cozmo_status, wraplength=740).pack()
        self.camera_label = tk.Label(self.window, text="Waiting for camera...", bg="black", fg="white")
        self.camera_label.pack(fill="both", expand=True, padx=15, pady=15)
        self.keys = set()
        self.running = True
        self.connected = False
        self.recorder = None
        self.frame = None
        self.frame_number = 0
        self.last_frame_at = 0
        self.ack_values = (0, 0)
        self.ack_time = 0
        self.sent_time = 0
        self.ack_monotonic = 0
        self.in_flight = False
        self.serial = None
        self.stream_started = getattr(cozmo, 'misty_stream_ready', False)
        self.session = None
        self.save_tasks = []
        self.window.bind("<KeyPress>", self.press)
        self.window.bind("<KeyRelease>", lambda e: self.keys.discard(e.keysym.lower()))
        self.window.bind("<FocusOut>", lambda e: self.keys.clear())
        self.window.protocol("WM_DELETE_WINDOW", self.close)

    def press(self, event):
        key = event.keysym.lower()
        if key == "escape":
            self.close()
        elif key == 'r':
            if key not in self.keys and self.cozmo is not None and self.cozmo_enabled.get():
                self.keys.add(key)
                self.cozmo_tasks.append(asyncio.create_task(self.reverse_cozmo()))
        elif key in {"w", "a", "s", "d", "space"}:
            if key == "space":
                self.keys.clear()
                if getattr(self, 'cozmo', None) is not None:
                    self.cozmo_enabled.set(False)
                    self.toggle_cozmo()
            if "space" not in self.keys and self.connected:
                self.keys.add(key)

    def close(self):
        self.keys.clear()
        self.running = False

    def toggle_cozmo(self):
        self.cozmo_pending = True
        self.cozmo_toggle.configure(text='Cozmo ON' if self.cozmo_enabled.get() else 'Cozmo OFF')
        self.cozmo_tasks.append(asyncio.create_task(self.set_cozmo(self.cozmo_enabled.get())))

    async def set_cozmo(self, enabled):
        try:
            await self.cozmo.send('start' if enabled else 'stop')
            self.cozmo_status.set('Cozmo starting...' if enabled else 'Cozmo stopping...')
        except Exception as exc:
            self.cozmo_pending = False
            self.cozmo_enabled.set(False)
            self.cozmo_toggle.configure(text='Cozmo OFF')
            self.cozmo_status.set('Cozmo: ' + str(exc))

    async def reverse_cozmo(self):
        try:
            await self.cozmo.send('reverse')
        except Exception as exc:
            self.cozmo_status.set('Cozmo: ' + str(exc))

    def update_cozmo(self):
        if self.cozmo is None:
            return
        while not self.cozmo.events.empty():
            event = self.cozmo.events.get_nowait()
            kind = event['event']
            if kind == 'running':
                self.cozmo_pending = False
                self.cozmo_status.set('Cozmo running - random turns / 5-10 sec / edge reversal')
            elif kind in ('stopped', 'error'):
                self.cozmo_pending = False
                self.cozmo_enabled.set(False)
                self.cozmo_status.set(event.get('message', 'Cozmo stopped - OFF'))
        # Cozmo's control is independent of Misty's camera. Never lock out OFF
        # while waiting for the worker to acknowledge a start/stop command.
        self.cozmo_toggle.configure(
            text='Cozmo ON' if self.cozmo_enabled.get() else 'Cozmo OFF',
            state='normal' if not self.cozmo.error or self.cozmo_enabled.get() or self.cozmo_pending else 'disabled')
        self.cozmo_tasks = [task for task in self.cozmo_tasks if not task.done()]

    async def request(self, method, path, payload=None, timeout=3):
        async with self.session.request(method, "http://" + self.ip + "/api/" + path,
                                        json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
            response.raise_for_status()
            return unwrap(await response.json(content_type=None))

    async def send_drive(self, values):
        self.in_flight = True
        sent = time.time()
        try:
            if values == (0, 0):
                await self.request("POST", "drive/stop", {"Hold": False}, timeout=1)
            else:
                await self.request("POST", "drive/time", {
                    "LinearVelocity": values[0], "AngularVelocity": values[1], "TimeMs": 500}, timeout=1)
            self.ack_values = values
            self.sent_time = sent
            self.ack_time = time.time()
            self.ack_monotonic = time.monotonic()
        finally:
            self.in_flight = False

    async def drive_loop(self):
        try:
            while self.running and self.connected:
                # Do not drive blind if camera delivery stops.
                wanted = velocities(self.keys) if time.monotonic() - self.last_frame_at < 2 else (0, 0)
                if wanted != self.ack_values or (wanted != (0, 0) and time.monotonic() - self.ack_monotonic > 0.15):
                    await self.send_drive(wanted)
                await asyncio.sleep(0.02)
        except Exception as exc:
            self.fail("Drive connection failed: " + str(exc))

    def fail(self, message):
        print(message, flush=True)
        self.keys.clear()
        self.connected = False
        self.connection.set(message + " — close and reopen to retry")
        self.record_button.configure(state="disabled")

    def toggle_recording(self):
        if self.recorder is None:
            if not self.connected or self.frame is None:
                return
            metadata = {
                "schema_version": 1, "robot": "Misty 4", "serial": self.serial, "ip": self.ip,
                "sampling": "rate limited", "target_fps": CAMERA_FPS, "color": True,
                "camera_transport": "websocket", "stream_port": getattr(self, 'misty_port', getattr(self.cozmo, 'misty_port', 5678)),
                "requested_width": 640, "requested_height": 480,
                "image_rotation_clockwise_degrees": 90,
                "image_format": "PNG; decoded stream frame, no resizing",
                "velocity_units": "percent (-100 to 100); positive angular means left",
                "head_angle": "unchanged; not measured",
                "label_alignment": "Last HTTP-acknowledged command at PC frame receipt. command_state marks transitions and expired timed commands. Not exposure-time synchronization or measured motion.",
                "stopped_frames_included": True,
            }
            try:
                self.recorder = DatasetRecorder(Path(__file__).parent / "datasets_misty4",
                                                fps=CAMERA_FPS, metadata=metadata, fields=FIELDS)
            except OSError as exc:
                self.record_status.set("Cannot record: " + str(exc))
                return
            self.record_button.configure(text="Stop recording")
        else:
            self.keys.clear()
            # Flush disk writes off the GUI/event-loop thread.
            recorder, self.recorder = self.recorder, None
            self.record_button.configure(text="Saving...", state="disabled")
            self.save_tasks.append(asyncio.create_task(self.finish_recording(recorder)))

    async def finish_recording(self, recorder):
        await asyncio.get_running_loop().run_in_executor(None, recorder.close)
        self.record_status.set("Saved {} frames: {}{}".format(recorder.count, recorder.path,
                                   " | ERROR: " + recorder.error if recorder.error else ""))
        self.record_button.configure(text="Start recording", state="normal" if self.connected else "disabled")

    def label(self, received):
        state = "acknowledged"
        if self.in_flight or velocities(self.keys) != self.ack_values:
            state = "transition"
        elif self.ack_values != (0, 0) and time.monotonic() - self.ack_monotonic > 0.5:
            state = "expired"
        return {"image": "", "frame_number": self.frame_number, "received_unix_s": received,
                "keys": "+".join(sorted(self.keys)), "requested_command": command_name(velocities(self.keys)),
                "command": command_name(self.ack_values), "linear_velocity_percent": self.ack_values[0],
                "angular_velocity_percent": self.ack_values[1], "command_sent_unix_s": self.sent_time,
                "command_ack_unix_s": self.ack_time, "command_state": state}

    async def camera_loop(self):
        try:
            socket = getattr(self, 'misty_socket', getattr(self.cozmo, 'misty_socket', None))
            if socket is None:
                socket = await open_misty_camera(self.session, self.ip)
            async with socket:
                async for message in socket:
                    if not self.running or not self.connected:
                        break
                    if message.type not in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                        if message.type == aiohttp.WSMsgType.ERROR:
                            raise RuntimeError("Camera websocket error")
                        continue
                    received = time.time()
                    self.frame_number += 1
                    row = self.label(received)
                    frame = decode_frame(message.data).transpose(Image.Transpose.ROTATE_270)
                    self.frame = frame
                    if self.frame_number == 1:
                        print("Camera frame received:", frame.size, frame.mode, flush=True)
                    self.last_frame_at = time.monotonic()
                    if self.recorder is not None:
                        self.recorder.offer_frame(frame, row)
            if self.running:
                self.fail("Camera stream closed")
        except Exception as exc:
            self.fail("Camera failed: " + str(exc))

    async def connect(self):
        info = await self.request("GET", "device")
        self.serial = str(info.get("serialNumber", ""))
        await self.send_drive((0, 0))
        if not getattr(self, 'stream_started', False):
            await self.request("POST", "videostreaming/start", {
                "Port": 5678, "Rotation": 0, "Width": 640, "Height": 480,
                "Quality": 90, "Overlay": False}, timeout=20)
        self.stream_started = True
        self.connected = True
        self.connection.set("Connected: {} | 15% drive / 15% turn".format(self.ip))
        self.record_button.configure(state="normal")
        print("Connected to Misty at", self.ip, flush=True)

    async def run(self):
        tasks = []
        shown = None
        preview_rate = FrameLimiter()
        async with aiohttp.ClientSession(trust_env=False) as self.session:
            connection_task = asyncio.create_task(self.connect())
            try:
                while self.running:
                    self.window.update()
                    self.update_cozmo()
                    if connection_task is not None and connection_task.done():
                        try:
                            connection_task.result()
                            tasks = [asyncio.create_task(self.drive_loop()), asyncio.create_task(self.camera_loop())]
                        except Exception as exc:
                            self.fail("Connection failed: " + str(exc))
                            print("Connection failed:", repr(exc), flush=True)
                        connection_task = None
                    if self.frame is not None and self.frame is not shown and preview_rate.ready():
                        preview = self.frame.copy()
                        preview.thumbnail((740, 550), Image.Resampling.BILINEAR)
                        photo = ImageTk.PhotoImage(preview, master=self.window)
                        self.camera_label.configure(image=photo, text="")
                        self.camera_label.image = photo
                        shown = self.frame
                    if self.recorder is not None:
                        if self.recorder.error:
                            self.keys.clear()
                            self.toggle_recording()
                        else:
                            rate = self.recorder.count / max(time.monotonic() - self.recorder.started_at, 0.001)
                            self.record_status.set("RECORDING: {} saved | {} dropped | {:.1f} avg FPS | 15 FPS cap".format(
                                self.recorder.count, self.recorder.dropped, rate))
                    await asyncio.sleep(0.02)
            finally:
                self.keys.clear()
                if self.cozmo is not None:
                    for task in self.cozmo_tasks:
                        task.cancel()
                    await asyncio.gather(*self.cozmo_tasks, return_exceptions=True)
                    with suppress(Exception):
                        await self.cozmo.send('stop')
                if connection_task is not None:
                    tasks.append(connection_task)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if self.serial is not None:
                    with suppress(Exception):
                        await self.send_drive((0, 0))
                if self.stream_started:
                    with suppress(Exception):
                        await self.request("POST", "videostreaming/stop", {})
                        if self.cozmo is not None:
                            self.cozmo.misty_stream_ready = False
                if self.recorder is not None:
                    await asyncio.get_running_loop().run_in_executor(None, self.recorder.close)
                await asyncio.gather(*self.save_tasks, return_exceptions=True)
                self.window.destroy()


async def launch(args):
    cozmo = None
    try:
        cozmo = await preflight(args.ip, decode_frame, unwrap)
        if getattr(args, 'check_only', False):
            return
        await MistyController(args.ip, cozmo=cozmo).run()
    finally:
        if cozmo is not None:
            await cozmo.close()
            if getattr(cozmo, 'misty_socket', None) is not None:
                await cozmo.misty_socket.close()
            if getattr(cozmo, 'misty_session', None) is not None:
                await cozmo.misty_session.close()
            # Covers check-only mode and failures before the window owns cleanup.
            if getattr(cozmo, 'misty_stream_ready', False):
                async with aiohttp.ClientSession() as session:
                    with suppress(Exception):
                        async with session.post('http://'+args.ip+'/api/videostreaming/stop',
                                                json={}, timeout=aiohttp.ClientTimeout(total=3)):
                            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", default=DEFAULT_IP)
    parser.add_argument("--check-only", action="store_true", help="Check all robot connections without opening controls")
    args = parser.parse_args()
    try:
        asyncio.run(launch(args))
    except Exception as exc:
        print('Startup/controller failed:', str(exc) or type(exc).__name__, flush=True)
        raise SystemExit(1)
