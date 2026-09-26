"""ADR-0046 §1: `POST /video/live` refuses a camera the terminal reports as having no video signal
(no camera connected), before any relay or device command - the backend guard behind the web
wall hiding such a camera, so hiding a tile is never the only protection."""

from __future__ import annotations

import unittest

import raad.core.di  # noqa: F401 - import order: the container before the routers
from raad.core.errors.exceptions import CameraNotConnectedError
from raad.core.errors.handlers import resolve_status
from raad.modules.fleet_device.application.queries import CameraDTO
from raad.modules.video.api.routers import ensure_camera_connected


def _camera(signal: str) -> CameraDTO:
    return CameraDTO(id="cam-2", channel_no=2, position="other", label="Channel 2", video_signal=signal)


class CameraConnectedGateTests(unittest.TestCase):
    def test_an_absent_camera_is_refused_with_409(self) -> None:
        with self.assertRaises(CameraNotConnectedError) as raised:
            ensure_camera_connected(_camera("absent"))
        self.assertEqual(raised.exception.code, "CAMERA_NOT_CONNECTED")
        self.assertEqual(resolve_status(raised.exception), 409)

    def test_a_present_camera_passes(self) -> None:
        ensure_camera_connected(_camera("present"))

    def test_an_unreported_camera_passes_as_before(self) -> None:
        ensure_camera_connected(_camera("unknown"))
