# govmem — design notes

## What it is

An in-process Python library for governed shared memory in multi-agent LLM systems. Every entry carries a governance envelope — scope, authority, mutability, provenance — and the store enforces it on every read and write. Stdlib only in v1.

## Stance

Governance belongs in the data layer, not in LLM-side policy prompts. Scope matching, supersession chains, and conflict detection are structural operations with zero inference cost. Teams building multi-agent systems get leakage prevention and audit trails without paying per-turn LLM overhead.

## Delta vs MemClaw (closest prior art)

[MemClaw](https://github.com/caura-ai/caura-memclaw) ships governed fleet memory as a self-hosted REST service with LLM enrichment on every write. govmem ships the same governance semantics — scope enforcement, supersession, audit — as an embeddable in-process library with structural enforcement and no LLM dependency.

## What I'd do differently

- **Persistence first.** v1 is in-memory with a pluggable backend protocol; SQLite should have been phase 1, not phase 2 — without persistence the library is a demo, not infrastructure.
- **Semantic conflict detection deferred correctly, but document the boundary.** Structural conflict (same key, different value) catches obvious contradictions; the README should be clearer about what it won't catch without an LLM.
- **Decay policies stubbed.** `decaying` mutability is stored but not enforced — either implement or remove from the API surface until ready.
