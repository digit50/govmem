# govmem

Governed shared memory for multi-agent LLM systems. Every entry carries a governance envelope; the store enforces scope, provenance, and supersession on every read and write. Pure data infrastructure — no LLM, no per-turn inference cost.

## Clone

```bash
git clone https://github.com/digit50/govmem.git
cd govmem
```

## Install (editable)

```bash
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
read_scope = Scope(user="user_123", task="travel")
conflicts = store.check_conflict(
    "user_location", "Paris", agent_id="researcher", scope=read_scope
)

updated = store.supersede(
    entry_id=entry.id,
    new_value="Hamburg",
    agent_id="researcher",
    reason="user moved",
    evidence="turn 50: 'I just moved'",
)

log = store.audit_log("user_location", agent_id="researcher", scope=read_scope)
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

Simulated in-process workflow (no LLM):

```bash
python examples/multi_agent_demo.py
```

**Real multi-agent LLM demo** (Ollama + GPU when available):

```bash
docker context use default   # required when Docker Desktop context has no GPU
cd docker && docker compose up --build
```

See [`docker/README.md`](docker/README.md) for GPU setup, model options, and troubleshooting.

**Host run** (Ollama already on localhost):

```bash
ollama pull qwen2.5:0.5b
OLLAMA_HOST=http://127.0.0.1:11434 python examples/llm_multi_agent_demo.py
```

## Tests

```bash
python -m pytest tests/ -v
```

## Prior art

Closest prior art is [MemClaw](https://github.com/caura-ai/caura-memclaw) — they ship governed memory as a hosted REST service with LLM enrichment on every write; govmem ships it as an in-process Python library with structural enforcement and zero inference cost. Also related: [CMGL](https://github.com/kadubon/certified-memory-governance-layer) (governance layer, not the store), Mem0, Graphiti/Zep.

## Examples

See [`examples/multi_agent_demo.py`](examples/multi_agent_demo.py) for a simulated multi-agent scenario (no LLM).

See [`examples/llm_multi_agent_demo.py`](examples/llm_multi_agent_demo.py) for the same scenario with real Ollama LLM agents (Docker or host).

**Idea validation** — comparative proof that governance prevents four failure modes in multi-agent shared memory:

```bash
python examples/prove_the_idea.py   # exits 0 when all four modes proven
```

Report: [`examples/prove_the_idea.md`](examples/prove_the_idea.md)

## Design

See [docs/WRITEUP.md](docs/WRITEUP.md) for framing, trade-offs, and deferred features (SQLite, semantic conflicts, decay policies).
