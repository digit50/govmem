FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ src/
COPY examples/ examples/
COPY docker/wait_for_model.py docker/wait_for_model.py

RUN pip install --no-cache-dir -e .

ENV OLLAMA_HOST=http://ollama:11434
ENV OLLAMA_MODEL=qwen2.5:0.5b

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "examples/llm_multi_agent_demo.py"]
