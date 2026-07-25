"""Multi-step governance scenarios — not unit tests, full narratives.

Each test simulates a realistic multi-agent workflow or adversarial attack
and asserts invariants that must hold across many operations.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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
from govmem.models import EntryState


@pytest.fixture
def fleet_store() -> GovernedMemoryStore:
    """Three-agent fleet: researcher, planner, support."""
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
    store.register_agent(
        "support",
        write_kinds=["note", "resolution"],
        scopes=["support"],
    )
    return store


def _research_scope(**kwargs: str) -> Scope:
    defaults = {"user": "user_123", "task": "travel", "namespace": "research"}
    defaults.update(kwargs)
    return Scope(**defaults)


def _plan_scope(**kwargs: str) -> Scope:
    defaults = {"user": "user_123", "task": "travel", "namespace": "planning"}
    defaults.update(kwargs)
    return Scope(**defaults)


class TestTravelPlanningScenario:
    """End-to-end: researcher gathers facts, planner builds plan, user revises."""

    def test_full_travel_lifecycle(self, fleet_store: GovernedMemoryStore) -> None:
        store = fleet_store
        rs = _research_scope()
        ps = _plan_scope()

        # Researcher ingests user-stated facts
        loc = store.write(
            agent_id="researcher",
            key="user_location",
            value="Berlin",
            scope=rs,
            authority="user_stated",
            provenance_source="turn 1: I live in Berlin",
            kind="fact",
        )
        store.write(
            agent_id="researcher",
            key="budget",
            value="200 EUR",
            scope=rs,
            authority="user_stated",
            provenance_source="turn 2: budget is 200 euros",
            kind="fact",
        )
        store.write(
            agent_id="researcher",
            key="interests",
            value="historical landmarks",
            scope=rs,
            authority="agent_inferred",
            provenance_source="turn 3: inferred from chat",
            kind="hypothesis",
        )

        # Planner reads research facts visible in travel scope
        planner_view = store.read(agent_id="planner", scope=Scope(user="user_123", task="travel"))
        planner_keys = {e.key for e in planner_view}
        assert {"user_location", "budget", "interests"}.issubset(planner_keys)

        # Planner writes plan in planning namespace
        store.write(
            agent_id="planner",
            key="itinerary",
            value="Day 1: Brandenburg Gate; Day 2: Museum Island",
            scope=ps,
            authority="agent_inferred",
            provenance_source="turn 10: generated plan",
            kind="plan",
        )

        # User corrects location — supersede chain
        store.supersede(
            entry_id=loc.id,
            new_value="Hamburg",
            agent_id="researcher",
            reason="user moved",
            evidence="turn 50: I just moved to Hamburg",
        )

        # Planner must see Hamburg, not Berlin
        locations = [
            e.value
            for e in store.read(agent_id="planner", scope=Scope(user="user_123", task="travel"))
            if e.key == "user_location"
        ]
        assert locations == ["Hamburg"]

        # Audit trail: Berlin → Hamburg with evidence
        audit = store.audit_log(
            key="user_location", agent_id="researcher", scope=Scope(user="user_123", task="travel")
        )
        assert len(audit) == 2
        assert audit[0].value == "Berlin" and audit[0].state == EntryState.SUPERSEDED
        assert audit[1].value == "Hamburg" and audit[1].state == EntryState.ACTIVE
        assert audit[0].superseded_by == audit[1].id

        # No duplicate active entries for same key+scope
        active_locs = [
            e
            for e in store.read(agent_id="planner", scope=Scope(user="user_123", task="travel"))
            if e.key == "user_location" and e.state == EntryState.ACTIVE
        ]
        assert len(active_locs) == 1


class TestFourFailureModes:
    """Each arXiv-cited failure mode as a strict pytest (mirrors prove_the_idea.py)."""

    @pytest.fixture
    def store(self) -> GovernedMemoryStore:
        s = GovernedMemoryStore()
        s.register_agent("researcher", write_kinds=["fact"], scopes=["research"])
        s.register_agent("planner", write_kinds=["plan"], scopes=["planning"])
        return s

    def test_unauthorized_leakage_private_session(self, store: GovernedMemoryStore) -> None:
        store.write(
            agent_id="researcher",
            key="therapy_note",
            value="patient anxiety",
            scope=Scope(
                user="u1", task="travel", session="private_sess", namespace="research"
            ),
            authority="user_stated",
            provenance_source="turn 1",
            kind="fact",
        )
        public_read = store.read(
            agent_id="planner",
            scope=Scope(user="u1", task="travel", session="public_sess"),
        )
        assert all(e.key != "therapy_note" for e in public_read)

    def test_stale_propagation_supersede_hides_old(self, store: GovernedMemoryStore) -> None:
        rs = Scope(user="u1", task="travel", namespace="research")
        store.write(
            agent_id="researcher",
            key="city",
            value="Berlin",
            scope=rs,
            authority="user_stated",
            provenance_source="t1",
            kind="fact",
        )
        entry = store.read(agent_id="planner", scope=Scope(user="u1", task="travel"))[0]
        store.supersede(
            entry_id=entry.id,
            new_value="Hamburg",
            agent_id="researcher",
            reason="moved",
            evidence="t2",
        )
        values = [
            e.value
            for e in store.read(agent_id="planner", scope=Scope(user="u1", task="travel"))
            if e.key == "city"
        ]
        assert values == ["Hamburg"]
        assert "Berlin" not in values

    def test_contradiction_detection_before_commit(self, store: GovernedMemoryStore) -> None:
        rs = Scope(user="u1", task="travel", namespace="research")
        store.write(
            agent_id="researcher",
            key="budget",
            value="500",
            scope=rs,
            authority="user_stated",
            provenance_source="t1",
            kind="fact",
        )
        conflicts = store.check_conflict(
            "budget", "200", agent_id="researcher", scope=Scope(user="u1", task="travel")
        )
        assert len(conflicts) == 1
        assert conflicts[0].value == "500"

    def test_provenance_chain_survives_many_writes(self, store: GovernedMemoryStore) -> None:
        rs = Scope(user="u1", task="travel", namespace="research")
        entry = store.write(
            agent_id="researcher",
            key="status",
            value="v0",
            scope=rs,
            authority="system",
            provenance_source="init",
            kind="fact",
        )
        for i in range(1, 8):
            entry = store.supersede(
                entry_id=entry.id,
                new_value=f"v{i}",
                agent_id="researcher",
                reason=f"rev {i}",
                evidence=f"turn {i}",
            )
        audit = store.audit_log(
            key="status", agent_id="researcher", scope=Scope(user="u1", task="travel")
        )
        assert len(audit) == 8
        assert [e.value for e in audit] == [f"v{i}" for i in range(8)]
        assert all(audit[i].superseded_by == audit[i + 1].id for i in range(7))
        assert audit[-1].state == EntryState.ACTIVE
        assert all(e.state == EntryState.SUPERSEDED for e in audit[:-1])
        agents = {e.provenance.agent_id for e in audit}
        assert agents == {"researcher"}


class TestAdversarialAttacks:
    """Agents attempting to bypass governance — all must fail."""

    def test_support_agent_cannot_write_research_facts(self, fleet_store: GovernedMemoryStore) -> None:
        with pytest.raises(UnauthorizedWriteError):
            fleet_store.write(
                agent_id="support",
                key="injected",
                value="malicious",
                scope=Scope(user="u1", namespace="research"),
                authority="system",
                provenance_source="attack",
                kind="fact",
            )

    def test_planner_cannot_supersede_research_entry(self, fleet_store: GovernedMemoryStore) -> None:
        entry = fleet_store.write(
            agent_id="researcher",
            key="fact",
            value="true",
            scope=_research_scope(user="u1"),
            authority="user_stated",
            provenance_source="t1",
            kind="fact",
        )
        with pytest.raises(UnauthorizedWriteError):
            fleet_store.supersede(
                entry_id=entry.id,
                new_value="false",
                agent_id="planner",
                reason="override",
                evidence="attack",
            )

    def test_cross_user_supersede_rejected(self, fleet_store: GovernedMemoryStore) -> None:
        entry = fleet_store.write(
            agent_id="researcher",
            key="secret",
            value="alice_data",
            scope=_research_scope(user="alice"),
            authority="user_stated",
            provenance_source="t1",
            kind="fact",
        )
        with pytest.raises(UnauthorizedWriteError):
            fleet_store.supersede(
                entry_id=entry.id,
                new_value="stolen",
                agent_id="researcher",
                reason="attack",
                evidence="wrong user scope",
                scope=Scope(user="bob", namespace="research"),
            )

    def test_unregistered_agent_blocked_on_every_api(self) -> None:
        store = GovernedMemoryStore()
        scope = Scope(user="u1")
        with pytest.raises(AgentNotRegisteredError):
            store.write(
                agent_id="intruder",
                key="k",
                value="v",
                scope=scope,
                authority="system",
                provenance_source="x",
            )
        with pytest.raises(AgentNotRegisteredError):
            store.read(agent_id="intruder", scope=scope)
        with pytest.raises(AgentNotRegisteredError):
            store.check_conflict("k", "v", agent_id="intruder")
        with pytest.raises(AgentNotRegisteredError):
            store.audit_log("k", agent_id="intruder")
        with pytest.raises(AgentNotRegisteredError):
            store.supersede(
                entry_id="fake-id",
                new_value="x",
                agent_id="intruder",
                reason="r",
                evidence="e",
            )

    def test_locked_entry_blocks_write_and_supersede(self, fleet_store: GovernedMemoryStore) -> None:
        rs = _research_scope()
        entry = fleet_store.write(
            agent_id="researcher",
            key="policy",
            value="immutable",
            scope=rs,
            authority="policy",
            provenance_source="legal",
            mutability="locked",
            kind="fact",
        )
        with pytest.raises(LockedEntryError):
            fleet_store.supersede(
                entry_id=entry.id,
                new_value="hacked",
                agent_id="researcher",
                reason="attack",
                evidence="x",
            )
        with pytest.raises(LockedEntryError):
            fleet_store.write(
                agent_id="researcher",
                key="policy",
                value="overwrite",
                scope=rs,
                authority="system",
                provenance_source="attack",
                kind="fact",
            )

    def test_supersede_only_rejects_direct_write(self, fleet_store: GovernedMemoryStore) -> None:
        rs = _research_scope()
        fleet_store.write(
            agent_id="researcher",
            key="verdict",
            value="guilty",
            scope=rs,
            authority="policy",
            provenance_source="court",
            mutability="supersede_only",
            kind="fact",
        )
        with pytest.raises(SupersedeOnlyError):
            fleet_store.write(
                agent_id="researcher",
                key="verdict",
                value="innocent",
                scope=rs,
                authority="policy",
                provenance_source="retry",
                kind="fact",
            )

    def test_returned_entry_mutation_does_not_corrupt_store(
        self, fleet_store: GovernedMemoryStore
    ) -> None:
        rs = _research_scope()
        entry = fleet_store.write(
            agent_id="researcher",
            key="x",
            value="original",
            scope=rs,
            authority="system",
            provenance_source="t1",
            kind="fact",
        )
        # Attempt in-place tampering on frozen entry — must not affect store
        with pytest.raises((AttributeError, TypeError)):
            entry.value = "tampered"  # type: ignore[misc]
        fresh = fleet_store.read(agent_id="planner", scope=Scope(user="user_123", task="travel"))
        assert fresh[0].value == "original"

    def test_duplicate_agent_registration_rejected(self, fleet_store: GovernedMemoryStore) -> None:
        with pytest.raises(AgentAlreadyRegisteredError):
            fleet_store.register_agent("researcher", write_kinds=["fact"], scopes=["research"])


class TestScopeIsolationMatrix:
    """Parameterized isolation across scope dimensions."""

    @pytest.mark.parametrize(
        "writer_scope,reader_scope,should_see",
        [
            (Scope(user="a", task="t"), Scope(user="a", task="t"), True),
            (Scope(user="a", task="t"), Scope(user="b", task="t"), False),
            (Scope(user="a", task="t1"), Scope(user="a", task="t2"), False),
            (Scope(user="a", task="t", namespace="research"), Scope(user="a", task="t"), True),
            (Scope(user="a", task="t", session="s1"), Scope(user="a", task="t", session="s2"), False),
        ],
    )
    def test_read_visibility(
        self,
        writer_scope: Scope,
        reader_scope: Scope,
        should_see: bool,
    ) -> None:
        store = GovernedMemoryStore()
        store.register_agent("researcher", write_kinds=["fact"], scopes=["research"])
        store.register_agent("reader")
        if writer_scope.namespace is None:
            writer_scope = Scope(
                user=writer_scope.user,
                task=writer_scope.task,
                session=writer_scope.session,
                namespace="research",
            )
        store.write(
            agent_id="researcher",
            key="probe",
            value="seen",
            scope=writer_scope,
            authority="system",
            provenance_source="test",
            kind="fact",
        )
        results = store.read(agent_id="reader", scope=reader_scope)
        probe = [e for e in results if e.key == "probe"]
        if should_see:
            assert len(probe) == 1 and probe[0].value == "seen"
        else:
            assert probe == []


class TestConcurrentFleet:
    """Many agents writing concurrently — invariants must hold."""

    def test_concurrent_multi_key_writes_no_corruption(self, fleet_store: GovernedMemoryStore) -> None:
        rs = _research_scope()
        errors: list[Exception] = []
        lock = threading.Lock()

        def write_fact(key: str, value: str) -> None:
            try:
                fleet_store.write(
                    agent_id="researcher",
                    key=key,
                    value=value,
                    scope=rs,
                    authority="system",
                    provenance_source=f"write {key}={value}",
                    kind="fact",
                )
            except Exception as exc:
                with lock:
                    errors.append(exc)

        keys = [f"metric_{i}" for i in range(50)]
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(write_fact, k, f"v_{k}") for k in keys]
            for f in as_completed(futures):
                f.result()

        assert errors == []
        active = fleet_store.read(
            agent_id="planner", scope=Scope(user="user_123", task="travel")
        )
        active_keys = {e.key for e in active if e.key.startswith("metric_")}
        assert active_keys == set(keys)

    def test_concurrent_supersede_same_key_single_active(
        self, fleet_store: GovernedMemoryStore
    ) -> None:
        rs = _research_scope()
        fleet_store.write(
            agent_id="researcher",
            key="counter",
            value="v0",
            scope=rs,
            authority="system",
            provenance_source="init",
            kind="fact",
        )
        errors: list[Exception] = []
        lock = threading.Lock()

        def revise(i: int) -> None:
            try:
                active = [
                    e
                    for e in fleet_store.read(
                        agent_id="planner", scope=Scope(user="user_123", task="travel")
                    )
                    if e.key == "counter" and e.state == EntryState.ACTIVE
                ]
                if active:
                    fleet_store.write(
                        agent_id="researcher",
                        key="counter",
                        value=f"v{i}",
                        scope=rs,
                        authority="system",
                        provenance_source=f"rev {i}",
                        kind="fact",
                    )
            except Exception as exc:
                with lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(revise, range(30)))

        assert errors == []
        active = [
            e
            for e in fleet_store.read(
                agent_id="planner", scope=Scope(user="user_123", task="travel")
            )
            if e.key == "counter"
        ]
        assert len(active) == 1
        audit = fleet_store.audit_log(
            key="counter", agent_id="researcher", scope=Scope(user="user_123", task="travel")
        )
        assert len(audit) >= 2  # initial + at least one revision
        assert audit[-1].state == EntryState.ACTIVE


class TestAuditLogIntegrity:
    """Audit log must be complete and ordered under complex operations."""

    def test_branched_keys_isolated_in_audit(self, fleet_store: GovernedMemoryStore) -> None:
        rs = _research_scope()
        for key, val in [("alpha", "1"), ("beta", "2"), ("gamma", "3")]:
            store_write = fleet_store.write(
                agent_id="researcher",
                key=key,
                value=val,
                scope=rs,
                authority="system",
                provenance_source=f"init {key}",
                kind="fact",
            )
            fleet_store.supersede(
                entry_id=store_write.id,
                new_value=f"{val}_updated",
                agent_id="researcher",
                reason="update",
                evidence=f"rev {key}",
            )
        for key in ("alpha", "beta", "gamma"):
            log = fleet_store.audit_log(
                key=key, agent_id="researcher", scope=Scope(user="user_123", task="travel")
            )
            assert len(log) == 2
            assert log[0].state == EntryState.SUPERSEDED
            assert log[1].state == EntryState.ACTIVE

    def test_audit_empty_for_unknown_key(self, fleet_store: GovernedMemoryStore) -> None:
        assert (
            fleet_store.audit_log(
                key="nonexistent",
                agent_id="researcher",
                scope=Scope(user="user_123"),
            )
            == []
        )

    def test_audit_respects_scope_filter(self, fleet_store: GovernedMemoryStore) -> None:
        fleet_store.write(
            agent_id="researcher",
            key="shared",
            value="alice",
            scope=_research_scope(user="alice"),
            authority="system",
            provenance_source="t1",
            kind="fact",
        )
        fleet_store.write(
            agent_id="researcher",
            key="shared",
            value="bob",
            scope=_research_scope(user="bob"),
            authority="system",
            provenance_source="t2",
            kind="fact",
        )
        alice_audit = fleet_store.audit_log(
            key="shared", agent_id="researcher", scope=Scope(user="alice")
        )
        bob_audit = fleet_store.audit_log(
            key="shared", agent_id="researcher", scope=Scope(user="bob")
        )
        assert len(alice_audit) == 1 and alice_audit[0].value == "alice"
        assert len(bob_audit) == 1 and bob_audit[0].value == "bob"

    def test_supersede_nonexistent_raises(self, fleet_store: GovernedMemoryStore) -> None:
        with pytest.raises(EntryNotFoundError):
            fleet_store.supersede(
                entry_id="00000000-0000-0000-0000-000000000000",
                new_value="x",
                agent_id="researcher",
                reason="r",
                evidence="e",
            )

    def test_double_supersede_same_entry_rejected(self, fleet_store: GovernedMemoryStore) -> None:
        rs = _research_scope()
        original = fleet_store.write(
            agent_id="researcher",
            key="x",
            value="v1",
            scope=rs,
            authority="system",
            provenance_source="t1",
            kind="fact",
        )
        fleet_store.supersede(
            entry_id=original.id,
            new_value="v2",
            agent_id="researcher",
            reason="r",
            evidence="e",
        )
        with pytest.raises(LockedEntryError):
            fleet_store.supersede(
                entry_id=original.id,
                new_value="v3",
                agent_id="researcher",
                reason="stale",
                evidence="e2",
            )


class TestConflictDetectionScenarios:
    """Structural conflict detection across realistic cases."""

    def test_no_conflict_when_values_match(self, fleet_store: GovernedMemoryStore) -> None:
        rs = _research_scope()
        fleet_store.write(
            agent_id="researcher",
            key="temp",
            value="20C",
            scope=rs,
            authority="system",
            provenance_source="t1",
            kind="fact",
        )
        assert (
            fleet_store.check_conflict(
                "temp", "20C", agent_id="researcher", scope=Scope(user="user_123", task="travel")
            )
            == []
        )

    def test_conflict_scoped_to_user_not_global(self, fleet_store: GovernedMemoryStore) -> None:
        for user, val in [("alice", "500"), ("bob", "200")]:
            fleet_store.write(
                agent_id="researcher",
                key="budget",
                value=val,
                scope=_research_scope(user=user),
                authority="system",
                provenance_source=f"t-{user}",
                kind="fact",
            )
        # Checking alice scope should not flag bob's budget
        alice_conflicts = fleet_store.check_conflict(
            "budget", "999", agent_id="researcher", scope=Scope(user="alice", task="travel")
        )
        assert len(alice_conflicts) == 1
        assert alice_conflicts[0].value == "500"

    def test_superseded_entries_not_conflicts(self, fleet_store: GovernedMemoryStore) -> None:
        rs = _research_scope()
        entry = fleet_store.write(
            agent_id="researcher",
            key="loc",
            value="Berlin",
            scope=rs,
            authority="system",
            provenance_source="t1",
            kind="fact",
        )
        fleet_store.supersede(
            entry_id=entry.id,
            new_value="Hamburg",
            agent_id="researcher",
            reason="moved",
            evidence="t2",
        )
        conflicts = fleet_store.check_conflict(
            "loc", "Paris", agent_id="researcher", scope=Scope(user="user_123", task="travel")
        )
        assert len(conflicts) == 1
        assert conflicts[0].value == "Hamburg"  # only active entry; Berlin is superseded
