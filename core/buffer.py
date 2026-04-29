"""Thread-safe circular buffer wrapping collections.deque.

Provides atomic push, drain, and peek operations for safe cross-thread
data transfer between the watcher and analysis threads.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Generic, TypeVar

T = TypeVar("T")


class ThreadSafeBuffer(Generic[T]):
    """A thread-safe circular buffer backed by collections.deque.

    All mutating operations acquire an internal lock to guarantee
    consistency when accessed from multiple threads.
    """

    def __init__(self, maxlen: int = 10_000) -> None:
        """Initialise the buffer with an optional maximum length.

        Args:
            maxlen: Maximum number of items retained. Oldest items are
                    silently evicted once the limit is reached.
        """
        self._deque: deque[T] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def push(self, item: T) -> None:
        """Append *item* to the right side of the buffer atomically."""
        with self._lock:
            self._deque.append(item)

    def drain(self) -> list[T]:
        """Empty the buffer and return all items as a list atomically.

        The buffer is cleared atomically so no item is returned twice.
        """
        with self._lock:
            items = list(self._deque)
            self._deque.clear()
            return items

    def peek_last(self, n: int) -> list[T]:
        """Return up to the last *n* items without removing them.

        Args:
            n: Number of items to peek from the right (newest) end.

        Returns:
            A list of at most *n* items, ordered oldest-first.
        """
        with self._lock:
            return list(self._deque)[-n:]

    def __len__(self) -> int:
        """Return the current number of items in the buffer."""
        with self._lock:
            return len(self._deque)
