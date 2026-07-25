"""Wait for Ollama and ensure model is pulled (used by Docker entrypoint)."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request


def wait_for_ollama(host: str, *, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{host}/api/tags", timeout=5):
                return
        except urllib.error.URLError:
            time.sleep(2)
    raise TimeoutError(f"Ollama not reachable at {host}")


def model_installed(host: str, model: str) -> bool:
    with urllib.request.urlopen(f"{host}/api/tags", timeout=10) as resp:
        tags = json.loads(resp.read())
    names = {m["name"] for m in tags.get("models", [])}
    return model in names or f"{model}:latest" in names


def pull_model(host: str, model: str) -> None:
    payload = json.dumps({"name": model}).encode()
    req = urllib.request.Request(
        f"{host}/api/pull",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        for line in resp:
            status = json.loads(line)
            if status.get("status") == "success":
                return
            if err := status.get("error"):
                raise RuntimeError(f"Model pull failed: {err}")
    raise RuntimeError("Model pull ended without success status")


def main() -> None:
    host = sys.argv[1].rstrip("/")
    model = sys.argv[2]
    wait_for_ollama(host)
    if not model_installed(host, model):
        print(f"Pulling {model}...", flush=True)
        pull_model(host, model)
    print(f"Model ready: {model}", flush=True)


if __name__ == "__main__":
    main()
