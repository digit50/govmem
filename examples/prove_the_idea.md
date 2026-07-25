# GOVMEM Idea Proof — Validation Report

**Date:** 2026-07-25  
**Script:** `examples/prove_the_idea.py`  
**Thesis:** Governed shared memory prevents four failure modes in multi-agent LLM systems.

## Method

Same scenario run twice for each failure mode:

| Agent | Role |
|-------|------|
| Researcher | Writes facts and private session notes |
| Planner | Reads travel-scope context |
| Support | Writes conflicting estimates |

- **Ungoverned:** naive append-only list (`UngovernedStore`) — no scope filtering, supersession, conflict detection, or audit trail.
- **Governed:** `GovernedMemoryStore` with full governance envelope.

**Success criterion:** ungoverned = FAIL, governed = PASS for all four modes. Script exits 0 only when all proofs hold.

## Results

| Failure mode | Ungoverned | Governed | Evidence |
|--------------|------------|----------|----------|
| Unauthorized leakage | **FAIL** | **PASS** | Private session note visible to planner in naive store; filtered out by scope in govmem |
| Stale propagation | **FAIL** | **PASS** | Berlin and Hamburg coexist as active in naive store; only Hamburg active after supersede in govmem |
| Contradiction persistence | **FAIL** | **PASS** | Two conflicting budget values coexist silently in naive store; `check_conflict` flags mismatch in govmem |
| Provenance collapse | **FAIL** | **PASS** | `audit_log` returns empty in naive store; full agent+evidence chain in govmem |

## Full script output

```
========================================================================
GOVMEM IDEA PROOF — Comparative Validation
Thesis: governed shared memory prevents four multi-agent failure modes
========================================================================

## Unauthorized leakage

| Store       | Verdict | Detail |
|-------------|---------|--------|
| Ungoverned  | FAIL    | Planner sees 1 entries including private note |
| Governed    | PASS    | Planner sees 0 entries (private note filtered out) |
| Proof       | PROVEN  | ungoverned must FAIL, governed must PASS |

## Stale propagation

| Store       | Verdict | Detail |
|-------------|---------|--------|
| Ungoverned  | FAIL    | Both Berlin and Hamburg coexist as active (2 entries) |
| Governed    | PASS    | Planner sees active location=['Hamburg'] |
| Proof       | PROVEN  | ungoverned must FAIL, governed must PASS |

## Contradiction persistence

| Store       | Verdict | Detail |
|-------------|---------|--------|
| Ungoverned  | FAIL    | Two conflicting budget values coexist; check_conflict returns nothing |
| Governed    | PASS    | check_conflict flagged 1 conflicting entry(ies) |
| Proof       | PROVEN  | ungoverned must FAIL, governed must PASS |

## Provenance collapse

| Store       | Verdict | Detail |
|-------------|---------|--------|
| Ungoverned  | FAIL    | audit_log returns empty — no agent/evidence chain |
| Governed    | PASS    | audit_log chain: superseded:'Berlin'(agent=researcher) → active:'Hamburg'(agent=researcher) |
| Proof       | PROVEN  | ungoverned must FAIL, governed must PASS |

========================================================================
RESULT: ALL 4 FAILURE MODES PROVEN — ungoverned FAIL, governed PASS
========================================================================
```

## How to reproduce

```bash
python examples/prove_the_idea.py   # exits 0 on success
pytest tests/ -q                    # library tests
```

## Optional LLM layer

`examples/llm_idea_proof.py` extends the leakage proof with real Ollama agents:

- **Ungoverned:** planner LLM receives full memory dump including private session note.
- **Governed:** planner LLM receives only scope-filtered entries from `govmem.read()`.

Requires Ollama with `llama3.2:1b` (or set `OLLAMA_MODEL`). Skips gracefully when unavailable.

```bash
ollama pull llama3.2:1b
python examples/llm_idea_proof.py
```

## Conclusion

All four failure modes from the paper thesis are demonstrated empirically: naive shared memory fails each check; govmem passes each check. Unit tests (51) validate individual store behaviors; this comparative script validates the *idea* — that governance at the store boundary is what prevents the failures, not merely that isolated API calls work.
