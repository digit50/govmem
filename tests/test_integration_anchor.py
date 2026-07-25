"""External anchor: multi-agent integration scenario with hard assertions.

Run standalone:
    cd projects/govmem && PYTHONPATH=src python -m tests.test_integration_anchor
"""

from __future__ import annotations

from govmem import GovernedMemoryStore, Scope


def run_multi_agent_scenario() -> dict[str, object]:
    """Simulate researcher + planner workflow; return observable outcomes."""
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

    travel_research = Scope(user="user_123", task="travel", namespace="research")
    travel_read = Scope(user="user_123", task="travel")
    travel_planning = Scope(user="user_123", task="travel", namespace="planning")
    other_user = Scope(user="user_999", task="travel")

    location = store.write(
        agent_id="researcher",
        key="user_location",
        value="Berlin",
        scope=travel_research,
        authority="user_stated",
        provenance_source="turn 5: 'I live in Berlin'",
        mutability="revisable",
        kind="fact",
    )
    store.write(
        agent_id="planner",
        key="itinerary",
        value="Day 1: Brandenburg Gate",
        scope=travel_planning,
        authority="agent_inferred",
        provenance_source="turn 6: planner draft",
        kind="plan",
    )

    planner_context_before = store.read(agent_id="planner", scope=travel_read)
    conflicts = store.check_conflict("user_location", "Paris", agent_id="researcher")
    leaked = store.read(agent_id="planner", scope=other_user)

    updated = store.supersede(
        entry_id=location.id,
        new_value="Hamburg",
        agent_id="researcher",
        reason="user moved",
        evidence="turn 50: 'I just moved'",
    )
    planner_context_after = store.read(agent_id="planner", scope=travel_read)
    audit = store.audit_log("user_location", agent_id="researcher")

    return {
        "planner_context_before_count": len(planner_context_before),
        "planner_keys_before": sorted(e.key for e in planner_context_before),
        "conflict_count": len(conflicts),
        "conflict_value": conflicts[0].value if conflicts else None,
        "leaked_count": len(leaked),
        "updated_value": updated.value,
        "planner_location_after": next(
            e.value for e in planner_context_after if e.key == "user_location"
        ),
        "audit_length": len(audit),
        "audit_states": [e.state.value for e in audit],
        "audit_values": [e.value for e in audit],
    }


def test_integration_anchor_multi_agent_scenario() -> None:
    """External anchor assertions mirroring examples/multi_agent_demo.py."""
    result = run_multi_agent_scenario()

    assert result["planner_context_before_count"] == 2
    assert result["planner_keys_before"] == ["itinerary", "user_location"]
    assert result["conflict_count"] == 1
    assert result["conflict_value"] == "Berlin"
    assert result["leaked_count"] == 0
    assert result["updated_value"] == "Hamburg"
    assert result["planner_location_after"] == "Hamburg"
    assert result["audit_length"] == 2
    assert result["audit_states"] == ["superseded", "active"]
    assert result["audit_values"] == ["Berlin", "Hamburg"]


if __name__ == "__main__":
    result = run_multi_agent_scenario()
    checks = [
        ("planner sees 2 entries", result["planner_context_before_count"] == 2),
        ("scope isolation (other user)", result["leaked_count"] == 0),
        ("conflict detected", result["conflict_count"] == 1),
        ("supersession propagated", result["planner_location_after"] == "Hamburg"),
        ("audit trail intact", result["audit_length"] == 2),
    ]
    for label, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label}")
    if not all(ok for _, ok in checks):
        raise SystemExit(1)
    print("Integration anchor: all checks passed")
