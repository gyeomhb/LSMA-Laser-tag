"""Hold WASD in the control window to drive Cozmo."""

import asyncio
import argparse
from functools import partial
import tkinter as tk
import time
from pathlib import Path

import cozmo
from PIL import Image, ImageTk
from dataset_recorder import DatasetRecorder
from tracking_panel import DEFAULT_TRACKING_URL, TrackingPanel


def wheel_speeds(keys):
    if "space" in keys:
        return 0, 0
    forward = 60 * (("w" in keys) - ("s" in keys))
    turn = 40 * (("d" in keys) - ("a" in keys))
    return forward + turn, forward - turn


async def main(robot: cozmo.robot.Robot, tracking_url=DEFAULT_TRACKING_URL, marker_id=5):
    window = tk.Tk()
    window.title("Cozmo WASD control + camera")
    window.geometry("680x820")
    window.resizable(False, False)
    tk.Label(window, text="Cozmo keyboard control", font=("Segoe UI", 18)).pack(pady=16)
    tk.Label(window, text="Hold W / S: forward / backward\n"
                         "Hold A / D: turn left / right\n"
                         "Space: stop     Esc: quit\n\n"
                         "Click this window before driving.\n"
                         "Release keys or switch windows to stop.",
             font=("Segoe UI", 11)).pack()
    status = tk.StringVar(value="Stopped")
    tk.Label(window, textvariable=status, font=("Segoe UI", 11)).pack(pady=12)
    recording_status = tk.StringVar(value="Recording off")
    recorder = None
    applied_keys = set()
    applied_speeds = (0, 0)

    def toggle_recording():
        nonlocal recorder
        if recorder is None:
            try:
                recorder = DatasetRecorder(Path(__file__).parent / "dataset_cozmo")
                record_button.configure(text="Stop recording")
            except OSError as exc:
                recording_status.set("Cannot record: " + str(exc))
        else:
            keys.clear()
            robot.stop_all_motors()
            recorder.close()
            recording_status.set("Saved {} frames to {}{}".format(
                recorder.count, recorder.path.name,
                " | ERROR: " + recorder.error if recorder.error else ""))
            recorder = None
            record_button.configure(text="Start recording")

    record_button = tk.Button(window, text="Start recording", command=toggle_recording,
                              takefocus=False)
    record_button.pack()
    tk.Label(window, textvariable=recording_status, wraplength=640).pack(pady=6)
    tracking = TrackingPanel(window, tracking_url, marker_id)
    camera_view = tk.Label(window, text="Waiting for Cozmo's camera...",
                           bg="black", fg="white")
    camera_view.pack(fill="both", expand=True, padx=20, pady=(0, 20))
    keys = set()
    running = True

    def on_camera_image(evt, *, image, **kwargs):
        if recorder is not None and running:
            recorder.offer(image, applied_keys, applied_speeds, robot.head_angle.degrees)

    camera_handler = robot.world.add_event_handler(cozmo.world.EvtNewCameraImage, on_camera_image)

    def close(event=None):
        nonlocal running
        keys.clear()
        running = False

    def press(event):
        key = event.keysym.lower()
        if key == "escape":
            close()
        elif key in {"w", "a", "s", "d", "space"}:
            # A stop clears prior movement; release and press again to resume.
            if key == "space":
                keys.clear()
            if "space" not in keys:
                keys.add(key)

    window.bind("<KeyPress>", press)
    window.bind("<KeyRelease>", lambda event: keys.discard(event.keysym.lower()))
    window.bind("<FocusOut>", lambda event: keys.clear())
    window.protocol("WM_DELETE_WINDOW", close)
    previous = None
    previous_image = None
    stream_was_enabled = robot.camera.image_stream_enabled
    color_was_enabled = robot.camera.color_image_enabled
    try:
        robot.stop_all_motors()
        robot.camera.color_image_enabled = True
        robot.camera.image_stream_enabled = True
        await robot.set_head_angle(cozmo.util.degrees(-5)).wait_for_completed()
        while running:
            window.update()
            speeds = wheel_speeds(keys) if running else (0, 0)
            if speeds != previous:
                if speeds == (0, 0):
                    robot.stop_all_motors()
                    status.set("Stopped")
                else:
                    robot.drive_wheel_motors(*speeds)
                    status.set("Driving")
                previous = speeds
            applied_keys = keys.copy()
            applied_speeds = speeds
            if recorder is not None:
                if recorder.error:
                    keys.clear()
                    robot.stop_all_motors()
                    toggle_recording()
                    applied_keys = set()
                    applied_speeds = (0, 0)
                else:
                    saved_fps = recorder.count / max(time.monotonic() - recorder.started_at, 0.001)
                    recording_status.set("RECORDING: {} saved | {} dropped | {:.1f} avg FPS | uncapped".format(
                        recorder.count, recorder.dropped, saved_fps))
            camera_image = robot.world.latest_image
            if running and camera_image is not None and camera_image is not previous_image:
                frame = camera_image.raw_image.copy()
                frame.thumbnail((640, 480), Image.Resampling.BILINEAR)
                photo = ImageTk.PhotoImage(frame, master=window)
                camera_view.configure(image=photo, text="")
                camera_view.image = photo  # Keep Tk's image alive between frames.
                previous_image = camera_image
            await asyncio.sleep(0.02)
    finally:
        try:
            robot.stop_all_motors()
            robot.camera.image_stream_enabled = stream_was_enabled
            robot.camera.color_image_enabled = color_was_enabled
        finally:
            camera_handler.disable()
            try:
                if recorder is not None:
                    recorder.close()
            finally:
                tracking.close()
                window.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking-url", default=DEFAULT_TRACKING_URL)
    parser.add_argument("--marker-id", type=int, default=5, help="This robot's ArUco marker ID (default: 5)")
    args = parser.parse_args()
    # Do not move off the charger automatically when opening the controller.
    cozmo.robot.Robot.drive_off_charger_on_connect = False
    cozmo.run_program(partial(main, tracking_url=args.tracking_url, marker_id=args.marker_id))
