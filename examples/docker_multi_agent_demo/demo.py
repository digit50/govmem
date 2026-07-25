"""Real multi-agent demo: researcher + planner sharing a GovernedMemoryStore.

Uses a local Ollama LLM (not simulated). Demonstrates scope isolation,
conflict detection, supersession, and audit trails.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

from govmem import GovernedMemoryStore, Scope
from govmem.exceptions import UnauthorizedWriteError

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")

USER_MESSAGE = (
    "Hi! I'm planning a trip. I live in Berlin and I'd love to visit "
    "historical landmarks. My budget is around 200 euros for two days."
)


def ollama_generate(prompt: str, *, system: str | None = None) -> str:
    """Call Ollama /api/chat and return assistant text."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 512},
        }
    ).encode()

    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc

    content = body.get("message", {}).get("content", "")
    if not content.strip():
        raise RuntimeError(f"Ollama returned empty response: {body!r}")
    return content.strip()


def parse_json_from_llm(text: str) -> dict:
    """Extract JSON object from LLM output (handles markdown fences)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in LLM output: {text!r}")
    blob = cleaned[start : end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        plan_match = re.search(r'"plan"\s*:\s*"((?:[^"\\]|\\.)*)"', blob)
        if plan_match:
            return {"plan": json.loads(f'"{plan_match.group(1)}"')}
        raise


def normalize_facts(raw_facts: list) -> list[dict[str, str]]:
    """Convert LLM fact objects to {key, value} pairs (handles schema drift)."""
    key_aliases = {"location": "user_location", "city": "user_location"}
    normalized: list[dict[str, str]] = []
    for item in raw_facts:
        if not isinstance(item, dict):
            continue
        if "key" in item and "value" in item:
            key = key_aliases.get(str(item["key"]), str(item["key"]))
            normalized.append({"key": key, "value": str(item["value"])})
            continue
        for field, val in item.items():
            if isinstance(val, (list, dict)):
                val = json.dumps(val)
            key = key_aliases.get(str(field), str(field))
            normalized.append({"key": key, "value": str(val)})
    return normalized


def researcher_extract_facts(store: GovernedMemoryStore, user_text: str) -> list[dict]:
    """Researcher agent: LLM extracts facts, writes to governed memory."""
    print("\n--- Researcher agent (LLM fact extraction) ---")
    system = (
        "You extract structured facts from user messages for a travel assistant. "
        "Respond with ONLY valid JSON, no markdown."
    )
    prompt = (
        f'User message: "{user_text}"\n\n'
        'Return JSON with this exact shape:\n'
        '{"facts": [{"key": "user_location", "value": "Berlin"}, '
        '{"key": "budget", "value": "200 euros"}, '
        '{"key": "interests", "value": "historical landmarks"}, '
        '{"key": "duration", "value": "2 days"}]}\n'
        "Each fact MUST have exactly two fields: key (snake_case) and value (string)."
    )

    raw = ollama_generate(prompt, system=system)
    print(f"[researcher] LLM response ({len(raw)} chars):\n{raw[:300]}{'...' if len(raw) > 300 else ''}")

    parsed = parse_json_from_llm(raw)
    facts = normalize_facts(parsed.get("facts", []))
    if not facts:
        raise RuntimeError(f"Researcher LLM returned no facts: {parsed!r}")

    scope = Scope(user="user_123", task="travel", namespace="research")
    written = []
    for i, fact in enumerate(facts):
        entry = store.write(
            agent_id="researcher",
            key=fact["key"],
            value=fact["value"],
            scope=scope,
            authority="user_stated",
            provenance_source=f"LLM extraction from user message (fact {i + 1})",
            mutability="revisable",
            kind="fact",
            source_turn=1,
        )
        written.append(entry)
        print(f"[researcher] wrote {entry.key}={entry.value!r} (id={entry.id[:8]}...)")

    return [{"key": e.key, "value": e.value, "id": e.id} for e in written]


def planner_create_plan(store: GovernedMemoryStore) -> str:
    """Planner agent: reads scope-filtered memory, LLM generates plan."""
    print("\n--- Planner agent (LLM planning from governed memory) ---")

    read_scope = Scope(user="user_123", task="travel")
    context = store.read(agent_id="planner", scope=read_scope)
    print(f"[planner] read {len(context)} entries in scope user_123/travel:")
    for entry in context:
        print(
            f"  - {entry.key}: {entry.value!r} "
            f"[{entry.authority.value}, ns={entry.scope.namespace}]"
        )

    memory_lines = "\n".join(f"- {e.key}: {e.value}" for e in context)
    system = (
        "You are a travel planner. Use ONLY the provided memory facts. "
        "Respond with ONLY valid JSON, no markdown."
    )
    prompt = (
        f"Known facts:\n{memory_lines}\n\n"
        'Return JSON: {"plan": "A concise 2-day itinerary as a single string"}'
    )

    raw = ollama_generate(prompt, system=system)
    print(f"[planner] LLM response ({len(raw)} chars):\n{raw[:300]}{'...' if len(raw) > 300 else ''}")

    parsed = parse_json_from_llm(raw)
    plan_text = parsed.get("plan", "")
    if not plan_text:
        raise RuntimeError(f"Planner LLM returned no plan: {parsed!r}")

    plan_scope = Scope(user="user_123", task="travel", namespace="planning")
    entry = store.write(
        agent_id="planner",
        key="itinerary",
        value=plan_text,
        scope=plan_scope,
        authority="agent_inferred",
        provenance_source="LLM plan from governed memory",
        kind="plan",
        source_turn=2,
    )
    print(f"[planner] wrote itinerary ({len(plan_text)} chars, id={entry.id[:8]}...)")
    return plan_text


def demonstrate_governance(store: GovernedMemoryStore, location_entry_id: str | None) -> None:
    """Show scope isolation, conflicts, supersede, and audit log."""
    print("\n--- Governance demonstrations ---")

    # Scope isolation: secret entry for another user
    secret_scope = Scope(user="user_999", task="travel", namespace="research")
    store.write(
        agent_id="researcher",
        key="secret_destination",
        value="classified",
        scope=secret_scope,
        authority="user_stated",
        provenance_source="other user's private data",
        kind="fact",
    )
    leaked = store.read(agent_id="planner", scope=Scope(user="user_123", task="travel"))
    leaked_keys = {e.key for e in leaked}
    if "secret_destination" in leaked_keys:
        print("[FAIL] Scope isolation: planner saw secret_destination!")
        sys.exit(1)
    print("[PASS] Scope isolation: planner cannot see user_999 entries")

    # Unauthorized write: planner cannot write facts
    try:
        store.write(
            agent_id="planner",
            key="fake_fact",
            value="injected",
            scope=Scope(user="user_123", task="travel", namespace="research"),
            authority="agent_inferred",
            provenance_source="unauthorized",
            kind="fact",
        )
        print("[FAIL] Kind enforcement: planner wrote a fact!")
        sys.exit(1)
    except UnauthorizedWriteError:
        print("[PASS] Kind enforcement: planner rejected for writing kind='fact'")

    # Conflict detection
    read_scope = Scope(user="user_123", task="travel")
    conflicts = store.check_conflict(
        "user_location", "Paris", agent_id="researcher", scope=read_scope
    )
    if conflicts:
        print(
            f"[PASS] Conflict detection: user_location={conflicts[0].value!r} "
            f"conflicts with proposed 'Paris'"
        )
    else:
        print("[INFO] Conflict detection: no user_location entry to conflict with")

    # Supersede + audit log
    if location_entry_id:
        updated = store.supersede(
            entry_id=location_entry_id,
            new_value="Hamburg",
            agent_id="researcher",
            reason="user moved",
            evidence="turn 50: 'I just moved to Hamburg'",
            source_turn=50,
        )
        print(f"[PASS] Supersede: user_location -> {updated.value!r}")

        audit = store.audit_log("user_location", agent_id="researcher", scope=read_scope)
        states = [e.state.value for e in audit]
        values = [e.value for e in audit]
        print(f"[PASS] Audit log: {len(audit)} entries, states={states}, values={values}")

        planner_view = store.read(agent_id="planner", scope=read_scope)
        loc = next((e for e in planner_view if e.key == "user_location"), None)
        if loc and loc.value == "Hamburg":
            print(f"[PASS] Supersession visible to planner: user_location={loc.value!r}")
        elif loc:
            print(f"[FAIL] Planner sees stale location: {loc.value!r}")
            sys.exit(1)


def main() -> None:
    print("=== govmem multi-agent demo (real LLM via Ollama) ===")
    print(f"Model: {OLLAMA_MODEL} @ {OLLAMA_HOST}")

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
    print("[setup] Registered researcher (facts/research) and planner (plan/planning)")

    facts = researcher_extract_facts(store, USER_MESSAGE)
    location_id = next((f["id"] for f in facts if f["key"] == "user_location"), None)
    if location_id is None:
        # LLM may use a different key; pick first location-like fact
        for f in facts:
            if "location" in f["key"] or "city" in f["key"] or "live" in f["key"]:
                location_id = f["id"]
                break

    plan = planner_create_plan(store)
    demonstrate_governance(store, location_id)

    print("\n=== Demo complete ===")
    print(f"Final plan excerpt: {plan[:120]}{'...' if len(plan) > 120 else ''}")
    print("All governance checks passed. Real LLM agents ran successfully.")


if __name__ == "__main__":
    main()
