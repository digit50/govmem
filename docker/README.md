# Docker LLM demo

Real multi-agent demo: Ollama (GPU) + govmem in Docker Compose.

## Prerequisites

- Docker Engine with NVIDIA Container Toolkit
- NVIDIA GPU driver (`nvidia-smi` works on host)
- **Use the native Docker context**, not Docker Desktop:

```bash
docker context use default
docker run --rm --runtime=nvidia nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```

Docker Desktop (`desktop-linux` context) may not expose GPU — CDI can report "no known GPU vendor". Switch to `default` before running the demo.

## Quick start

```bash
cd docker
docker compose up --build
```

First run pulls `llama3.2:1b` (~1.3 GB) into a named volume. Subsequent runs reuse cached weights.

## Services

| Service | Role |
|---------|------|
| `ollama` | Local LLM server, `runtime: nvidia` for GPU inference |
| `demo` | Python 3.12 + govmem; runs `examples/llm_multi_agent_demo.py` |

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `OLLAMA_HOST` | `http://ollama:11434` | Ollama API base URL |
| `OLLAMA_MODEL` | `qwen2.5:0.5b` | Model tag to pull and use |

Default model is small (0.5B) for fast demo runs. Override:

```bash
OLLAMA_MODEL=llama3.2:1b docker compose up --build
```

### Registry pull failures

If `ollama pull` returns `EOF` from the container, mount a volume that already contains models:

```yaml
# docker-compose.yml — replace ollama_models with an external volume
volumes:
  - my-ollama-models:/root/.ollama   # external: true under volumes:
```

Or run Ollama on the host and point the demo at it (see CPU fallback below).

## CPU fallback (no GPU in Docker)

If GPU passthrough fails, run Ollama on the host and the demo in Docker against it:

```bash
# Install Ollama on host (snap or curl install script)
ollama serve &
ollama pull llama3.2:1b

# Demo container talks to host Ollama
OLLAMA_HOST=http://host.docker.internal:11434 docker compose run --no-deps demo
```

Or run everything on host without Docker:

```bash
ollama pull llama3.2:1b
OLLAMA_HOST=http://127.0.0.1:11434 PYTHONPATH=src python examples/llm_multi_agent_demo.py
```

CPU inference is slower but proves the same governance flow.

## What the demo proves

1. **Researcher agent** — LLM extracts city from user text; writes `user_location` with scope, authority, provenance
2. **Planner agent** — reads scope-filtered memory; LLM drafts itinerary using governed facts
3. **Conflict detection** — structural check flags Paris vs active Berlin
4. **Supersession** — explicit supersede when user moves to Hamburg
5. **Audit log** — full Berlin → Hamburg chain with evidence spans

govmem library code is unchanged; LLM calls live only in the demo script.
