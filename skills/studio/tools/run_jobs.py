"""Run a list of ComfyUI template jobs one after another through comfy.py (host config).

Usage: python run_jobs.py <jobs.json> [job_id ...]

jobs.json is a list of {"id", "workflow", "params": {...}, "out": "<path relative to the jobs file>"}.
A job whose "out" file already exists is skipped, so the list can be re-run after a failure.
Each finished job gets "<out>.json" beside it with the workflow, params (including the seed used)
and timing. Progress lines go to stdout, one JSON object per job.
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COMFY = os.path.join(HERE, "..", "..", "comfyui", "comfy.py")
HOST_CFG = os.path.join(HERE, "..", "..", "comfyui", "config.host.json")


def main():
    jobs_path = os.path.abspath(sys.argv[1])
    only = set(sys.argv[2:])
    base = os.path.dirname(jobs_path)
    jobs = json.load(open(jobs_path, encoding="utf-8"))
    env = dict(os.environ, COMFY_CONFIG=HOST_CFG)
    for job in jobs:
        if only and job["id"] not in only:
            continue
        out = os.path.join(base, job["out"])
        if os.path.exists(out):
            print(json.dumps({"id": job["id"], "status": "skipped", "out": out}), flush=True)
            continue
        os.makedirs(os.path.dirname(out), exist_ok=True)
        args = [sys.executable, COMFY, "run", job["workflow"]]
        for k, v in job["params"].items():
            if isinstance(v, str) and k in ("image", "audio", "video") and not os.path.isabs(v):
                v = os.path.join(base, v)
            args.append(f"{k}={v}")
        t0 = time.time()
        for attempt in (1, 2):
            p = subprocess.run(args, capture_output=True, text=True, env=env)
            try:
                res = json.loads(p.stdout)
            except Exception:
                res = {"ok": False, "error": "unreadable helper output", "raw": p.stdout[-1500:] + p.stderr[-1500:]}
            if res.get("ok") or attempt == 2:
                break
            print(json.dumps({"id": job["id"], "status": "retrying", "error": res.get("error"), "raw": res.get("raw")}), flush=True)
            time.sleep(20)
        row = {"id": job["id"], "status": "ok" if res.get("ok") else "failed", "seconds": round(time.time() - t0, 1)}
        if res.get("ok") and res.get("files"):
            src = res["files"][0]
            shutil.copyfile(src, out)
            meta = {"workflow": job["workflow"], "params": res.get("params"), "source_file": src,
                    "seconds": row["seconds"], "note": job.get("note", "")}
            json.dump(meta, open(out + ".json", "w", encoding="utf-8"), indent=1)
            row["out"] = out
        else:
            row.update(error=res.get("error"), details=res.get("details"), raw=res.get("raw"))
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
