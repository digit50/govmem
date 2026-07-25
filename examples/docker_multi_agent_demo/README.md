# Docker multi-agent demo (Ollama + govmem)

Two real LLM agents — **researcher** and **planner** — share a `GovernedMemoryStore` backed by a local Ollama model. This is not a stub: both agents call the LLM API to extract facts and generate plans.

## Prerequisites

- Docker Engine with Compose v2
- NVIDIA GPU + drivers (recommended). CPU fallback works but is slower.
- ~2 GB disk for `llama3.2:1b` (default model)

### GPU setup

your machine uses the **default** Docker context for GPU passthrough. If `docker run --gpus all` fails with a CDI error on `desktop-linux`, switch context:

```bash
docker context use default
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```

`/etc/docker/daemon.json` should include the NVIDIA runtime (already configured).

## Quick start

From this directory:

```bash
cd projects/govmem/examples/docker_multi_agent_demo
docker compose up --build
```

First run pulls the Ollama image and downloads the model (~1.3 GB). Subsequent runs are faster.

### Override model (CPU-friendly)

Smaller models run on CPU if GPU is unavailable — remove `gpus: all` from `docker-compose.yml`:

```bash
OLLAMA_MODEL=phi3:mini docker compose up --build
```

## What the demo does

1. **Register agents** — researcher (`fact`/`research` scope) and planner (`plan`/`planning` scope)
2. **Researcher loop** — sends a user travel message to Ollama, parses extracted facts as JSON, writes each to governed memory
3. **Planner loop** — reads scope-filtered memory, asks Ollama for a 2-day itinerary, writes the plan
4. **Governance proofs** (deterministic checks after LLM steps):
   - Scope isolation — planner cannot see `user_999` entries
   - Kind enforcement — planner cannot write `fact` entries
   - Conflict detection — `check_conflict` finds value mismatches
   - Supersede + audit log — location update with full provenance chain

## Expected output (excerpt)

```
[researcher] LLM response (142 chars):
{"facts": [{"key": "user_location", "value": "Berlin"}, ...]}
[researcher] wrote user_location='Berlin' (id=abc12345...)
[planner] read 3 entries in scope user_123/travel:
  - user_location: 'Berlin' [user_stated, ns=research]
[PASS] Scope isolation: planner cannot see user_999 entries
[PASS] Kind enforcement: planner rejected for writing kind='fact'
[PASS] Supersede: user_location -> 'Hamburg'
All governance checks passed. Real LLM agents ran successfully.
```

## Architecture

```
┌─────────────┐     HTTP      ┌──────────────┐
│  demo.py    │──────────────▶│   Ollama     │
│ (researcher │               │ llama3.2:1b  │
│  + planner) │               │  (GPU/CPU)   │
└──────┬──────┘               └──────────────┘
       │
       ▼
 GovernedMemoryStore (in-process, stdlib-only govmem)
```

The demo depends on stdlib HTTP only (`urllib`). govmem itself has zero runtime dependencies.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `no known GPU vendor found` | `docker context use default` |
| Ollama pull timeout | Retry; or set `OLLAMA_MODEL=phi3:mini` |
| JSON parse error from LLM | Re-run; small models occasionally emit malformed JSON |
| Port 11434 in use on host | Ollama is internal-only (no host port); stop conflicting containers if needed |

## Local run (without Docker)

If Ollama is already running on the host:

```bash
cd projects/govmem
OLLAMA_HOST=http://localhost:11434 PYTHONPATH=src \
  python examples/docker_multi_agent_demo/demo.py
```
