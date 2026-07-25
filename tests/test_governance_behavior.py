"""Behavioral tests: leakage, stale propagation, provenance, adversarial cases."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from govmem import (
    AgentNotRegisteredError,
    GovernedMemoryStore,
    LockedEntryError,
    Scope,
    UnauthorizedWriteError,
)
from govmem.exceptions import EntryNotFoundError


@pytest.fixture
def multi_agent_store() -> GovernedMemoryStore:
    store = GovernedMemoryStore()
    store.register_agent(
        "researcher",
        write_kinds=["fact", "hypothesis"],
        scopes=["research"],
    )
    store.register_agent(
        "planner",
        write_kinds=["plan"],
        scopes=["planning"],
    )
    return store


class TestScopeLeakage:
    """Structural scope matching must prevent cross-context leakage."""

    def test_cross_user_isolation_same_task(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        multi_agent_store.write(
            agent_id="researcher",
            key="budget",
            value="5000 EUR",
            scope=Scope(user="alice", task="travel", namespace="research"),
            authority="user_stated",
            provenance_source="turn 1",
            kind="fact",
        )
        multi_agent_store.write(
            agent_id="researcher",
            key="budget",
            value="2000 USD",
            scope=Scope(user="bob", task="travel", namespace="research"),
            authority="user_stated",
            provenance_source="turn 2",
            kind="fact",
        )
        alice_view = multi_agent_store.read(
            agent_id="planner",
            scope=Scope(user="alice", task="travel"),
        )
        bob_view = multi_agent_store.read(
            agent_id="planner",
            scope=Scope(user="bob", task="travel"),
        )
        assert {e.value for e in alice_view} == {"5000 EUR"}
        assert {e.value for e in bob_view} == {"2000 USD"}

    def test_session_private_note_hidden_when_reader_specifies_other_session(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        multi_agent_store.write(
            agent_id="researcher",
            key="therapy_note",
            value="confidential",
            scope=Scope(
                user="user_123",
                task="travel",
                session="private_sess",
                namespace="research",
            ),
            authority="user_stated",
            provenance_source="turn 99",
            kind="fact",
        )
        assert multi_agent_store.read(
            agent_id="planner",
            scope=Scope(user="user_123", task="travel", session="public_sess"),
        ) == []

    def test_session_tagged_entry_visible_when_reader_omits_session(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        """Documents structural matching: omitting session does not restrict visibility."""
        multi_agent_store.write(
            agent_id="researcher",
            key="therapy_note",
            value="confidential",
            scope=Scope(
                user="user_123",
                task="travel",
                session="private_sess",
                namespace="research",
            ),
            authority="user_stated",
            provenance_source="turn 99",
            kind="fact",
        )
        entries = multi_agent_store.read(
            agent_id="planner",
            scope=Scope(user="user_123", task="travel"),
        )
        assert len(entries) == 1
        assert entries[0].value == "confidential"

    def test_namespace_does_not_block_cross_namespace_read(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        multi_agent_store.write(
            agent_id="researcher",
            key="user_location",
            value="Berlin",
            scope=Scope(user="user_123", task="travel", namespace="research"),
            authority="user_stated",
            provenance_source="turn 5",
            kind="fact",
        )
        multi_agent_store.write(
            agent_id="planner",
            key="itinerary",
            value="Day 1: Museum",
            scope=Scope(user="user_123", task="travel", namespace="planning"),
            authority="agent_inferred",
            provenance_source="turn 6",
            kind="plan",
        )
        context = multi_agent_store.read(
            agent_id="planner",
            scope=Scope(user="user_123", task="travel"),
        )
        keys = {entry.key for entry in context}
        assert keys == {"user_location", "itinerary"}


class TestStalePropagation:
    """Readers must see current active values after supersession."""

    def test_planner_sees_superseded_value_not_stale(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", task="travel", namespace="research")
        original = multi_agent_store.write(
            agent_id="researcher",
            key="user_location",
            value="Berlin",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 5",
            kind="fact",
        )
        before = multi_agent_store.read(
            agent_id="planner",
            scope=Scope(user="user_123", task="travel"),
        )
        assert before[0].value == "Berlin"

        multi_agent_store.supersede(
            entry_id=original.id,
            new_value="Hamburg",
            agent_id="researcher",
            reason="user moved",
            evidence="turn 50",
        )
        after = multi_agent_store.read(
            agent_id="planner",
            scope=Scope(user="user_123", task="travel"),
        )
        assert len(after) == 1
        assert after[0].value == "Hamburg"
        assert after[0].id != original.id

    def test_revisable_write_propagates_to_readers(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", task="travel", namespace="research")
        multi_agent_store.write(
            agent_id="researcher",
            key="hotel",
            value="Hotel A",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 1",
            kind="fact",
        )
        multi_agent_store.write(
            agent_id="researcher",
            key="hotel",
            value="Hotel B",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 2",
            kind="fact",
        )
        entries = multi_agent_store.read(
            agent_id="planner",
            scope=Scope(user="user_123", task="travel"),
        )
        hotel = [e for e in entries if e.key == "hotel"]
        assert len(hotel) == 1
        assert hotel[0].value == "Hotel B"


class TestProvenanceAndAudit:
    """Provenance chain must be preserved through supersession."""

    def test_audit_log_preserves_agent_and_evidence_per_generation(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", namespace="research")
        first = multi_agent_store.write(
            agent_id="researcher",
            key="fact",
            value="v1",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 1: original",
            kind="fact",
        )
        second = multi_agent_store.supersede(
            entry_id=first.id,
            new_value="v2",
            agent_id="researcher",
            reason="correction",
            evidence="turn 2: updated",
        )
        log = multi_agent_store.audit_log("fact", agent_id="researcher")
        assert len(log) == 2
        assert log[0].provenance.agent_id == "researcher"
        assert "turn 1" in log[0].provenance.evidence_spans[0]
        assert log[1].id == second.id
        assert "correction" in log[1].provenance.evidence_spans[0]
        assert "turn 2" in log[1].provenance.evidence_spans[0]

    def test_write_records_source_turn_in_provenance(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        entry = multi_agent_store.write(
            agent_id="researcher",
            key="fact",
            value="data",
            scope=Scope(user="u", namespace="research"),
            authority="user_stated",
            provenance_source="turn 7",
            source_turn=7,
            kind="fact",
        )
        assert entry.provenance.source_turn == 7


class TestContradictions:
    """Structural conflict detection across active entries."""

    def test_conflict_detects_same_key_different_value_across_scopes(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        multi_agent_store.write(
            agent_id="researcher",
            key="temperature",
            value="20C",
            scope=Scope(user="u1", task="weather", namespace="research"),
            authority="agent_inferred",
            provenance_source="turn 1",
            kind="fact",
        )
        multi_agent_store.write(
            agent_id="researcher",
            key="temperature",
            value="25C",
            scope=Scope(user="u2", task="weather", namespace="research"),
            authority="agent_inferred",
            provenance_source="turn 2",
            kind="fact",
        )
        conflicts = multi_agent_store.check_conflict(
            "temperature", "20C", agent_id="researcher"
        )
        assert len(conflicts) == 1
        assert conflicts[0].value == "25C"

    def test_no_conflict_when_all_active_match_proposed_value(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        scope_a = Scope(user="u1", namespace="research")
        scope_b = Scope(user="u2", namespace="research")
        multi_agent_store.write(
            agent_id="researcher",
            key="status",
            value="ok",
            scope=scope_a,
            authority="system",
            provenance_source="t1",
            kind="fact",
        )
        multi_agent_store.write(
            agent_id="researcher",
            key="status",
            value="ok",
            scope=scope_b,
            authority="system",
            provenance_source="t2",
            kind="fact",
        )
        assert multi_agent_store.check_conflict(
            "status", "ok", agent_id="researcher"
        ) == []


class TestAdversarial:
    """Authority bypass and concurrent mutation attempts."""

    def test_unregistered_agent_cannot_write(self) -> None:
        store = GovernedMemoryStore()
        with pytest.raises(AgentNotRegisteredError):
            store.write(
                agent_id="intruder",
                key="k",
                value="v",
                scope=Scope(user="u"),
                authority="system",
                provenance_source="x",
            )

    def test_planner_cannot_supersede_research_namespace_entry(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        entry = multi_agent_store.write(
            agent_id="researcher",
            key="user_location",
            value="Berlin",
            scope=Scope(user="user_123", task="travel", namespace="research"),
            authority="user_stated",
            provenance_source="turn 5",
            kind="fact",
        )
        with pytest.raises(UnauthorizedWriteError):
            multi_agent_store.supersede(
                entry_id=entry.id,
                new_value="Paris",
                agent_id="planner",
                reason="override",
                evidence="turn 99",
            )

    def test_cannot_supersede_already_superseded_entry(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", namespace="research")
        original = multi_agent_store.write(
            agent_id="researcher",
            key="fact",
            value="v1",
            scope=scope,
            authority="user_stated",
            provenance_source="turn 1",
            kind="fact",
        )
        multi_agent_store.supersede(
            entry_id=original.id,
            new_value="v2",
            agent_id="researcher",
            reason="update",
            evidence="turn 2",
        )
        with pytest.raises(LockedEntryError):
            multi_agent_store.supersede(
                entry_id=original.id,
                new_value="v3",
                agent_id="researcher",
                reason="stale supersede",
                evidence="turn 3",
            )

    def test_locked_entry_survives_concurrent_supersede_attempts(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", namespace="research")
        entry = multi_agent_store.write(
            agent_id="researcher",
            key="policy",
            value="immutable",
            scope=scope,
            authority="policy",
            provenance_source="init",
            mutability="locked",
            kind="fact",
        )
        errors: list[Exception] = []
        lock = threading.Lock()

        def attempt_supersede() -> None:
            try:
                multi_agent_store.supersede(
                    entry_id=entry.id,
                    new_value="hacked",
                    agent_id="researcher",
                    reason="attack",
                    evidence="turn 0",
                )
            except LockedEntryError as exc:
                with lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _: attempt_supersede(), range(8)))

        assert len(errors) == 8
        active = multi_agent_store.read(
            agent_id="planner",
            scope=Scope(user="user_123"),
        )
        assert active[0].value == "immutable"
        assert active[0].state.value == "active"

    def test_concurrent_writes_same_key_produce_single_active_entry(
        self, multi_agent_store: GovernedMemoryStore
    ) -> None:
        scope = Scope(user="user_123", task="travel", namespace="research")
        errors: list[Exception] = []
        lock = threading.Lock()

        def write_version(value: str) -> None:
            try:
                multi_agent_store.write(
                    agent_id="researcher",
                    key="counter",
                    value=value,
                    scope=scope,
                    authority="system",
                    provenance_source=f"write {value}",
                    kind="fact",
                )
            except Exception as exc:
                with lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(write_version, [f"v{i}" for i in range(20)]))

        assert errors == []
        active = multi_agent_store.read(
            agent_id="planner",
            scope=Scope(user="user_123", task="travel"),
        )
        counter_entries = [e for e in active if e.key == "counter"]
        assert len(counter_entries) == 1
        log = multi_agent_store.audit_log("counter", agent_id="researcher")
        assert len(log) == 20
        assert log[-1].state.value == "active"
        assert all(e.state.value == "superseded" for e in log[:-1])
