"""Data models and enums for governed memory entries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class Authority(str, Enum):
    USER_STATED = "user_stated"
    AGENT_INFERRED = "agent_inferred"
    SYSTEM = "system"
    POLICY = "policy"


class Mutability(str, Enum):
    REVISABLE = "revisable"
    SUPERSEDE_ONLY = "supersede_only"
    LOCKED = "locked"
    DECAYING = "decaying"


class EntryState(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class Scope:
    """Who/what an entry may be used for."""

    user: str | None = None
    task: str | None = None
    session: str | None = None
    namespace: str | None = None

    def matches(self, query: Scope) -> bool:
        """Return True when every non-None query field equals this scope."""
        for field_name in ("user", "task", "session", "namespace"):
            query_value = getattr(query, field_name)
            if query_value is None:
                continue
            if getattr(self, field_name) != query_value:
                return False
        return True


@dataclass(frozen=True)
class Provenance:
    """Origin metadata for a memory entry."""

    agent_id: str
    source_turn: int | None
    evidence_spans: tuple[str, ...]
    written_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_source(
        cls,
        *,
        agent_id: str,
        provenance_source: str,
        source_turn: int | None = None,
    ) -> Provenance:
        return cls(
            agent_id=agent_id,
            source_turn=source_turn,
            evidence_spans=(provenance_source,),
        )


@dataclass(frozen=True)
class Entry:
    """A governed memory entry with full envelope metadata."""

    id: str
    key: str
    value: Any
    scope: Scope
    authority: Authority
    mutability: Mutability
    provenance: Provenance
    kind: str | None = None
    superseded_by: str | None = None
    state: EntryState = EntryState.ACTIVE

    @classmethod
    def create(
        cls,
        *,
        key: str,
        value: Any,
        scope: Scope,
        authority: Authority | str,
        mutability: Mutability | str,
        provenance: Provenance,
        kind: str | None = None,
    ) -> Entry:
        return cls(
            id=str(uuid4()),
            key=key,
            value=value,
            scope=scope,
            authority=Authority(authority),
            mutability=Mutability(mutability),
            provenance=provenance,
            kind=kind,
        )
