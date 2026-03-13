"""Audio device discovery — list input devices and find WASAPI loopback.

Cross-platform: on Windows, detects WASAPI loopback devices automatically.
On macOS / Linux, simply lists available input devices.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, TypedDict

import sounddevice as sd

logger = logging.getLogger(__name__)


class AudioDevice(TypedDict):
    """Describes a single audio input device."""

    id: int
    name: str
    is_input: bool
    is_loopback: bool
    max_input_channels: int
    host_api: str


def list_devices() -> list[AudioDevice]:
    """Return a list of audio input devices available on this system."""
    devices: list[AudioDevice] = []
    host_apis = sd.query_hostapis()

    for i, dev in enumerate(sd.query_devices()):
        dev_dict: dict[str, Any] = dict(dev)  # type: ignore[arg-type]
        max_in: int = dev_dict.get("max_input_channels", 0)
        if max_in <= 0:
            continue  # skip output-only devices

        host_api_index: int = dev_dict.get("hostapi", 0)
        host_api_name: str = host_apis[host_api_index]["name"]  # type: ignore[index]

        is_loopback = False
        if sys.platform == "win32":
            # WASAPI loopback devices have 'WASAPI' in host API name
            # and often contain 'Loopback' in device name
            if "wasapi" in host_api_name.lower():
                is_loopback = True

        devices.append(
            AudioDevice(
                id=i,
                name=dev_dict.get("name", f"Device {i}"),
                is_input=True,
                is_loopback=is_loopback,
                max_input_channels=max_in,
                host_api=host_api_name,
            )
        )

    return devices


def find_wasapi_loopback() -> AudioDevice | None:
    """Find the first WASAPI loopback input device (Windows only).

    Returns None on non-Windows platforms or if no loopback device is found.
    """
    if sys.platform != "win32":
        return None

    for device in list_devices():
        if device["is_loopback"]:
            return device

    return None
