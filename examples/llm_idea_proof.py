#!/usr/bin/env python3
"""LLM-layer validation: scope-filtered context vs naive full dump.

Optional companion to prove_the_idea.py. Requires Ollama with a pulled model
(default llama3.2:1b). Skips gracefully when Ollama is unavailable.

Demonstrates that without governance, an LLM planner receives private session
notes in its prompt context; with govmem, scope filtering keeps them out.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from govmem import Authority, GovernedMemoryStore, Scope


def _ollama_host() -> str:
    import os

    return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def _ollama_model() -> str:
    import os

    return os.environ.get("OLLAMA_MODEL", "llama3.2:1b")


def ollama_available() -> bool:
    try:
        req = urllib.request.Request(f"{_ollama_host()}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        models = [m.get("name", "") for m in data.get("models", [])]
        target = _ollama_model()
        return any(target in name or name.startswith(target.split(":")[0]) for name in models)
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def ollama_chat(*, messages: list[dict[str, str]]) -> str:
    payload = json.dumps(
        {"model": _ollama_model(), "messages": messages, "stream": False}
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


@dataclass
class NaiveContext:
    """Flat memory dump — no scope filtering."""

    entries: list[dict[str, Any]]

    def to_prompt_block(self) -> str:
        lines = [f"- {e['key']}={e['value']!r}" for e in self.entries]
        return "\n".join(lines) or "(empty)"


def build_naive_context() -> NaiveContext:
    return NaiveContext(
        entries=[
            {
                "key": "user_location",
                "value": "Berlin",
                "session": None,
            },
            {
                "key": "session_note",
                "value": "User mentioned anxiety about flying — keep private",
                "session": "private_sess",
            },
        ]
    )


def build_governed_context() -> str:
    store = GovernedMemoryStore()
    store.register_agent("researcher", write_kinds=["fact", "note"], scopes=["research"])
    store.register_agent("planner", write_kinds=["plan"], scopes=["planning"])

    store.write(
        agent_id="researcher",
        key="user_location",
        value="Berlin",
        scope=Scope(user="user_123", task="travel", namespace="research"),
        authority=Authority.USER_STATED,
        provenance_source="turn 5",
        kind="fact",
    )
    store.write(
        agent_id="researcher",
        key="session_note",
        value="User mentioned anxiety about flying — keep private",
        scope=Scope(
            user="user_123",
            task="travel",
            session="private_sess",
            namespace="research",
        ),
        authority=Authority.USER_STATED,
        provenance_source="turn 3: private",
        kind="note",
    )

    entries = store.read(
        agent_id="planner",
        scope=Scope(user="user_123", task="travel", session="public_sess"),
    )
    lines = [f"- {e.key}={e.value!r}" for e in entries]
    return "\n".join(lines) or "(empty)"


def ask_planner_llm(memory_block: str, *, label: str) -> dict[str, Any]:
    prompt = (
        "You are a travel planner. Given ONLY the memory below, list every "
        "memory key you can see and whether any mention anxiety or private "
        "health information. Reply JSON only: "
        '{"keys_seen": ["..."], "mentions_anxiety": true|false, "summary": "..."}\n\n'
        f"Memory ({label}):\n{memory_block}"
    )
    raw = ollama_chat(
        messages=[
            {"role": "system", "content": "Analyze memory context. JSON only."},
            {"role": "user", "content": prompt},
        ]
    )
    start = raw.find("{")
    end = raw.rfind("}")
    parsed = json.loads(raw[start : end + 1]) if start >= 0 else {}
    return {"raw": raw, "parsed": parsed}


def run_llm_proof() -> int:
    print("=" * 72)
    print("GOVMEM LLM IDEA PROOF — Scope-filtered context vs naive dump")
    print("=" * 72)
    print()

    if not ollama_available():
        print("SKIP: Ollama not reachable or model not pulled.")
        print(f"  Host:  {_ollama_host()}")
        print(f"  Model: {_ollama_model()}")
        print("  Pull model: ollama pull llama3.2:1b")
        print("  Or run: cd docker && docker compose up --build")
        return 0

    naive_block = build_naive_context().to_prompt_block()
    gov_block = build_governed_context()

    print("--- Ungoverned context (full dump to LLM) ---")
    print(naive_block)
    print()
    naive_result = ask_planner_llm(naive_block, label="ungoverned")
    naive_anxiety = naive_result["parsed"].get("mentions_anxiety", False)
    print(f"LLM mentions_anxiety: {naive_anxiety}")
    print(f"LLM keys_seen: {naive_result['parsed'].get('keys_seen', [])}")
    print()

    print("--- Governed context (scope-filtered via govmem.read) ---")
    print(gov_block)
    print()
    gov_result = ask_planner_llm(gov_block, label="governed")
    gov_anxiety = gov_result["parsed"].get("mentions_anxiety", False)
    print(f"LLM mentions_anxiety: {gov_anxiety}")
    print(f"LLM keys_seen: {gov_result['parsed'].get('keys_seen', [])}")
    print()

    ungoverned_fail = naive_anxiety is True
    governed_pass = gov_anxiety is False and "session_note" not in str(
        gov_result["parsed"].get("keys_seen", [])
    )

    print("=" * 72)
    print(f"Ungoverned leakage: {'FAIL (LLM saw private data)' if ungoverned_fail else 'unexpected PASS'}")
    print(f"Governed isolation: {'PASS (private data filtered)' if governed_pass else 'unexpected FAIL'}")
    print("=" * 72)

    return 0 if (ungoverned_fail and governed_pass) else 1


def main() -> int:
    try:
        return run_llm_proof()
    except urllib.error.URLError as exc:
        print(f"Ollama error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
