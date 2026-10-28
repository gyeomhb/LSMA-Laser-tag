"""Cozmo camera: Space saves a PNG; Esc quits. Click the preview first."""

import argparse
import asyncio
from datetime import datetime
from functools import partial
from pathlib import Path
import time
import tkinter as tk

import cozmo
from PIL import ImageTk
from frame_rate import FrameLimiter


async def main(robot, folder):
    window = tk.Tk()
    window.title('Cozmo - Space: save picture | Esc: quit')
    preview = tk.Label(window, text='Waiting for Cozmo camera...')
    preview.pack()
    status = tk.StringVar(value='Click this window. Space saves. Esc quits.')
    tk.Label(window, textvariable=status).pack(padx=12, pady=12)
    latest = None
    received_at = 0
    shown_at = None
    preview_rate = FrameLimiter()
    running = True

    def close(event=None):
        nonlocal running
        running = False

    def on_image(evt, *, image, **kwargs):
        nonlocal latest, received_at
        latest = image.raw_image.copy()
        received_at = time.monotonic()

    def save(event=None):
        if latest is None or time.monotonic() - received_at > 2:
            status.set('No fresh camera picture. Wait for the stream.')
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (datetime.now().strftime('cozmo_%Y%m%d_%H%M%S_%f') + '.png')
            latest.save(path)
            status.set('Saved: ' + path.name)
            print('Saved:', path.resolve(), flush=True)
        except OSError as exc:
            status.set('Could not save: ' + str(exc))

    window.bind('<space>', save)
    window.bind('<Escape>', close)
    window.protocol('WM_DELETE_WINDOW', close)
    original_stream = robot.camera.image_stream_enabled
    original_color = robot.camera.color_image_enabled
    handler = robot.world.add_event_handler(cozmo.world.EvtNewCameraImage, on_image)
    try:
        robot.camera.color_image_enabled = True
        robot.camera.image_stream_enabled = True
        await robot.set_head_angle(cozmo.util.degrees(-5)).wait_for_completed()
        while running:
            window.update()
            if latest is not None and shown_at != received_at and preview_rate.ready():
                photo = ImageTk.PhotoImage(latest)
                preview.configure(image=photo, text='')
                preview.image = photo
                shown_at = received_at
            await asyncio.sleep(0.03)
    finally:
        handler.disable()
        try:
            robot.camera.image_stream_enabled = original_stream
            robot.camera.color_image_enabled = original_color
        finally:
            window.destroy()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, default=Path(__file__).parent / 'cozmo_screenshots')
    args = parser.parse_args()
    cozmo.robot.Robot.drive_off_charger_on_connect = False
    cozmo.run_program(partial(main, folder=args.folder))
