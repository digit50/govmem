"""Pluggable storage backends for governed memory."""

from __future__ import annotations

from typing import Protocol

from govmem.models import Entry


class MemoryBackend(Protocol):
    """Storage interface for governed memory entries."""

    def save(self, entry: Entry) -> None:
        """Persist a new or updated entry."""

    def get(self, entry_id: str) -> Entry | None:
        """Fetch a single entry by id."""

    def get_by_key(self, key: str) -> list[Entry]:
        """Return all entries for a key, any state."""

    def list_all(self) -> list[Entry]:
        """Return every stored entry."""


class InMemoryBackend:
    """Thread-unsafe in-memory backend; store provides locking."""

    def __init__(self) -> None:
        self._entries: dict[str, Entry] = {}
        self._by_key: dict[str, list[str]] = {}

    def save(self, entry: Entry) -> None:
        self._entries[entry.id] = entry
        ids = self._by_key.setdefault(entry.key, [])
        if entry.id not in ids:
            ids.append(entry.id)

    def get(self, entry_id: str) -> Entry | None:
        return self._entries.get(entry_id)

    def get_by_key(self, key: str) -> list[Entry]:
        return [self._entries[entry_id] for entry_id in self._by_key.get(key, ())]

    def list_all(self) -> list[Entry]:
        return list(self._entries.values())
