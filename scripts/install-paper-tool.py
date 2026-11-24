"""Install or update the Paper Reader tool in Open WebUI and attach it to the ultron models.

Usage: python scripts/install-paper-tool.py [--url http://127.0.0.1:3000]
Reads ULTRON_API_KEY and PAPER_QUEUE_KEY from the environment or compose/.env (never printed).
Safe to run again: it creates or updates the tool, sets its valves, and adds it to each model
only if it is not there yet.
"""

import argparse
import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TOOL_ID = "paper_reader"
MODELS = ["ultron", "ultron-think", "ultron-agent"]


def env_value(name):
    if os.environ.get(name):
        return os.environ[name]
    try:
        m = re.search(rf"^{name}=(.*)$", (ROOT / "compose" / ".env").read_text(encoding="utf-8"), re.M)
        return m.group(1).strip() if m else ""
    except OSError:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:3000", help="Open WebUI address")
    args = ap.parse_args()
    key, queue_key = env_value("ULTRON_API_KEY"), env_value("PAPER_QUEUE_KEY")
    if not key:
        sys.exit("ULTRON_API_KEY not found (environment or compose/.env).")
    base = args.url.rstrip("/")
    H = {"Authorization": f"Bearer {key}"}

    def api(method, path, body=None, ok_404=False):
        r = requests.request(method, base + path, json=body, headers=H, timeout=30)
        if ok_404 and r.status_code == 404:
            return None
        if r.status_code >= 400:
            sys.exit(f"{method} {path} failed: {r.status_code} {r.text[:200]}")
        return r.json() if r.content else None

    content = (ROOT / "tools" / "paper_reader.py").read_text(encoding="utf-8")
    form = {"id": TOOL_ID, "name": "Paper Reader", "content": content,
            "meta": {"description": "Queue an arXiv or PDF link for a deep-read report."}}
    existing = api("GET", f"/api/v1/tools/id/{TOOL_ID}", ok_404=True)
    if existing is None:
        api("POST", "/api/v1/tools/create", {**form, "access_grants": []})
        print(f"tool {TOOL_ID}: created")
    elif existing.get("content") != content:
        api("POST", f"/api/v1/tools/id/{TOOL_ID}/update", {**form, "access_grants": existing.get("access_grants") or []})
        print(f"tool {TOOL_ID}: updated")
    else:
        print(f"tool {TOOL_ID}: already up to date")

    if queue_key:
        valves = api("GET", f"/api/v1/tools/id/{TOOL_ID}/valves") or {}
        want = {**valves, "queue_url": valves.get("queue_url") or "http://paper-digest:8095/queue", "queue_key": queue_key}
        if want != valves:
            api("POST", f"/api/v1/tools/id/{TOOL_ID}/valves/update", want)
            print("valves: queue_key set")
        else:
            print("valves: already set")
    else:
        print("valves: PAPER_QUEUE_KEY is empty in compose/.env; set it, then run this again")

    for mid in MODELS:
        m = api("GET", f"/api/v1/models/model?id={mid}", ok_404=True)
        if not m:
            print(f"model {mid}: no settings entry found; skipped")
            continue
        meta = m.get("meta") or {}
        ids = list(meta.get("toolIds") or [])
        if TOOL_ID in ids:
            print(f"model {mid}: already has the tool")
            continue
        meta["toolIds"] = ids + [TOOL_ID]
        api("POST", "/api/v1/models/model/update",
            {"id": m["id"], "base_model_id": m.get("base_model_id"), "name": m["name"], "meta": meta,
             "params": m.get("params") or {}, "access_grants": m.get("access_grants"),
             "is_active": m.get("is_active", True)})
        print(f"model {mid}: tool attached")


if __name__ == "__main__":
    main()
