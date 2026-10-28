"""Misty camera: Space saves a PNG; Esc quits. Click the preview first."""

import argparse
import asyncio
from contextlib import suppress
from datetime import datetime
from pathlib import Path
import time
import tkinter as tk

import aiohttp
from PIL import Image, ImageTk

from wasd_misty import DEFAULT_IP, decode_frame, unwrap
from frame_rate import FrameLimiter


async def main(ip, folder):
    window = tk.Tk()
    window.title('Misty - Space: save picture | Esc: quit')
    preview = tk.Label(window, text='Connecting to Misty...')
    preview.pack()
    status = tk.StringVar(value='Click this window. Space saves. Esc quits.')
    tk.Label(window, textvariable=status).pack(padx=12, pady=12)
    frame = None
    received_at = 0
    preview_rate = FrameLimiter()
    running = True
    started = False
    task = None

    def close(event=None):
        nonlocal running
        running = False

    def save(event=None):
        if frame is None or time.monotonic() - received_at > 2:
            status.set('No fresh camera picture. Wait for the stream.')
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (datetime.now().strftime('misty_%Y%m%d_%H%M%S_%f') + '.png')
            frame.save(path)
            status.set('Saved: ' + path.name)
            print('Saved:', path.resolve(), flush=True)
        except OSError as exc:
            status.set('Could not save: ' + str(exc))

    window.bind('<space>', save)
    window.bind('<Escape>', close)
    window.protocol('WM_DELETE_WINDOW', close)

    async with aiohttp.ClientSession() as session:
        async def request(action):
            payload = ({'Port': 5678, 'Rotation': 0, 'Width': 640, 'Height': 480,
                        'Quality': 90, 'Overlay': False} if action == 'start' else {})
            async with session.post('http://' + ip + '/api/videostreaming/' + action,
                                    json=payload, timeout=aiohttp.ClientTimeout(total=20)) as response:
                response.raise_for_status()
                unwrap(await response.json(content_type=None))

        async def camera():
            nonlocal frame, received_at, started
            await request('start')
            started = True
            async with session.ws_connect('ws://' + ip + ':5678', receive_timeout=8,
                                          max_msg_size=16 * 1024 * 1024) as socket:
                async for message in socket:
                    if message.type == aiohttp.WSMsgType.ERROR:
                        raise RuntimeError('Camera connection failed')
                    if message.type not in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                        continue
                    frame = decode_frame(message.data).transpose(Image.Transpose.ROTATE_270)
                    received_at = time.monotonic()
                    if not preview_rate.ready():
                        continue
                    photo = ImageTk.PhotoImage(frame)
                    preview.configure(image=photo, text='')
                    preview.image = photo
            raise RuntimeError('Camera stream closed')

        try:
            task = asyncio.create_task(camera())
            while running:
                window.update()
                if task.done():
                    try:
                        task.result()
                    except Exception as exc:
                        status.set('Camera error: ' + str(exc))
                    # Keep the error visible until the user closes the window.
                    while running:
                        window.update()
                        await asyncio.sleep(0.03)
                    break
                await asyncio.sleep(0.03)
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
            if started:
                with suppress(Exception):
                    await request('stop')
            window.destroy()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ip', default=DEFAULT_IP)
    parser.add_argument('--folder', type=Path, default=Path(__file__).parent / 'misty_screenshots')
    args = parser.parse_args()
    try:
        asyncio.run(main(args.ip, args.folder))
    except KeyboardInterrupt:
        pass
