# Meeting Co-Pilot

Real-time AI question advisor for meetings.

Listens to meeting audio (microphone + system audio), transcribes it via Groq Whisper, and surfaces contextually relevant questions in a floating overlay using Groq Llama 4.

**100% free to run** — Groq API free tier covers all inference.

## Quick Start

```bash
# Install uv (one time)
powershell -c 'irm https://astral.sh/uv/install.ps1 | iex'

# Install dependencies
uv sync

# Get your free Groq API key at https://console.groq.com

# List audio devices
uv run python -m meeting_copilot --list-devices

# Launch the app
uv run python -m meeting_copilot
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| GUI | PySide6 (LGPL) |
| STT | Groq Whisper (whisper-large-v3-turbo) |
| LLM | Groq Llama 4 (llama-4-scout-17b-16e-instruct) |
| Audio | sounddevice + WASAPI loopback (Windows) |
| Architecture | Event-driven with typed EventBus |

## Running Tests

```bash
uv run pytest tests/unit/           # fast, no external deps
uv run pytest tests/integration/    # requires GROQ_API_KEY
uv run mypy src/                    # type check
uv run ruff check src/ tests/       # lint
```
