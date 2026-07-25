FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY demo.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENV PYTHONPATH=/app/govmem_src

ENTRYPOINT ["./entrypoint.sh"]
