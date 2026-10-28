import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from wasd_misty_only import MistyOnlyController, launch


class MistyOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_launch_does_not_start_combined_preflight(self):
        with patch('wasd_misty_only.MistyOnlyController') as controller, \
             patch('wasd_misty.preflight', AsyncMock()) as preflight:
            controller.return_value.run = AsyncMock()
            await launch(SimpleNamespace(ip='192.168.1.38'))
            controller.assert_called_once_with('192.168.1.38')
            controller.return_value.run.assert_awaited_once()
            preflight.assert_not_awaited()

    async def test_connect_reuses_verified_camera(self):
        controller = MistyOnlyController.__new__(MistyOnlyController)
        controller.ip = 'unused'
        controller.session = Mock()
        controller.request = AsyncMock(return_value={'serialNumber': 'test'})
        controller.send_drive = AsyncMock()
        controller.connection = Mock()
        controller.record_button = Mock()
        socket = AsyncMock()
        with patch('wasd_misty_only.ensure_misty_camera', AsyncMock(
                return_value=(socket, b'image', 12345))), \
             patch('wasd_misty_only.decode_frame'):
            await controller.connect()
        self.assertIs(controller.misty_socket, socket)
        self.assertEqual(controller.misty_port, 12345)
        self.assertTrue(controller.connected)
        self.assertTrue(controller.stream_started)
        self.assertTrue(all(call.args == ('GET', 'device')
                            for call in controller.request.await_args_list))
