"""Run Misty WASD, camera, and recording without Cozmo or tracking."""

import argparse
import asyncio
from contextlib import suppress

from robot_startup import ensure_misty_camera
from wasd_misty import DEFAULT_IP, MistyController, decode_frame, unwrap


class MistyOnlyController(MistyController):
    async def connect(self):
        await self.request('GET', 'device')
        await self.send_drive((0, 0))
        # Also clean up if stream setup fails partway through.
        self.stream_started = True
        self.misty_socket, data, self.misty_port = await ensure_misty_camera(
            self.session, self.ip, unwrap)
        decode_frame(data)
        await super().connect()

    async def run(self):
        try:
            await super().run()
        finally:
            socket = getattr(self, 'misty_socket', None)
            if socket is not None:
                with suppress(Exception):
                    await socket.close()


async def launch(args):
    await MistyOnlyController(args.ip).run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ip', default=DEFAULT_IP)
    args = parser.parse_args()
    try:
        asyncio.run(launch(args))
    except Exception as exc:
        print('Misty controller failed:', str(exc) or type(exc).__name__, flush=True)
        raise SystemExit(1)
