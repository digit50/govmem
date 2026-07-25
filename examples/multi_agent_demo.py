"""Simulated multi-agent workflow using governed shared memory."""

from govmem import GovernedMemoryStore, Scope


def main() -> None:
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

    travel_scope = Scope(user="user_123", task="travel", namespace="research")
    read_scope = Scope(user="user_123", task="travel")

    location = store.write(
        agent_id="researcher",
        key="user_location",
        value="Berlin",
        scope=travel_scope,
        authority="user_stated",
        provenance_source="turn 5: 'I live in Berlin'",
        mutability="revisable",
        kind="fact",
    )
    print(f"Researcher wrote: {location.key}={location.value!r} (id={location.id})")

    plan_scope = Scope(user="user_123", task="travel", namespace="planning")
    plan = store.write(
        agent_id="planner",
        key="itinerary",
        value="Day 1: Brandenburg Gate",
        scope=plan_scope,
        authority="agent_inferred",
        provenance_source="turn 6: planner draft",
        kind="plan",
    )
    print(f"Planner wrote: {plan.key}={plan.value!r}")

    context = store.read(agent_id="planner", scope=read_scope)
    print(f"Planner sees {len(context)} entries in travel scope:")
    for entry in context:
        print(f"  - {entry.key}: {entry.value!r} [{entry.authority.value}]")

    conflicts = store.check_conflict("user_location", "Paris")
    if conflicts:
        print(f"Conflict detected for user_location vs Paris: {conflicts[0].value!r}")

    updated = store.supersede(
        entry_id=location.id,
        new_value="Hamburg",
        agent_id="researcher",
        reason="user moved",
        evidence="turn 50: 'I just moved'",
    )
    print(f"Superseded location -> {updated.value!r}")

    log = store.audit_log(key="user_location")
    print(f"Audit log ({len(log)} entries):")
    for entry in log:
        print(
            f"  - {entry.state.value}: {entry.value!r} "
            f"(agent={entry.provenance.agent_id}, evidence={entry.provenance.evidence_spans[0]!r})"
        )


if __name__ == "__main__":
    main()
