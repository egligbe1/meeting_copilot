"""Thread-safe, in-process, synchronous pub/sub EventBus.

The bus is a module-level singleton accessed via ``get_bus()``.
Two subscription modes:
    * ``subscribe()`` — callback invoked synchronously on the emitting thread.
    * ``subscribe_qt()`` — wraps the slot so it always executes on the Qt
      main thread (via ``QMetaObject.invokeMethod`` with QueuedConnection).
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class EventBus:
    """Centralised, thread-safe event bus."""

    def __init__(self) -> None:
        self._subs: dict[type, list[Callable[..., Any]]] = defaultdict(list)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(
        self, event_type: type[T], callback: Callable[[T], None]
    ) -> None:
        """Subscribe *callback* to *event_type*.

        The callback is invoked **synchronously** on whatever thread calls
        ``emit()``.  Use :meth:`subscribe_qt` for UI callbacks.
        """
        with self._lock:
            self._subs[event_type].append(callback)

    def subscribe_qt(
        self, event_type: type[T], slot: Callable[[T], None]
    ) -> None:
        """Subscribe a Qt slot ensuring it runs on the **main thread**.

        Uses QMetaObject.invokeMethod with QueuedConnection to marshal the
        event invocation onto the Qt event loop of the thread that owns
        the bridge object (the main thread).
        """
        from PySide6.QtCore import (  # noqa: PLC0415
            QMetaObject,
            QObject,
            Qt,
            Slot,
        )

        class QtBridge(QObject):
            @Slot(object)
            def handle(self, event: Any) -> None:
                slot(event)

        # Create bridge on the current thread (Main Thread)
        bridge = QtBridge()

        # Store bridge reference to prevent GC
        with self._lock:
            if not hasattr(self, "_qt_bridges"):
                self._qt_bridges: list[QtBridge] = []
            self._qt_bridges.append(bridge)

        def _invoke(event: T) -> None:
            # Marshal to the bridge's thread (Main Thread)
            QMetaObject.invokeMethod(
                bridge,
                "handle",
                Qt.ConnectionType.QueuedConnection,
                event,
            )

        self.subscribe(event_type, _invoke)

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------

    def emit(self, event: object) -> None:
        """Emit *event* to all subscribers of its type.

        Individual subscriber exceptions are caught, logged, and swallowed
        so that one failing handler cannot break other handlers.
        """
        with self._lock:
            callbacks = list(self._subs.get(type(event), []))

        for cb in callbacks:
            try:
                cb(event)
            except Exception:
                logger.exception(
                    "EventBus handler error for %s", type(event).__name__
                )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all subscriptions. Intended for testing only."""
        with self._lock:
            self._subs.clear()


# Module-level singleton
_bus = EventBus()


def get_bus() -> EventBus:
    """Return the global EventBus singleton."""
    return _bus
