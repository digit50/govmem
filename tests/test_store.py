"""Comprehensive tests for GovernedMemoryStore."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from govmem import (
    AgentAlreadyRegisteredError,
    AgentNotRegisteredError,
    GovernedMemoryStore,
    LockedEntryError,
    Scope,
    SupersedeOnlyError,
    UnauthorizedWriteError,
)
from govmem.exceptions import EntryNotFoundError


class TestBasicWriteRead:
    def test_write_returns_entry_with_envelope(self, registered_store: GovernedMemoryStore) -> None:
        entry = registered_store.write(
            agent_id="researcher",
            key="user_location",
            value="Berlin",
            scope=Scope(user="user_123", task="travel", namespace="research"),
            authority="user_stated",
            provenance_source="turn 5: 'I live in Berlin'",
            mutability="revisable",
            kind="fact",
        )
        assert entry.key == "user_location"
        assert entry.value == "Berlin"
        assert entry.authority.value == "user_stated"
        assert entry.mutability.value == "revisable"
        assert entry.state.value == "active"
        assert entry.provenance.agent_id == "researcher"
        assert "Berlin" in entry.provenance.evidence_spans[0]

    def test_read_returns_matching_active_entries(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        registered_store.write(
            agent_id="researcher",
            key="user_location",
            value="Berlin",
            scope=Scope(user="user_123", task="travel", namespace="research"),
            authority="user_stated",
            provenance_source="turn 5",
            kind="fact",
        )
        entries = registered_store.read(
            agent_id="planner",
            scope=Scope(user="user_123", task="travel"),
        )
        assert len(entries) == 1
        assert entries[0].value == "Berlin"

    def test_unregistered_agent_cannot_read(self, store: GovernedMemoryStore) -> None:
        with pytest.raises(AgentNotRegisteredError):
            store.read(agent_id="unknown", scope=Scope(user="u"))


class TestScopeFiltering:
    def test_read_filters_by_user(self, registered_store: GovernedMemoryStore) -> None:
        scope_a = Scope(user="user_a", task="travel", namespace="research")
        scope_b = Scope(user="user_b", task="travel", namespace="research")
        registered_store.write(
            agent_id="researcher",
            key="secret",
            value="alpha",
            scope=scope_a,
            authority="user_stated",
            provenance_source="turn 1",
            kind="fact",
        )
        assert len(registered_store.read(agent_id="planner", scope=scope_a)) == 1
        assert registered_store.read(agent_id="planner", scope=scope_b) == []

    def test_read_filters_by_task(self, registered_store: GovernedMemoryStore) -> None:
        user_scope = Scope(user="user_123", namespace="research")
        registered_store.write(
            agent_id="researcher",
            key="plan_step",
            value="book flight",
            scope=Scope(user="user_123", task="travel", namespace="research"),
            authority="agent_inferred",
            provenance_source="turn 2",
            kind="fact",
        )
        assert len(
            registered_store.read(
                agent_id="planner",
                scope=Scope(user="user_123", task="travel"),
            )
        ) == 1
        assert registered_store.read(
            agent_id="planner",
            scope=Scope(user="user_123", task="shopping"),
        ) == []

    def test_session_must_match_when_specified(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        registered_store.write(
            agent_id="researcher",
            key="note",
            value="private",
            scope=Scope(
                user="user_123",
                task="travel",
                session="sess_a",
                namespace="research",
            ),
            authority="user_stated",
            provenance_source="turn 3",
            kind="fact",
        )
        assert len(
            registered_store.read(
                agent_id="planner",
                scope=Scope(user="user_123", task="travel", session="sess_a"),
            )
        ) == 1
        assert registered_store.read(
            agent_id="planner",
            scope=Scope(user="user_123", task="travel", session="sess_b"),
        ) == []


class TestAgentAuthority:
    def test_write_kind_enforcement(self, registered_store: GovernedMemoryStore) -> None:
        scope = Scope(user="user_123", task="travel", namespace="research")
        with pytest.raises(UnauthorizedWriteError):
            registered_store.write(
                agent_id="researcher",
                key="bad",
                value="x",
                scope=scope,
                authority="user_stated",
                provenance_source="turn 1",
                kind="plan",
            )

    def test_scope_namespace_enforcement(self, registered_store: GovernedMemoryStore) -> None:
        with pytest.raises(UnauthorizedWriteError):
            registered_store.write(
                agent_id="researcher",
                key="bad",
                value="x",
                scope=Scope(user="user_123", task="travel", namespace="planning"),
                authority="user_stated",
                provenance_source="turn 1",
                kind="fact",
            )

    def test_missing_namespace_rejected_when_agent_has_scopes(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        with pytest.raises(UnauthorizedWriteError):
            registered_store.write(
                agent_id="researcher",
                key="bad",
                value="x",
                scope=Scope(user="u"),
                authority="user_stated",
                provenance_source="turn 1",
                kind="fact",
            )

    def test_missing_kind_rejected_when_restricted(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        with pytest.raises(UnauthorizedWriteError):
            registered_store.write(
                agent_id="researcher",
                key="bad",
                value="x",
                scope=Scope(user="user_123", namespace="research"),
                authority="user_stated",
                provenance_source="turn 1",
            )

    def test_unrestricted_agent_can_write(self, store: GovernedMemoryStore) -> None:
        store.register_agent("free_agent")
        entry = store.write(
            agent_id="free_agent",
            key="k",
            value="v",
            scope=Scope(user="u"),
            authority="system",
            provenance_source="init",
        )
        assert entry.value == "v"

    def test_register_agent_rejects_duplicate(self, store: GovernedMemoryStore) -> None:
        store.register_agent("agent_a")
        with pytest.raises(AgentAlreadyRegisteredError):
            store.register_agent("agent_a")


class TestConflictDetection:
    def test_check_conflict_empty_for_missing_key(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        assert registered_store.check_conflict(
            "missing_key", "x", agent_id="researcher"
        ) == []

    def test_unregistered_agent_cannot_check_conflict(
        self, store: GovernedMemoryStore
    ) -> None:
        with pytest.raises(AgentNotRegisteredError):
            store.check_conflict("key", "x", agent_id="unknown")

    def test_check_conflict_finds_different_value(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", task="travel", namespace="research")
        registered_store.write(
            agent_id="researcher",
            key="user_location",
            value="Berlin",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 5",
            kind="fact",
        )
        conflicts = registered_store.check_conflict(
            "user_location", "Paris", agent_id="researcher", scope=scope
        )
        assert len(conflicts) == 1
        assert conflicts[0].value == "Berlin"

    def test_check_conflict_empty_for_same_value(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", namespace="research")
        registered_store.write(
            agent_id="researcher",
            key="user_location",
            value="Berlin",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 5",
            kind="fact",
        )
        assert registered_store.check_conflict(
            "user_location", "Berlin", agent_id="researcher", scope=scope
        ) == []

    def test_superseded_entries_not_conflicts(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", namespace="research")
        original = registered_store.write(
            agent_id="researcher",
            key="user_location",
            value="Berlin",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 5",
            kind="fact",
        )
        registered_store.supersede(
            entry_id=original.id,
            new_value="Hamburg",
            agent_id="researcher",
            reason="moved",
            evidence="turn 50",
        )
        conflicts = registered_store.check_conflict(
            "user_location", "Paris", agent_id="researcher", scope=scope
        )
        assert len(conflicts) == 1
        assert conflicts[0].value == "Hamburg"
        assert conflicts[0].id != original.id


class TestSupersession:
    def test_supersede_links_chain(self, registered_store: GovernedMemoryStore) -> None:
        scope = Scope(user="user_123", task="travel", namespace="research")
        original = registered_store.write(
            agent_id="researcher",
            key="user_location",
            value="Berlin",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 5",
            kind="fact",
        )
        successor = registered_store.supersede(
            entry_id=original.id,
            new_value="Hamburg",
            agent_id="researcher",
            reason="user moved",
            evidence="turn 50: 'I just moved'",
        )
        log = registered_store.audit_log(
            "user_location", agent_id="researcher", scope=scope
        )
        assert log[0].state.value == "superseded"
        assert log[0].superseded_by == successor.id
        assert successor.value == "Hamburg"
        assert successor.state.value == "active"

    def test_read_returns_only_active_by_default(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", task="travel", namespace="research")
        original = registered_store.write(
            agent_id="researcher",
            key="user_location",
            value="Berlin",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 5",
            kind="fact",
        )
        registered_store.supersede(
            entry_id=original.id,
            new_value="Hamburg",
            agent_id="researcher",
            reason="moved",
            evidence="turn 50",
        )
        active = registered_store.read(agent_id="planner", scope=Scope(user="user_123", task="travel"))
        assert len(active) == 1
        assert active[0].value == "Hamburg"

        all_entries = registered_store.read(
            agent_id="planner",
            scope=Scope(user="user_123", task="travel"),
            include_superseded=True,
        )
        assert len(all_entries) == 2


class TestAuditLog:
    def test_audit_log_returns_full_chain(self, registered_store: GovernedMemoryStore) -> None:
        scope = Scope(user="user_123", namespace="research")
        first = registered_store.write(
            agent_id="researcher",
            key="user_location",
            value="Berlin",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 5",
            kind="fact",
        )
        second = registered_store.supersede(
            entry_id=first.id,
            new_value="Hamburg",
            agent_id="researcher",
            reason="moved",
            evidence="turn 50",
        )
        third = registered_store.supersede(
            entry_id=second.id,
            new_value="Munich",
            agent_id="researcher",
            reason="moved again",
            evidence="turn 60",
        )
        log = registered_store.audit_log(
            "user_location", agent_id="researcher", scope=scope
        )
        assert [entry.id for entry in log] == [first.id, second.id, third.id]
        assert all(entry.key == "user_location" for entry in log)

    def test_audit_log_empty_for_unknown_key(self, registered_store: GovernedMemoryStore) -> None:
        assert registered_store.audit_log("missing", agent_id="researcher") == []

    def test_unregistered_agent_cannot_audit_log(self, store: GovernedMemoryStore) -> None:
        with pytest.raises(AgentNotRegisteredError):
            store.audit_log("key", agent_id="unknown")


class TestMutability:
    def test_locked_entry_cannot_be_superseded(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", namespace="research")
        entry = registered_store.write(
            agent_id="researcher",
            key="policy",
            value="no refunds",
            scope=scope,
            authority="policy",
            provenance_source="system init",
            mutability="locked",
            kind="fact",
        )
        with pytest.raises(LockedEntryError):
            registered_store.supersede(
                entry_id=entry.id,
                new_value="refunds ok",
                agent_id="researcher",
                reason="change",
                evidence="turn 99",
            )

    def test_locked_entry_blocks_revision_via_write(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", namespace="research")
        registered_store.write(
            agent_id="researcher",
            key="policy",
            value="no refunds",
            scope=scope,
            authority="policy",
            provenance_source="system init",
            mutability="locked",
            kind="fact",
        )
        with pytest.raises(LockedEntryError):
            registered_store.write(
                agent_id="researcher",
                key="policy",
                value="refunds ok",
                scope=scope,
                authority="policy",
                provenance_source="turn 99",
                kind="fact",
            )

    def test_supersede_only_rejects_direct_write(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", namespace="research")
        registered_store.write(
            agent_id="researcher",
            key="estimate",
            value="100",
            scope=scope,
            authority="agent_inferred",
            provenance_source="turn 1",
            mutability="supersede_only",
            kind="hypothesis",
        )
        with pytest.raises(SupersedeOnlyError):
            registered_store.write(
                agent_id="researcher",
                key="estimate",
                value="200",
                scope=scope,
                authority="agent_inferred",
                provenance_source="turn 2",
                kind="hypothesis",
            )

    def test_supersede_only_allows_supersede_path(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", namespace="research")
        original = registered_store.write(
            agent_id="researcher",
            key="estimate",
            value="100",
            scope=scope,
            authority="agent_inferred",
            provenance_source="turn 1",
            mutability="supersede_only",
            kind="hypothesis",
        )
        updated = registered_store.supersede(
            entry_id=original.id,
            new_value="200",
            agent_id="researcher",
            reason="new data",
            evidence="turn 2",
        )
        assert updated.value == "200"

    def test_revisable_auto_supersedes_on_write(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", namespace="research")
        first = registered_store.write(
            agent_id="researcher",
            key="note",
            value="v1",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 1",
            kind="fact",
        )
        second = registered_store.write(
            agent_id="researcher",
            key="note",
            value="v2",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 2",
            kind="fact",
        )
        log = registered_store.audit_log("note", agent_id="researcher", scope=scope)
        assert log[0].state.value == "superseded"
        assert log[0].superseded_by == second.id
        assert second.value == "v2"

    def test_decaying_entry_can_be_superseded(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", namespace="research")
        original = registered_store.write(
            agent_id="researcher",
            key="cache",
            value="stale",
            scope=scope,
            authority="system",
            provenance_source="turn 0",
            mutability="decaying",
            kind="fact",
        )
        successor = registered_store.supersede(
            entry_id=original.id,
            new_value="fresh",
            agent_id="researcher",
            reason="refresh",
            evidence="turn 10",
        )
        assert successor.value == "fresh"

    def test_supersede_missing_entry_raises(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        with pytest.raises(EntryNotFoundError):
            registered_store.supersede(
                entry_id="missing-id",
                new_value="x",
                agent_id="researcher",
                reason="n/a",
                evidence="n/a",
            )


class TestThreadSafety:
    def test_concurrent_writes(self, store: GovernedMemoryStore) -> None:
        store.register_agent("worker")
        errors: list[Exception] = []
        lock = threading.Lock()

        def write_one(index: int) -> None:
            try:
                store.write(
                    agent_id="worker",
                    key=f"key-{index}",
                    value=index,
                    scope=Scope(user="u", task=f"t-{index}"),
                    authority="system",
                    provenance_source=f"turn {index}",
                )
            except Exception as exc:  # pragma: no cover - collected for assertion
                with lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(write_one, range(50)))

        assert errors == []
        assert len(store.read(agent_id="worker", scope=Scope())) == 50


class TestGovernanceBlockers:
    """Tests for review-panel blocker fixes."""

    def test_returned_entry_mutation_does_not_affect_store(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", namespace="research")
        entry = registered_store.write(
            agent_id="researcher",
            key="fact",
            value="original",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 1",
            kind="fact",
        )
        with pytest.raises(Exception):
            entry.value = "mutated"  # frozen dataclass
        entries = registered_store.read(
            agent_id="planner", scope=Scope(user="user_123")
        )
        assert entries[0].value == "original"

    def test_locked_session_entry_not_bypassed_by_write_without_session(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        registered_store.write(
            agent_id="researcher",
            key="secret",
            value="private",
            scope=Scope(
                user="user_123",
                task="travel",
                session="private_sess",
                namespace="research",
            ),
            authority="user_stated",
            provenance_source="turn 1",
            mutability="locked",
            kind="fact",
        )
        with pytest.raises(LockedEntryError):
            registered_store.write(
                agent_id="researcher",
                key="secret",
                value="hacked",
                scope=Scope(user="user_123", task="travel", namespace="research"),
                authority="user_stated",
                provenance_source="turn 2",
                kind="fact",
            )

    def test_check_conflict_scope_filters_cross_user(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        registered_store.write(
            agent_id="researcher",
            key="budget",
            value="5000",
            scope=Scope(user="alice", task="travel", namespace="research"),
            authority="user_stated",
            provenance_source="t1",
            kind="fact",
        )
        registered_store.write(
            agent_id="researcher",
            key="budget",
            value="2000",
            scope=Scope(user="bob", task="travel", namespace="research"),
            authority="user_stated",
            provenance_source="t2",
            kind="fact",
        )
        alice_conflicts = registered_store.check_conflict(
            "budget",
            "5000",
            agent_id="researcher",
            scope=Scope(user="alice", task="travel"),
        )
        assert alice_conflicts == []
        bob_conflicts = registered_store.check_conflict(
            "budget",
            "5000",
            agent_id="researcher",
            scope=Scope(user="bob", task="travel"),
        )
        assert len(bob_conflicts) == 1
        assert bob_conflicts[0].value == "2000"

    def test_audit_log_scope_filters_cross_user(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        registered_store.write(
            agent_id="researcher",
            key="note",
            value="alice-only",
            scope=Scope(user="alice", namespace="research"),
            authority="user_stated",
            provenance_source="t1",
            kind="fact",
        )
        registered_store.write(
            agent_id="researcher",
            key="note",
            value="bob-only",
            scope=Scope(user="bob", namespace="research"),
            authority="user_stated",
            provenance_source="t2",
            kind="fact",
        )
        alice_log = registered_store.audit_log(
            "note", agent_id="researcher", scope=Scope(user="alice")
        )
        assert len(alice_log) == 1
        assert alice_log[0].value == "alice-only"

    def test_supersede_enforces_write_kinds(
        self, registered_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", namespace="planning")
        entry = registered_store.write(
            agent_id="planner",
            key="plan",
            value="step 1",
            scope=scope,
            authority="agent_inferred",
            provenance_source="t1",
            kind="plan",
        )
        with pytest.raises(UnauthorizedWriteError):
            registered_store.supersede(
                entry_id=entry.id,
                new_value="hacked",
                agent_id="researcher",
                reason="override",
                evidence="t2",
            )
