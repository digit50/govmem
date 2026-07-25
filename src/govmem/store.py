"""Governed memory store with scope filtering and supersession chains."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from threading import RLock
from typing import Any

from govmem.backend import InMemoryBackend, MemoryBackend
from govmem.exceptions import (
    AgentAlreadyRegisteredError,
    AgentNotRegisteredError,
    EntryNotFoundError,
    LockedEntryError,
    SupersedeOnlyError,
    UnauthorizedWriteError,
)
from govmem.models import Authority, Entry, EntryState, Mutability, Provenance, Scope


@dataclass
class AgentRegistration:
    write_kinds: frozenset[str] = field(default_factory=frozenset)
    scopes: frozenset[str] = field(default_factory=frozenset)


class GovernedMemoryStore:
    """In-process governed shared memory with enforced envelopes."""

    def __init__(self, backend: MemoryBackend | None = None) -> None:
        self._backend = backend or InMemoryBackend()
        self._agents: dict[str, AgentRegistration] = {}
        self._lock = RLock()

    def register_agent(
        self,
        agent_id: str,
        *,
        write_kinds: list[str] | None = None,
        scopes: list[str] | None = None,
    ) -> None:
        with self._lock:
            if agent_id in self._agents:
                raise AgentAlreadyRegisteredError(
                    f"Agent {agent_id!r} is already registered"
                )
            self._agents[agent_id] = AgentRegistration(
                write_kinds=frozenset(write_kinds or ()),
                scopes=frozenset(scopes or ()),
            )

    def write(
        self,
        *,
        agent_id: str,
        key: str,
        value: Any,
        scope: Scope,
        authority: Authority | str,
        provenance_source: str,
        mutability: Mutability | str = Mutability.REVISABLE,
        kind: str | None = None,
        source_turn: int | None = None,
    ) -> Entry:
        with self._lock:
            self._require_registered(agent_id)
            self._check_write_authority(agent_id, kind=kind, scope=scope)

            existing = self._active_entry_for_key(key, scope)
            if existing is not None:
                if existing.mutability == Mutability.LOCKED:
                    raise LockedEntryError(
                        f"Entry {existing.id!r} for key {key!r} is locked"
                    )
                if existing.mutability == Mutability.SUPERSEDE_ONLY:
                    raise SupersedeOnlyError(
                        f"Entry {existing.id!r} for key {key!r} is supersede-only; "
                        "use supersede() instead"
                    )
                return self._supersede_locked(
                    existing,
                    new_value=value,
                    agent_id=agent_id,
                    reason="revised via write",
                    evidence=provenance_source,
                    source_turn=source_turn,
                    authority=authority,
                    mutability=mutability,
                    scope=scope,
                )

            entry = Entry.create(
                key=key,
                value=value,
                scope=scope,
                authority=authority,
                mutability=mutability,
                provenance=Provenance.from_source(
                    agent_id=agent_id,
                    provenance_source=provenance_source,
                    source_turn=source_turn,
                ),
            )
            self._backend.save(entry)
            return entry

    def read(
        self,
        *,
        agent_id: str,
        scope: Scope,
        include_superseded: bool = False,
    ) -> list[Entry]:
        with self._lock:
            self._require_registered(agent_id)
            results: list[Entry] = []
            for entry in self._backend.list_all():
                if not include_superseded and entry.state != EntryState.ACTIVE:
                    continue
                if not entry.scope.matches(scope):
                    continue
                results.append(entry)
            results.sort(key=lambda entry: entry.provenance.written_at)
            return results

    def check_conflict(self, key: str, value: Any, *, agent_id: str) -> list[Entry]:
        with self._lock:
            self._require_registered(agent_id)
            conflicts: list[Entry] = []
            for entry in self._backend.get_by_key(key):
                if entry.state != EntryState.ACTIVE:
                    continue
                if entry.value != value:
                    conflicts.append(entry)
            return conflicts

    def supersede(
        self,
        *,
        entry_id: str,
        new_value: Any,
        agent_id: str,
        reason: str,
        evidence: str,
        source_turn: int | None = None,
        authority: Authority | str | None = None,
        mutability: Mutability | str | None = None,
    ) -> Entry:
        with self._lock:
            self._require_registered(agent_id)
            old = self._backend.get(entry_id)
            if old is None:
                raise EntryNotFoundError(f"Entry {entry_id!r} not found")
            if old.state != EntryState.ACTIVE:
                raise LockedEntryError(
                    f"Entry {entry_id!r} is not active (state={old.state.value})"
                )
            if old.mutability == Mutability.LOCKED:
                raise LockedEntryError(f"Entry {entry_id!r} is locked")

            self._check_write_authority(
                agent_id,
                kind=None,
                scope=old.scope,
                skip_kind_check=True,
            )

            return self._supersede_locked(
                old,
                new_value=new_value,
                agent_id=agent_id,
                reason=reason,
                evidence=evidence,
                source_turn=source_turn,
                authority=authority or old.authority,
                mutability=mutability or old.mutability,
                scope=old.scope,
            )

    def audit_log(self, key: str, *, agent_id: str) -> list[Entry]:
        with self._lock:
            self._require_registered(agent_id)
            entries = self._backend.get_by_key(key)
            if not entries:
                return []

            by_id = {entry.id: entry for entry in entries}
            referenced = {entry.superseded_by for entry in entries if entry.superseded_by}
            roots = [entry for entry in entries if entry.id not in referenced]

            chains: list[list[Entry]] = []
            for root in roots:
                chain: list[Entry] = []
                current: Entry | None = root
                while current is not None:
                    chain.append(current)
                    successor_id = current.superseded_by
                    current = by_id.get(successor_id) if successor_id else None
                chains.append(chain)

            merged: list[Entry] = []
            for chain in sorted(chains, key=lambda c: c[0].provenance.written_at):
                merged.extend(chain)
            return merged

    def _require_registered(self, agent_id: str) -> None:
        if agent_id not in self._agents:
            raise AgentNotRegisteredError(f"Agent {agent_id!r} is not registered")

    def _check_write_authority(
        self,
        agent_id: str,
        *,
        kind: str | None,
        scope: Scope,
        skip_kind_check: bool = False,
    ) -> None:
        registration = self._agents[agent_id]
        if registration.write_kinds and not skip_kind_check:
            if kind is None or kind not in registration.write_kinds:
                raise UnauthorizedWriteError(
                    f"Agent {agent_id!r} is not authorized to write kind {kind!r}"
                )
        if registration.scopes:
            namespace = scope.namespace
            if namespace is None or namespace not in registration.scopes:
                raise UnauthorizedWriteError(
                    f"Agent {agent_id!r} is not authorized for scope namespace {namespace!r}"
                )

    def _active_entry_for_key(self, key: str, scope: Scope) -> Entry | None:
        for entry in self._backend.get_by_key(key):
            if entry.state != EntryState.ACTIVE:
                continue
            if entry.scope.user == scope.user and entry.scope.task == scope.task:
                if entry.scope.session == scope.session:
                    if entry.scope.namespace == scope.namespace:
                        return entry
        return None

    def _supersede_locked(
        self,
        old: Entry,
        *,
        new_value: Any,
        agent_id: str,
        reason: str,
        evidence: str,
        source_turn: int | None,
        authority: Authority | str,
        mutability: Mutability | str,
        scope: Scope,
    ) -> Entry:
        new_entry = Entry.create(
            key=old.key,
            value=new_value,
            scope=scope,
            authority=authority,
            mutability=mutability,
            provenance=Provenance.from_source(
                agent_id=agent_id,
                provenance_source=f"{reason}: {evidence}",
                source_turn=source_turn,
            ),
        )
        old.state = EntryState.SUPERSEDED
        old.superseded_by = new_entry.id
        self._backend.save(old)
        self._backend.save(new_entry)
        return new_entry
