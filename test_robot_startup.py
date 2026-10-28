import asyncio
from types import SimpleNamespace
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from robot_startup import CozmoProcess, open_misty_camera, ensure_misty_camera
import aiohttp
from wasd_misty import MistyController, launch


def sample():
    return {'frame_age_seconds': 0.01, 'frame_number': 1,
            'markers': [{'id': 5, 'center_pixels': [400, 300]},
                        {'id': 8, 'center_pixels': [1100, 650]}]}


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_r_reverses_once_per_press_only_while_enabled(self):
        controller = self.controller()
        controller.keys = set()
        controller.cozmo_enabled.get.return_value = True
        event = SimpleNamespace(keysym='r')
        controller.press(event)
        controller.press(event)
        await asyncio.gather(*controller.cozmo_tasks)
        controller.cozmo.send.assert_awaited_once_with('reverse')
        controller.keys.discard('r')
        controller.cozmo_enabled.get.return_value = False
        controller.press(event)
        self.assertEqual(controller.cozmo.send.await_count, 1)

    async def test_reuses_working_video_without_restart(self):
        socket = SimpleNamespace(receive=AsyncMock(return_value=SimpleNamespace(
            type=aiohttp.WSMsgType.BINARY, data=b'image')), close=AsyncMock())
        session = Mock()
        with patch('robot_startup.open_misty_camera', AsyncMock(return_value=socket)):
            self.assertEqual(await ensure_misty_camera(session, 'unused', Mock()), (socket, b'image', 5678))
        session.post.assert_not_called()

    async def test_stuck_video_gets_stop_wait_start(self):
        socket = SimpleNamespace(receive=AsyncMock(return_value=SimpleNamespace(
            type=aiohttp.WSMsgType.BINARY, data=b'image')), close=AsyncMock())
        response = SimpleNamespace(raise_for_status=Mock(), json=AsyncMock(return_value={}))
        context = AsyncMock()
        context.__aenter__.return_value = response
        session = SimpleNamespace(post=Mock(return_value=context))
        with patch('robot_startup.open_misty_camera', AsyncMock(side_effect=[RuntimeError('closed'), socket])), \
             patch('robot_startup.asyncio.sleep', AsyncMock()) as sleep:
            await ensure_misty_camera(session, 'unused', Mock())
        self.assertEqual([call.args[0].rsplit('/', 1)[1] for call in session.post.call_args_list], ['stop', 'start'])
        self.assertNotEqual(session.post.call_args_list[1].kwargs['json']['Port'], 5678)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [5, 2])

    async def test_controller_does_not_restart_verified_stream(self):
        controller = MistyController.__new__(MistyController)
        controller.ip = 'unused'
        controller.stream_started = True
        controller.request = AsyncMock(return_value={'serialNumber': 'test'})
        controller.send_drive = AsyncMock()
        controller.connection = Mock()
        controller.record_button = Mock()
        await controller.connect()
        controller.request.assert_awaited_once_with('GET', 'device')

    async def test_camera_loop_keeps_preflight_socket(self):
        import io
        from PIL import Image
        data = io.BytesIO()
        Image.new('RGB', (4, 3)).save(data, format='PNG')
        controller = MistyController.__new__(MistyController)
        controller.running = True
        controller.connected = True
        controller.frame_number = 0
        controller.recorder = None
        controller.label = Mock(return_value={})
        controller.fail = Mock()

        class Socket:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def __aiter__(self): return self.messages()
            async def messages(self):
                yield SimpleNamespace(type=aiohttp.WSMsgType.BINARY, data=data.getvalue())
                controller.running = False

        controller.cozmo = SimpleNamespace(misty_socket=Socket())
        with patch('wasd_misty.open_misty_camera', AsyncMock()) as reconnect:
            await controller.camera_loop()
        reconnect.assert_not_awaited()
        controller.fail.assert_not_called()
        self.assertEqual(controller.frame.size, (3, 4))

    async def test_camera_waits_for_listener_to_start(self):
        socket = Mock()
        session = SimpleNamespace(ws_connect=AsyncMock(side_effect=[
            aiohttp.ClientConnectionError('not ready'), socket]))
        self.assertIs(await open_misty_camera(session, 'unused'), socket)
        self.assertEqual(session.ws_connect.await_count, 2)

    async def test_camera_wait_has_a_deadline(self):
        session = SimpleNamespace(ws_connect=AsyncMock(side_effect=aiohttp.ClientConnectionError('offline')))
        with self.assertRaisesRegex(RuntimeError, 'did not open'):
            await open_misty_camera(session, 'unused', ready_timeout=0.01)

    def controller(self):
        controller = MistyController.__new__(MistyController)
        controller.cozmo = SimpleNamespace(send=AsyncMock(), events=asyncio.Queue(), error=None)
        controller.cozmo_pending = False
        controller.cozmo_enabled = Mock()
        controller.cozmo_status = Mock()
        controller.cozmo_toggle = Mock()
        controller.cozmo_tasks = []
        controller.connected = True
        controller.last_frame_at = time.monotonic()
        controller.misty_tag = 8
        controller.tracking = Mock()
        controller.tracking.snapshot.return_value = (sample(), 0)
        return controller

    async def test_toggle_starts_and_off_stops_even_with_bad_tracking(self):
        controller = self.controller()
        await controller.set_cozmo(True)
        controller.cozmo.send.assert_awaited_once_with('start')
        controller.tracking.snapshot.return_value = ({'error': 'offline'}, 0)
        controller.connected = False
        await controller.set_cozmo(False)
        self.assertEqual(controller.cozmo.send.await_args.args, ('stop',))

    async def test_start_does_not_need_tracking(self):
        controller = self.controller()
        controller.tracking.snapshot.return_value = ({'error': 'offline'}, 0)
        await controller.set_cozmo(True)
        controller.cozmo.send.assert_awaited_once_with('start')
        controller.tracking.snapshot.assert_not_called()

    async def test_cozmo_does_not_depend_on_misty_camera(self):
        controller = self.controller()
        controller.last_frame_at = 0
        controller.connected = False
        controller.tracking.snapshot.return_value = (
            dict(sample(), markers=[sample()['markers'][0]]), 0)
        await controller.set_cozmo(True)
        controller.cozmo.send.assert_awaited_once_with('start')

    async def test_off_stays_clickable_while_start_pending(self):
        controller = self.controller()
        controller.cozmo_pending = True
        controller.cozmo_enabled.get.return_value = True
        controller.last_frame_at = 0
        controller.update_cozmo()
        controller.cozmo_toggle.configure.assert_called_with(text='Cozmo ON', state='normal')

    async def test_worker_stopping_updates_toggle(self):
        controller = self.controller()
        controller.cozmo_enabled.get.return_value = False
        await controller.cozmo.events.put({'event': 'stopped'})
        controller.update_cozmo()
        controller.cozmo_enabled.set.assert_called_with(False)

    async def test_startup_failure_does_not_open_window(self):
        args = SimpleNamespace(ip='unused', tracking_url='unused', marker_id=8)
        with patch('wasd_misty.preflight', AsyncMock(side_effect=RuntimeError('offline'))), \
             patch('wasd_misty.MistyController') as ui:
            with self.assertRaises(RuntimeError):
                await launch(args)
            ui.assert_not_called()

    async def test_window_failure_closes_worker(self):
        args = SimpleNamespace(ip='unused', tracking_url='unused', marker_id=8)
        worker = SimpleNamespace(close=AsyncMock())
        with patch('wasd_misty.preflight', AsyncMock(return_value=worker)), \
             patch('wasd_misty.MistyController', side_effect=RuntimeError('window failed')):
            with self.assertRaises(RuntimeError):
                await launch(args)
        worker.close.assert_awaited_once()

    async def test_check_only_closes_worker_without_opening_window(self):
        args = SimpleNamespace(ip='unused', tracking_url='unused', marker_id=8, check_only=True)
        worker = SimpleNamespace(close=AsyncMock())
        with patch('wasd_misty.preflight', AsyncMock(return_value=worker)), \
             patch('wasd_misty.MistyController') as ui:
            await launch(args)
        ui.assert_not_called()
        worker.close.assert_awaited_once()

    async def test_worker_exit_reports_failure_not_ready_success(self):
        worker = CozmoProcess()
        reader = asyncio.StreamReader()
        reader.feed_eof()
        worker.process = SimpleNamespace(stdout=reader)
        await worker.read()
        self.assertTrue(worker.ready.is_set())
        self.assertIn('SDK disconnected', worker.error)
        self.assertEqual((await worker.events.get())['event'], 'error')

    async def test_shutdown_requests_graceful_quit(self):
        worker = CozmoProcess()
        worker.process = SimpleNamespace(wait=AsyncMock())
        worker.send = AsyncMock()
        await worker.close()
        worker.send.assert_awaited_once_with('quit')


if __name__ == '__main__':
    unittest.main()
