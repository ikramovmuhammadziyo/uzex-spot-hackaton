"""Bounded immutable tool-result cache. Model answers are never cached."""
from __future__ import annotations

from collections import OrderedDict


class ToolCache:
    def __init__(self, max_entries: int = 256, max_bytes: int = 8 * 1024 * 1024):
        self.max_entries = max(0, max_entries)
        self.max_bytes = max(0, max_bytes)
        self._items: OrderedDict[str, tuple[str, int]] = OrderedDict()
        self.bytes = 0
        self.generation: str | None = None

    def select_generation(self, generation: str) -> None:
        if generation != self.generation:
            self._items.clear()
            self.bytes = 0
            self.generation = generation

    def get(self, key: str) -> str | None:
        item = self._items.get(key)
        if item is None:
            return None
        self._items.move_to_end(key)
        return item[0]

    def put(self, key: str, value: str) -> None:
        size = len(key.encode()) + len(value.encode())
        if not self.max_entries or size > self.max_bytes:
            return
        old = self._items.pop(key, None)
        if old:
            self.bytes -= old[1]
        self._items[key] = (value, size)
        self.bytes += size
        while len(self._items) > self.max_entries or self.bytes > self.max_bytes:
            _, (_, removed) = self._items.popitem(last=False)
            self.bytes -= removed
