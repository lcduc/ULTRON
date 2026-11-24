"""Lets the stack's LiteLLM key (OPENAI_API_KEY in compose/.env, alias "open-webui") use the optional
cloud models cloud-gpt, cloud-claude and cloud-gemini.

The routes themselves are in compose/litellm-config.yaml; each needs its provider key in compose/.env
(OPENAI_CLOUD_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY). Safe to run again. Prints no secrets.

    python scripts/allow-cloud-models.py            # add the cloud models to the key
    python scripts/allow-cloud-models.py --remove   # local models only again
"""

import json
import sys
import urllib.request
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / "compose" / ".env"
GATEWAY = "http://127.0.0.1:4000"
LOCAL = ["ultron", "ultron-think", "ultron-agent"]
CLOUD = ["cloud-gpt", "cloud-claude", "cloud-gemini"]
OLD = ["openai/*", "anthropic/*", "gemini/*"]  # removed: they flood the model picker


def env() -> dict:
    out = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def call(method, path, master, body=None):
    req = urllib.request.Request(GATEWAY + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {master}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    e = env()
    key, master = e.get("OPENAI_API_KEY", ""), e.get("LITELLM_MASTER_KEY", "")
    if not key or not master:
        sys.exit("OPENAI_API_KEY or LITELLM_MASTER_KEY missing in compose/.env")
    info = call("GET", "/key/info?key=" + urllib.request.quote(key), master).get("info", {})
    models = list(info.get("models") or [])
    if not models:
        print("This key may already use every model (empty list); nothing to change.")
        return
    if "--remove" in sys.argv:
        new = [m for m in models if m not in CLOUD + OLD]
    else:
        new = [m for m in models if m not in OLD] + [m for m in CLOUD if m not in models]
    for m in LOCAL:
        if m not in new:
            new.insert(0, m)
    if new == models:
        print("No change. Allowed models:", ", ".join(models))
        return
    call("POST", "/key/update", master, {"key": key, "models": new})
    print("Allowed models now:", ", ".join(new))
    missing = [n for n in ("OPENAI_CLOUD_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY") if not e.get(n)]
    if missing and "--remove" not in sys.argv:
        print("Provider keys not set yet in compose/.env:", ", ".join(missing),
              "-> add them, then: docker compose -p ultron up -d litellm")


if __name__ == "__main__":
    main()
