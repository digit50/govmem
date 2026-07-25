#!/usr/bin/env python3
"""Comparative validation: governed vs ungoverned shared memory.

Demonstrates four failure modes from  that naive shared
memory exhibits, and that govmem prevents:

  1. Unauthorized leakage
  2. Stale propagation
  3. Contradiction persistence
  4. Provenance collapse

Exit 0 only when all four modes show ungoverned=FAIL and governed=PASS.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from govmem import GovernedMemoryStore, Scope


# ---------------------------------------------------------------------------
# Ungoverned (naive) store — flat dict, no scope / supersession / audit
# ---------------------------------------------------------------------------


@dataclass
class UngovernedEntry:
    key: str
    value: Any
    agent_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


class UngovernedStore:
    """Naive shared memory: append-only list, no governance envelope."""

    def __init__(self) -> None:
        self._entries: list[UngovernedEntry] = []

    def write(
        self,
        *,
        key: str,
        value: Any,
        agent_id: str,
        **metadata: Any,
    ) -> None:
        self._entries.append(
            UngovernedEntry(key=key, value=value, agent_id=agent_id, metadata=metadata)
        )

    def read_all(self) -> list[UngovernedEntry]:
        return list(self._entries)

    def read_by_key(self, key: str) -> list[UngovernedEntry]:
        return [e for e in self._entries if e.key == key]

    def check_conflict(self, key: str, value: Any) -> list[UngovernedEntry]:
        return []

    def audit_log(self, key: str) -> list[UngovernedEntry]:
        return []


# ---------------------------------------------------------------------------
# Proof result tracking
# ---------------------------------------------------------------------------


@dataclass
class ProofResult:
    failure_mode: str
    ungoverned_pass: bool
    governed_pass: bool
    ungoverned_detail: str
    governed_detail: str

    @property
    def ungoverned_verdict(self) -> str:
        return "PASS" if self.ungoverned_pass else "FAIL"

    @property
    def governed_verdict(self) -> str:
        return "PASS" if self.governed_pass else "FAIL"

    @property
    def proof_ok(self) -> bool:
        return (not self.ungoverned_pass) and self.governed_pass


def _register_agents(store: GovernedMemoryStore) -> None:
    store.register_agent(
        "researcher",
        write_kinds=["fact", "hypothesis", "note"],
        scopes=["research"],
    )
    store.register_agent(
        "planner",
        write_kinds=["plan"],
        scopes=["planning"],
    )
    store.register_agent(
        "support",
        write_kinds=["note"],
        scopes=["support"],
    )


# ---------------------------------------------------------------------------
# Four proofs
# ---------------------------------------------------------------------------


def prove_unauthorized_leakage() -> ProofResult:
    """Private session note must not appear in planner's travel read."""
    # --- Ungoverned ---
    naive = UngovernedStore()
    naive.write(
        key="session_note",
        value="User mentioned anxiety about flying — keep private",
        agent_id="researcher",
        session="private_sess",
        task="travel",
    )
    naive_travel_read = naive.read_all()
    naive_leaked = any(
        "anxiety" in str(e.value) for e in naive_travel_read
    )

    # --- Governed ---
    gov = GovernedMemoryStore()
    _register_agents(gov)
    gov.write(
        agent_id="researcher",
        key="session_note",
        value="User mentioned anxiety about flying — keep private",
        scope=Scope(
            user="user_123",
            task="travel",
            session="private_sess",
            namespace="research",
        ),
        authority="user_stated",
        provenance_source="turn 3: private disclosure",
        kind="note",
    )
    gov_travel_read = gov.read(
        agent_id="planner",
        scope=Scope(user="user_123", task="travel", session="public_sess"),
    )
    gov_leaked = any("anxiety" in str(e.value) for e in gov_travel_read)

    return ProofResult(
        failure_mode="Unauthorized leakage",
        ungoverned_pass=not naive_leaked,
        governed_pass=not gov_leaked,
        ungoverned_detail=(
            f"Planner sees {len(naive_travel_read)} entries including private note"
            if naive_leaked
            else "Planner did not see private note (unexpected)"
        ),
        governed_detail=(
            f"Planner sees {len(gov_travel_read)} entries (private note filtered out)"
            if not gov_leaked
            else "Planner saw private note (unexpected)"
        ),
    )


def prove_stale_propagation() -> ProofResult:
    """After supersede Berlin→Hamburg, only Hamburg is active."""
    travel_meta = {"user": "user_123", "task": "travel"}

    # --- Ungoverned: append-only, no supersession ---
    naive = UngovernedStore()
    naive.write(key="user_location", value="Berlin", agent_id="researcher", **travel_meta)
    naive.write(key="user_location", value="Hamburg", agent_id="researcher", **travel_meta)
    naive_active = naive.read_by_key("user_location")
    naive_stale = any(e.value == "Berlin" for e in naive_active) and any(
        e.value == "Hamburg" for e in naive_active
    )

    # --- Governed ---
    gov = GovernedMemoryStore()
    _register_agents(gov)
    scope = Scope(user="user_123", task="travel", namespace="research")
    berlin = gov.write(
        agent_id="researcher",
        key="user_location",
        value="Berlin",
        scope=scope,
        authority="user_stated",
        provenance_source="turn 5: 'I live in Berlin'",
        kind="fact",
    )
    gov.supersede(
        entry_id=berlin.id,
        new_value="Hamburg",
        agent_id="researcher",
        reason="user moved",
        evidence="turn 50: 'I just moved to Hamburg'",
    )
    gov_read = gov.read(
        agent_id="planner",
        scope=Scope(user="user_123", task="travel"),
    )
    location_values = [e.value for e in gov_read if e.key == "user_location"]
    gov_fresh = location_values == ["Hamburg"]

    return ProofResult(
        failure_mode="Stale propagation",
        ungoverned_pass=not naive_stale,
        governed_pass=gov_fresh,
        ungoverned_detail=(
            f"Both Berlin and Hamburg coexist as active ({len(naive_active)} entries)"
            if naive_stale
            else "Only one value visible (unexpected)"
        ),
        governed_detail=(
            f"Planner sees active location={location_values!r}"
            if gov_fresh
            else f"Stale values remain: {location_values!r}"
        ),
    )


def prove_contradiction_persistence() -> ProofResult:
    """Conflicting writes for same key must be flagged, not silently coexisting."""
    shared_scope = {"user": "user_123", "task": "travel"}

    # --- Ungoverned: both values coexist, no conflict check ---
    naive = UngovernedStore()
    naive.write(key="budget", value="5000 EUR", agent_id="researcher", **shared_scope)
    naive.write(key="budget", value="3000 EUR", agent_id="support", **shared_scope)
    naive_conflicts = naive.check_conflict("budget", "5000 EUR")
    naive_silent = len(naive_conflicts) == 0 and len(naive.read_by_key("budget")) == 2

    # --- Governed ---
    gov = GovernedMemoryStore()
    _register_agents(gov)
    scope = Scope(user="user_123", task="travel", namespace="research")
    gov.write(
        agent_id="researcher",
        key="budget",
        value="5000 EUR",
        scope=scope,
        authority="user_stated",
        provenance_source="turn 10: user stated budget",
        kind="fact",
    )
    support_scope = Scope(user="user_123", task="travel", namespace="support")
    gov.write(
        agent_id="support",
        key="budget",
        value="3000 EUR",
        scope=support_scope,
        authority="agent_inferred",
        provenance_source="turn 11: support estimate",
        kind="note",
    )
    conflicts = gov.check_conflict(
        "budget",
        "5000 EUR",
        agent_id="planner",
        scope=Scope(user="user_123", task="travel"),
    )
    gov_flagged = len(conflicts) >= 1

    return ProofResult(
        failure_mode="Contradiction persistence",
        ungoverned_pass=not naive_silent,
        governed_pass=gov_flagged,
        ungoverned_detail=(
            "Two conflicting budget values coexist; check_conflict returns nothing"
            if naive_silent
            else "Conflict was detected (unexpected)"
        ),
        governed_detail=(
            f"check_conflict flagged {len(conflicts)} conflicting entry(ies)"
            if gov_flagged
            else "No conflict detected (unexpected)"
        ),
    )


def prove_provenance_collapse() -> ProofResult:
    """Full write/supersede chain must be reconstructable with agent+evidence."""
    # --- Ungoverned: no audit trail ---
    naive = UngovernedStore()
    naive.write(key="user_location", value="Berlin", agent_id="researcher")
    naive.write(key="user_location", value="Hamburg", agent_id="researcher")
    naive_audit = naive.audit_log("user_location")
    naive_no_trail = len(naive_audit) == 0

    # --- Governed ---
    gov = GovernedMemoryStore()
    _register_agents(gov)
    scope = Scope(user="user_123", task="travel", namespace="research")
    first = gov.write(
        agent_id="researcher",
        key="user_location",
        value="Berlin",
        scope=scope,
        authority="user_stated",
        provenance_source="turn 5: original city",
        kind="fact",
    )
    gov.supersede(
        entry_id=first.id,
        new_value="Hamburg",
        agent_id="researcher",
        reason="user moved",
        evidence="turn 50: relocation",
    )
    log = gov.audit_log(
        "user_location",
        agent_id="researcher",
        scope=Scope(user="user_123", task="travel"),
    )
    gov_trail = (
        len(log) == 2
        and log[0].provenance.agent_id == "researcher"
        and log[0].value == "Berlin"
        and log[1].value == "Hamburg"
        and "user moved" in log[1].provenance.evidence_spans[0]
    )

    return ProofResult(
        failure_mode="Provenance collapse",
        ungoverned_pass=not naive_no_trail,
        governed_pass=gov_trail,
        ungoverned_detail=(
            "audit_log returns empty — no agent/evidence chain"
            if naive_no_trail
            else f"Unexpected audit data: {len(naive_audit)} entries"
        ),
        governed_detail=(
            f"audit_log chain: "
            + " → ".join(
                f"{e.state.value}:{e.value!r}(agent={e.provenance.agent_id})"
                for e in log
            )
            if gov_trail
            else f"Incomplete chain ({len(log)} entries)"
        ),
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_all_proofs() -> list[ProofResult]:
    return [
        prove_unauthorized_leakage(),
        prove_stale_propagation(),
        prove_contradiction_persistence(),
        prove_provenance_collapse(),
    ]


def print_report(results: list[ProofResult]) -> None:
    width = 72
    print("=" * width)
    print("GOVMEM IDEA PROOF — Comparative Validation")
    print("Thesis: governed shared memory prevents four multi-agent failure modes")
    print("Reference: ")
    print("=" * width)
    print()

    all_ok = True
    for r in results:
        proof_status = "PROVEN" if r.proof_ok else "NOT PROVEN"
        if not r.proof_ok:
            all_ok = False

        print(f"## {r.failure_mode}")
        print()
        print(f"| Store       | Verdict | Detail |")
        print(f"|-------------|---------|--------|")
        print(f"| Ungoverned  | {r.ungoverned_verdict:7} | {r.ungoverned_detail} |")
        print(f"| Governed    | {r.governed_verdict:7} | {r.governed_detail} |")
        print(f"| Proof       | {proof_status:7} | ungoverned must FAIL, governed must PASS |")
        print()

    print("=" * width)
    if all_ok:
        print("RESULT: ALL 4 FAILURE MODES PROVEN — ungoverned FAIL, governed PASS")
    else:
        print("RESULT: PROOF INCOMPLETE — see failures above")
    print("=" * width)


def main() -> int:
    results = run_all_proofs()
    print_report(results)
    all_ok = all(r.proof_ok for r in results)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
