# govmem

Governed shared memory for multi-agent LLM systems. Every entry carries a governance envelope; the store enforces scope, provenance, and supersession on every read and write. Pure data infrastructure — no LLM, no per-turn inference cost.

## Install (editable)

```bash
cd projects/govmem
python -m pip install -e ".[dev]"
```

## Quick start

```python
from govmem import GovernedMemoryStore, Scope

store = GovernedMemoryStore()

store.register_agent("researcher", write_kinds=["fact", "hypothesis"], scopes=["research"])
store.register_agent("planner", write_kinds=["plan"], scopes=["planning"])

scope = Scope(user="user_123", task="travel", namespace="research")

entry = store.write(
    agent_id="researcher",
    key="user_location",
    value="Berlin",
    scope=scope,
    authority="user_stated",
    provenance_source="turn 5: 'I live in Berlin'",
    mutability="revisable",
    kind="fact",
)

entries = store.read(agent_id="planner", scope=Scope(user="user_123", task="travel"))
conflicts = store.check_conflict("user_location", "Paris")

updated = store.supersede(
    entry_id=entry.id,
    new_value="Hamburg",
    agent_id="researcher",
    reason="user moved",
    evidence="turn 50: 'I just moved'",
)

log = store.audit_log(key="user_location")
```

## Operations

| Operation | Purpose |
|-----------|---------|
| `write` | Create a governed entry (auto-supersedes revisable duplicates in the same scope) |
| `read` | Scope-filtered retrieval; active entries only by default |
| `supersede` | Replace an entry without hard-deleting; links provenance chain |
| `check_conflict` | Structural conflict detection (same key, different active value) |
| `audit_log` | Full supersession history for a key |

## Governance envelope

Each entry includes:

- **scope** — `{user, task, session, namespace}` for leakage prevention
- **authority** — `user_stated`, `agent_inferred`, `system`, or `policy`
- **mutability** — `revisable`, `supersede_only`, `locked`, or `decaying`
- **provenance** — agent, source turn, evidence spans, timestamp
- **state** — `active`, `superseded`, or `quarantined`

## Agent registry

Agents declare permitted `write_kinds` and scope `namespace` labels. Writes are rejected when an agent exceeds its authority. Reads require registration but are filtered by scope matching, not write scopes.

## Demo

```bash
PYTHONPATH=src python examples/multi_agent_demo.py
```

## Tests

```bash
python -m pytest tests/ -v
```

## Design

See [DECISIONS.md](DECISIONS.md) for framing, trade-offs, and deferred features (SQLite, semantic conflicts, decay policies).
