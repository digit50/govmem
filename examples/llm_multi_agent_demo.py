"""Multi-agent LLM demo: real Ollama inference + governed shared memory.

Researcher and planner agents share one GovernedMemoryStore. LLM calls drive
reasoning; govmem enforces scope, provenance, and supersession structurally.

Run locally (Ollama on host):
    OLLAMA_HOST=http://127.0.0.1:11434 python examples/llm_multi_agent_demo.py

Run in Docker:
    cd docker && docker compose up --build
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from govmem import Authority, GovernedMemoryStore, Scope


def _ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def _ollama_model() -> str:
    return os.environ.get("OLLAMA_MODEL", "qwen2.5:0.5b")


def ollama_chat(*, messages: list[dict[str, str]], model: str | None = None) -> str:
    """Call Ollama /api/chat; returns assistant message content."""
    payload = json.dumps(
        {"model": model or _ollama_model(), "messages": messages, "stream": False}
    ).encode()
    req = urllib.request.Request(
        f"{_ollama_host()}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read())
    return body["message"]["content"]


def parse_json_object(text: str) -> dict[str, Any]:
    """Extract first JSON object from LLM output."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in LLM response: {text!r}")
    return json.loads(text[start : end + 1])


@dataclass
class ResearcherAgent:
    store: GovernedMemoryStore
    agent_id: str = "researcher"
    research_scope: Scope | None = None

    def __post_init__(self) -> None:
        if self.research_scope is None:
            self.research_scope = Scope(
                user="user_123", task="travel", namespace="research"
            )

    def extract_city(self, message: str) -> dict[str, str]:
        """Use LLM to extract city from user message (no store write)."""
        prompt = (
            "Extract the user's city from the message. "
            'Reply with JSON only: {"city": "<city name>"}. '
            f"Message: {message}"
        )
        raw = ollama_chat(
            messages=[
                {"role": "system", "content": "You extract structured facts. JSON only."},
                {"role": "user", "content": prompt},
            ]
        )
        parsed = parse_json_object(raw)
        return {"llm_raw": raw, "city": str(parsed["city"])}

    def write_location(self, city: str, *, message: str, turn: int) -> Any:
        """Write location fact to governed memory."""
        return self.store.write(
            agent_id=self.agent_id,
            key="user_location",
            value=city,
            scope=self.research_scope,
            authority=Authority.USER_STATED,
            provenance_source=f"turn {turn}: {message!r}",
            mutability="revisable",
            kind="fact",
            source_turn=turn,
        )

    def supersede_location(
        self, entry_id: str, city: str, *, message: str, turn: int
    ) -> Any:
        """Supersede existing location with new city and explicit reason."""
        return self.store.supersede(
            entry_id=entry_id,
            new_value=city,
            agent_id=self.agent_id,
            reason="user moved",
            evidence=f"turn {turn}: {message!r}",
            source_turn=turn,
        )

    def ingest_user_message(self, message: str, *, turn: int) -> dict[str, Any]:
        """Use LLM to extract a location fact, then write to governed memory."""
        extracted = self.extract_city(message)
        entry = self.write_location(
            extracted["city"], message=message, turn=turn
        )
        return {"llm_raw": extracted["llm_raw"], "entry": entry}


@dataclass
class PlannerAgent:
    store: GovernedMemoryStore
    agent_id: str = "planner"
    read_scope: Scope | None = None
    plan_scope: Scope | None = None

    def __post_init__(self) -> None:
        if self.read_scope is None:
            self.read_scope = Scope(user="user_123", task="travel")
        if self.plan_scope is None:
            self.plan_scope = Scope(
                user="user_123", task="travel", namespace="planning"
            )

    def read_context(self) -> list[Any]:
        return self.store.read(agent_id=self.agent_id, scope=self.read_scope)

    def create_plan(self, *, turn: int) -> dict[str, Any]:
        """Read scope-filtered memory, ask LLM for a one-day itinerary."""
        context = self.read_context()
        memory_lines = [
            f"- {e.key}={e.value!r} (authority={e.authority.value}, "
            f"from {e.provenance.agent_id})"
            for e in context
        ]
        memory_block = "\n".join(memory_lines) or "(no memory yet)"

        prompt = (
            "Given the governed memory below, write a one-day travel itinerary "
            "for the user's city. Reply with JSON only: "
            '{"itinerary": "<single sentence plan>"}.\n\n'
            f"Memory:\n{memory_block}"
        )
        raw = ollama_chat(
            messages=[
                {
                    "role": "system",
                    "content": "You are a travel planner using governed shared memory.",
                },
                {"role": "user", "content": prompt},
            ]
        )
        parsed = parse_json_object(raw)
        itinerary = str(parsed["itinerary"])

        entry = self.store.write(
            agent_id=self.agent_id,
            key="itinerary",
            value=itinerary,
            scope=self.plan_scope,
            authority=Authority.AGENT_INFERRED,
            provenance_source=f"turn {turn}: planner draft from governed memory",
            kind="plan",
            source_turn=turn,
        )
        return {"llm_raw": raw, "entry": entry, "context_count": len(context)}


def run_demo() -> None:
    store = GovernedMemoryStore()
    store.register_agent(
        "researcher", write_kinds=["fact", "hypothesis"], scopes=["research"]
    )
    store.register_agent("planner", write_kinds=["plan"], scopes=["planning"])

    researcher = ResearcherAgent(store=store)
    planner = PlannerAgent(store=store)
    read_scope = Scope(user="user_123", task="travel")

    print("=== govmem LLM multi-agent demo ===")
    print(f"Ollama: {_ollama_host()}  model: {_ollama_model()}\n")

    # 1. Researcher writes Berlin with provenance
    print("--- Step 1: Researcher ingests user message ---")
    r1 = researcher.ingest_user_message("I live in Berlin", turn=5)
    loc = r1["entry"]
    print(f"LLM extracted city via governed write: {loc.key}={loc.value!r}")
    print(f"  provenance: {loc.provenance.evidence_spans[0]!r}")
    print(f"  authority: {loc.authority.value}, kind: {loc.kind}\n")

    # 2. Planner reads scope-filtered memory and plans
    print("--- Step 2: Planner reads memory and creates plan ---")
    p1 = planner.create_plan(turn=6)
    print(f"Planner saw {p1['context_count']} entries in travel scope")
    for entry in planner.read_context():
        print(f"  - {entry.key}: {entry.value!r} [{entry.authority.value}]")
    print(f"Plan: {p1['entry'].value!r}\n")

    # 3. Conflict detection
    print("--- Step 3: Conflict detection (Paris vs active Berlin) ---")
    conflicts = store.check_conflict(
        "user_location", "Paris", agent_id="researcher", scope=read_scope
    )
    if conflicts:
        print(f"Conflict detected: proposed Paris vs active {conflicts[0].value!r}")
    else:
        print("No conflict (unexpected)")
    print()

    # 4. Supersede when user moves to Hamburg
    print("--- Step 4: User moves — supersede Berlin -> Hamburg ---")
    move_msg = "I just moved to Hamburg"
    extracted = researcher.extract_city(move_msg)
    updated = researcher.supersede_location(
        loc.id, extracted["city"], message=move_msg, turn=50
    )
    print(f"Superseded location -> {updated.value!r}")
    after = planner.read_context()
    location_after = next(e.value for e in after if e.key == "user_location")
    print(f"Planner now sees user_location={location_after!r}\n")

    # 5. Audit log
    print("--- Step 5: Audit log (full supersession chain) ---")
    log = store.audit_log("user_location", agent_id="researcher", scope=read_scope)
    print(f"Audit log ({len(log)} entries):")
    for entry in log:
        print(
            f"  - {entry.state.value}: {entry.value!r} "
            f"(agent={entry.provenance.agent_id}, "
            f"evidence={entry.provenance.evidence_spans[0]!r})"
        )

    print("\n=== Demo complete: governance enforced, LLM used for reasoning only ===")


def main() -> None:
    try:
        run_demo()
    except urllib.error.URLError as exc:
        print(
            f"Cannot reach Ollama at {_ollama_host()}: {exc}\n"
            "Start Ollama locally or run: cd docker && docker compose up --build",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
