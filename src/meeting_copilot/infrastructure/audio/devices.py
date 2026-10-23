"""Audio device discovery — list inputs and recognize virtual system-audio devices.

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
        name = dev_dict.get("name", "").lower()

        # 1. Explicit WASAPI loopback (official)
        if sys.platform == "win32" and "wasapi" in host_api_name.lower():
            if "loopback" in name:
                is_loopback = True
        
        # 2. Heuristic loopback (Stereo Mix, What U Hear, etc.)
        if not is_loopback:
            keywords = [
                "stereo mix", "what u hear", "system mix", "wave out", "loopback",
                # macOS virtual audio drivers.  BlackHole is the recommended
                # option because it is free and exposes an input device.
                "blackhole", "loopback audio", "soundflower",
            ]
            if any(k in name for k in keywords):
                is_loopback = True
            
            # 3. Name-based match (e.g. "Speakers (Realtek HD Audio output)")
            # If it contains 'output' or 'speaker' but is an input device, it's suspicious.
            if any(k in name for k in ["output", "speaker", "headphone"]):
                if "microphone" not in name and "mic" not in name:
                    is_loopback = True

        if is_loopback:
             logger.debug("Identified candidate loopback: %s (ID: %d, API: %s)", dev_dict.get("name"), i, host_api_name)

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


def find_best_loopback() -> AudioDevice | None:
    """Find the best available system audio loopback device.
    
    Heuristic:
    1. Prefer 'WASAPI' + 'loopback' in name.
    2. Fallback to 'Stereo Mix', 'What U Hear', 'System Mix' on any API.
    3. Look for input devices whose names suggest they capture output (contains 'output' or 'speaker').
    
    Prioritizes devices that match the current default output's name.
    """
    if sys.platform == "darwin":
        candidates = [device for device in list_devices() if device["is_loopback"]]
        return candidates[0] if candidates else None
    if sys.platform != "win32":
        return None

    try:
        # Get name of current default output
        all_devs = list(sd.query_devices())
        def_out_idx = sd.default.device[1]
        def_out_name = all_devs[def_out_idx]["name"].lower()
    except (IndexError, TypeError, KeyError):
        def_out_name = ""

    devices = list_devices()
    
    # Sort candidates by preference
    candidates = []
    for d in devices:
        if not d["is_loopback"]:
            continue
            
        score = 0
        name_lower = d["name"].lower()
        api_lower = d["host_api"].lower()
        
        # Priority 1: WASAPI + Loopback
        if "wasapi" in api_lower and "loopback" in name_lower:
            score += 100
        
        # Priority 2: Matches default output name
        if def_out_name and (def_out_name in name_lower):
            score += 50
            
        # Priority 3: Stereo Mix / What U Hear
        if any(k in name_lower for k in ["stereo mix", "what u hear", "system mix"]):
            score += 30
            
        # Priority 4: WASAPI is generally better than MME/DS
        if "wasapi" in api_lower:
            score += 10
            
        candidates.append((score, d))
        
    if not candidates:
        logger.warning("No loopback candidates found via heuristics.")
        return None
        
    # Pick highest score
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]
    logger.info("Best loopback candidate: %s (ID: %d, API: %s, Score: %d)", 
                best["name"], best["id"], best["host_api"], candidates[0][0])
    return best
