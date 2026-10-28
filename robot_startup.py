"""Startup checks and a managed Cozmo subprocess for the Misty controller."""

import asyncio
from contextlib import suppress
import json
import random
from pathlib import Path
import subprocess
import sys

import aiohttp



async def open_misty_camera(session, ip, ready_timeout=10, port=5678):
    """Misty can acknowledge start before its WebSocket listener is ready."""
    deadline = asyncio.get_running_loop().time()+ready_timeout
    while True:
        remaining = deadline-asyncio.get_running_loop().time()
        if remaining <= 0:
            raise RuntimeError('Misty camera did not open port {} within {} seconds'.format(port, ready_timeout))
        try:
            return await asyncio.wait_for(session.ws_connect(
                'ws://'+ip+':'+str(port), receive_timeout=8, max_msg_size=16*1024*1024),
                timeout=min(3, remaining))
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
            await asyncio.sleep(min(0.3, max(0, deadline-asyncio.get_running_loop().time())))


async def ensure_misty_camera(session, ip, unwrap):
    """Reuse a working stream or recover with up to two fresh-port restarts."""
    async def fresh_socket(timeout, port):
        socket = await open_misty_camera(session, ip, ready_timeout=timeout, port=port)
        try:
            message = await socket.receive(timeout=5)
            if message.type not in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                raise RuntimeError('Misty camera returned no image')
            return socket, message.data, port
        except BaseException:
            await socket.close()
            raise

    try:
        return await fresh_socket(1, 5678)
    except (RuntimeError, aiohttp.ClientError, asyncio.TimeoutError):
        print('Restarting Misty video service...', flush=True)
    # Misty's video server can fail to rebind its previous port after stop.
    # New ports avoid that failure without rebooting the robot.
    last_error = None
    ports = random.SystemRandom().sample(range(10000, 60001), 2)
    for port in ports:
        print('Starting Misty video on fresh port {}...'.format(port), flush=True)
        for action, payload in [('stop', {}), ('start', {
                'Port': port, 'Rotation': 0, 'Width': 640, 'Height': 480,
                'Quality': 90, 'Overlay': False})]:
            async with session.post('http://'+ip+'/api/videostreaming/'+action, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=20)) as response:
                response.raise_for_status()
                unwrap(await response.json(content_type=None))
            await asyncio.sleep(5 if action == 'stop' else 2)
        try:
            return await fresh_socket(10, port)
        except (RuntimeError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_error = exc
            print('Camera attempt failed: ' + str(exc), flush=True)
    raise RuntimeError('Misty camera failed after two fresh-port restarts: ' + str(last_error))


class CozmoProcess:
    def __init__(self):
        self.process = None
        self.tasks = []
        self.ready = asyncio.Event()
        self.events = asyncio.Queue()
        self.error = None
        self.closing = False

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, '-u', str(Path(__file__).with_name('cozmo_waypoint_worker.py')),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.tasks = [asyncio.create_task(self.read()), asyncio.create_task(self.heartbeat())]
        await asyncio.wait_for(self.ready.wait(), timeout=25)
        if self.error:
            raise RuntimeError('Cozmo: ' + self.error)

    async def send(self, command):
        if self.process is None or self.process.returncode is not None:
            raise RuntimeError('Cozmo connection is closed')
        self.process.stdin.write((json.dumps({'command': command})+'\n').encode())
        await self.process.stdin.drain()

    async def heartbeat(self):
        try:
            while True:
                await self.send('ping')
                await asyncio.sleep(0.5)
        except (RuntimeError, ConnectionError, OSError):
            pass

    async def read(self):
        while True:
            line = await self.process.stdout.readline()
            if not line:
                break
            text = line.decode(errors='replace').strip()
            if text.startswith('COZMO_EVENT '):
                event = json.loads(text[len('COZMO_EVENT '):])
                if event['event'] == 'error':
                    self.error = event['message']
                    self.ready.set()
                if event['event'] == 'ready':
                    self.ready.set()
                await self.events.put(event)
            else:
                print('[Cozmo] ' + text, flush=True)
                if text.startswith('Stopped:'):
                    await self.events.put({'event': 'stopped', 'message': text})
        if not self.closing:
            self.error = self.error or 'SDK disconnected. Check USB, Cozmo app SDK mode, and other Cozmo controllers.'
            self.ready.set()
            await self.events.put({'event': 'error', 'message': self.error})

    async def close(self):
        self.closing = True
        if self.process is not None:
            with suppress(Exception):
                await self.send('quit')
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.terminate()
                await self.process.wait()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


async def preflight(ip, decode_frame, unwrap):
    """Do not open driving controls until all checks pass. No movement commands."""
    cozmo = CozmoProcess()
    stream_started = False
    succeeded = False
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8), trust_env=False)
    async def request(method, path, payload=None):
        async with session.request(method, 'http://'+ip+'/api/'+path, json=payload,
                                   timeout=aiohttp.ClientTimeout(total=20)) as response:
            response.raise_for_status()
            return unwrap(await response.json(content_type=None))
    async def check_misty():
        nonlocal stream_started
        print('Checking Misty...', flush=True)
        await request('GET', 'device')
        stream_started = True
        socket, data, port = await ensure_misty_camera(session, ip, unwrap)
        cozmo.misty_port = port
        cozmo.misty_socket = socket
        cozmo.misty_session = session
        decode_frame(data)
        print('Misty + camera OK.', flush=True)

    try:
        print('Checking Cozmo SDK, camera, and initial tag 5 position...', flush=True)
        results = await asyncio.gather(check_misty(), cozmo.start(), return_exceptions=True)
        failures = ['{}: {}'.format(name, str(result) or type(result).__name__)
                    for name, result in zip(('Misty', 'Cozmo'), results)
                    if isinstance(result, BaseException)]
        if failures:
            raise RuntimeError(' | '.join(failures))
        print('All startup checks passed.', flush=True)
        succeeded = True
        cozmo.misty_stream_ready = True
        return cozmo
    except BaseException:
        await cozmo.close()
        raise
    finally:
        if stream_started and not succeeded:
            with suppress(Exception):
                await request('POST', 'videostreaming/stop', {})

        if not succeeded:
            if getattr(cozmo, 'misty_socket', None) is not None:
                await cozmo.misty_socket.close()
            await session.close()
