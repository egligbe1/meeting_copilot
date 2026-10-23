# Interview Co-Pilot

Real-time, concise answer guidance for data engineering, data architecture,
and behavioral interviews.

Listens to interview audio (microphone + system audio), transcribes it via Groq
Whisper, and surfaces a brief, speakable answer plus key talking points in a
floating overlay using Groq GPT-OSS.

The coach does not invent experience, credentials, employers, or metrics. Add
your truthful résumé highlights and project context in Settings so it can keep
the guidance grounded in your own background. Follow the interviewer's rules
on AI assistance and recording.

**100% free to run** — Groq API free tier covers all inference.

## Quick Start

```bash
# Install uv (one time; macOS)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Get your free Groq API key at https://console.groq.com

# List audio devices (BlackHole should appear after installing it)
uv run python -m meeting_copilot --list-devices

# Launch the app
uv run interview-copilot
```

## macOS audio setup

macOS does not expose system audio as a normal recording device. For the
interviewer side of a call, install [BlackHole](https://existential.audio/blackhole/),
then use **Audio MIDI Setup** to create a Multi-Output Device containing your
headphones/speakers and BlackHole. Set that Multi-Output Device as the meeting
app's output, and select BlackHole in Interview Co-Pilot's **System Audio**
settings. Only this system-audio input is transcribed; your microphone is not
captured or mixed into transcription. A loopback device is required.

macOS will prompt for microphone access the first time the app records.
Audio is submitted for transcription after about 0.8 seconds of silence, and
answer generation starts when each meeting speech segment is transcribed.
Actual response time depends on network and Groq service latency.
Use **Clear** in the overlay before a new question to discard the current
transcript context and answer; saved session history is kept.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| GUI | PySide6 (LGPL) |
| STT | Groq Whisper (whisper-large-v3-turbo) |
| LLM | Groq GPT-OSS 20B (openai/gpt-oss-20b) |
| Audio | sounddevice + WASAPI loopback (Windows) |
| Architecture | Event-driven with typed EventBus |

## Running Tests

```bash
uv run pytest tests/unit/           # fast, no external deps
uv run pytest tests/integration/    # requires GROQ_API_KEY
uv run mypy src/                    # type check
uv run ruff check src/ tests/       # lint
```
