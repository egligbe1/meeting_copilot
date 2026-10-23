"""Entry point — ``python -m meeting_copilot``.

During Phase 2–3 this runs in terminal mode (QCoreApplication, prints to stdout).
Phase 4+ switches to full QApplication with GUI overlay.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from meeting_copilot.application.orchestrator import Orchestrator
from meeting_copilot.infrastructure.persistence.config import ConfigStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    """Application entry point."""
    parser = argparse.ArgumentParser(
        description="Interview Co-Pilot — Real-time answer guidance"
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available audio input devices and exit",
    )
    args = parser.parse_args()

    # --list-devices: no Qt, just print and exit
    if args.list_devices:
        from meeting_copilot.infrastructure.audio.devices import list_devices

        devices = list_devices()
        if not devices:
            print("No audio input devices found.")
        else:
            print(f"{'ID':<5} {'Name':<50} {'Loopback':<10} {'Host API'}")
            print("-" * 80)
            for d in devices:
                print(
                    f"{d['id']:<5} {d['name']:<50} "
                    f"{'Yes' if d['is_loopback'] else 'No':<10} "
                    f"{d['host_api']}"
                )
        return

    # Load settings
    config_store = ConfigStore()
    settings = config_store.load()
    api_key = config_store.get_api_key()

    # Create Qt application
    from meeting_copilot.ui.app import build_qapplication
    app = build_qapplication(settings)

    # UI setup
    from meeting_copilot.ui.overlay import FloatingOverlay
    from meeting_copilot.ui.tray import SystemTrayManager
    
    overlay = FloatingOverlay(settings)
    
    # Onboarding if needed
    if not api_key:
        from meeting_copilot.ui.onboarding import OnboardingWizard
        wizard = OnboardingWizard(settings)
        if not wizard.exec():
            sys.exit(0)
        # Reload after onboarding
        settings = config_store.load()
        api_key = config_store.get_api_key()

    orchestrator = Orchestrator(settings, api_key=api_key or "", parent=overlay)
    tray = SystemTrayManager(overlay, orchestrator, parent=overlay)
    
    # Connect tray to error events
    from meeting_copilot.application.event_bus import get_bus
    from meeting_copilot.domain.events import ErrorOccurred
    get_bus().subscribe_qt(ErrorOccurred, tray._on_error)

    # Graceful shutdown on Ctrl+C
    def handle_sigint(*_args: object) -> None:
        print("\nStopping...")
        orchestrator.shutdown()
        app.quit()

    signal.signal(signal.SIGINT, handle_sigint)
    app.aboutToQuit.connect(orchestrator.shutdown)

    # Start listening
    print("Interview Co-Pilot is listening... (Ctrl+C to stop)")
    orchestrator.start()
    
    overlay.show()
    tray.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
