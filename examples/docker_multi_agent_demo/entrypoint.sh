#!/bin/bash
set -euo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2:1b}"

echo "=== govmem Docker multi-agent demo ==="
echo "Ollama host: ${OLLAMA_HOST}"
echo "Model: ${OLLAMA_MODEL}"
echo

echo "[setup] Waiting for Ollama API..."
for i in $(seq 1 60); do
  if curl -sf "${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
    echo "[setup] Ollama is ready."
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "[setup] ERROR: Ollama did not become ready in time." >&2
    exit 1
  fi
  sleep 2
done

echo "[setup] Pulling model ${OLLAMA_MODEL} (first run may take several minutes)..."
pull_ok=0
for attempt in 1 2 3; do
  if curl -sf --max-time 600 "${OLLAMA_HOST}/api/pull" -d "{\"name\":\"${OLLAMA_MODEL}\"}"; then
    pull_ok=1
    break
  fi
  echo "[setup] Pull attempt ${attempt} failed, retrying..." >&2
  sleep 5
done
if [ "$pull_ok" -ne 1 ]; then
  echo "[setup] ERROR: model pull failed after 3 attempts." >&2
  exit 1
fi

echo "[setup] Warming up model (first inference loads weights into GPU/CPU)..."
if ! curl -sf --max-time 300 "${OLLAMA_HOST}/api/generate" \
  -d "{\"model\":\"${OLLAMA_MODEL}\",\"prompt\":\"ok\",\"stream\":false}" >/dev/null; then
  echo "[setup] ERROR: model warmup failed." >&2
  exit 1
fi
echo "[setup] Model ready."
echo

exec python demo.py
