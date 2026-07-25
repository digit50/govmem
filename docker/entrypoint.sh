#!/bin/sh
set -e

OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:0.5b}"

python /app/docker/wait_for_model.py "${OLLAMA_HOST}" "${OLLAMA_MODEL}"
echo "Running demo..."
exec "$@"
