#!/usr/bin/env python3
"""ComfyUI helper for the agent sandbox. Standard library only.

  comfy.py status                       is ComfyUI up, queue length, GPU memory
  comfy.py models [folder]              list model files (checkpoints, loras, unet, vae, ...)
  comfy.py workflows                    list workflow templates and their parameters
  comfy.py run <workflow> k=v [k=v ...] run a template; hands the GPU over and back
  comfy.py upload <file>                copy an image from the workspace into ComfyUI's input folder

`run` unloads the chat model, queues the job, waits, saves outputs to
/home/user/workspace/outputs/, then frees ComfyUI's VRAM. The chat model
reloads by itself afterwards. Output is JSON on stdout.
"""
import json
import mimetypes
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
COMFY = CFG["comfy_url"].rstrip("/")
BROKER = CFG["broker_url"].rstrip("/")
BROKER_HOST = CFG["broker_host_header"]
OUT_DIR = CFG.get("output_dir", "/home/user/workspace/outputs")
WF_DIR = os.path.join(HERE, "workflows")


def die(msg, **extra):
    print(json.dumps({"ok": False, "error": msg, **extra}, indent=1))
    sys.exit(1)


def http(url, data=None, headers=None, timeout=30, raw=False):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return body if raw else (json.loads(body) if body else {})


def comfy(path, payload=None, timeout=30, raw=False):
    data = json.dumps(payload).encode() if payload is not None else None
    return http(COMFY + path, data, {"Content-Type": "application/json"} if data else None, timeout, raw)


def broker(path, post=False):
    try:
        return http(BROKER + path, b"" if post else None, {"Host": BROKER_HOST}, 120)
    except Exception as e:
        return {"ok": False, "error": f"GPU broker unreachable: {e}"}


def comfy_up():
    try:
        return comfy("/system_stats", timeout=5)
    except Exception:
        return None


def need_comfy():
    stats = comfy_up()
    if not stats:
        die(f"ComfyUI is not reachable at {COMFY}. Ask the user to start ComfyUI Desktop and launch the instance "
            "(port 8188). Do not retry in a loop.")
    return stats


def load_templates():
    out = {}
    for f in sorted(os.listdir(WF_DIR)):
        if f.endswith(".json"):
            out[f[:-5]] = json.load(open(os.path.join(WF_DIR, f)))
    return out


def cmd_status():
    stats = comfy_up()
    res = {"ok": True, "comfyui_reachable": bool(stats), "comfy_url": COMFY, "gpu_broker": broker("/status")}
    if stats:
        q = comfy("/queue")
        dev = stats["devices"][0]
        res.update(comfyui_version=stats["system"].get("comfyui_version"),
                   queue_running=len(q.get("queue_running", [])), queue_pending=len(q.get("queue_pending", [])),
                   vram_free_gb=round(dev["vram_free"] / 2**30, 1), vram_total_gb=round(dev["vram_total"] / 2**30, 1))
    print(json.dumps(res, indent=1))


def cmd_models(folder=None):
    need_comfy()
    folders = [folder] if folder else ["checkpoints", "diffusion_models", "unet", "loras", "vae", "text_encoders", "controlnet", "upscale_models"]
    res = {}
    for f in folders:
        try:
            res[f] = comfy("/models/" + urllib.parse.quote(f))
        except urllib.error.HTTPError:
            res[f] = []
    print(json.dumps({"ok": True, "models": res}, indent=1))


def cmd_workflows():
    res = {}
    for name, t in load_templates().items():
        res[name] = {"description": t.get("description", ""),
                     "params": {k: {x: v[x] for x in v if x not in ("node", "input")} for k, v in t["params"].items()}}
    print(json.dumps({"ok": True, "workflows": res}, indent=1))


def upload(path):
    if not os.path.isfile(path):
        die(f"file not found: {path}")
    name = os.path.basename(path)
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode() + open(path, "rb").read() + (
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n").encode()
    r = http(COMFY + "/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}, 120)
    return r.get("name", name)


def cast(name, spec, value):
    t = spec.get("type", "str")
    try:
        if t == "int":
            value = int(value)
        elif t == "float":
            value = float(value)
    except ValueError:
        die(f"parameter '{name}' must be {t}, got '{value}'")
    if t in ("int", "float"):
        if "min" in spec and value < spec["min"] or "max" in spec and value > spec["max"]:
            die(f"parameter '{name}' must be between {spec.get('min')} and {spec.get('max')}, got {value}")
    if "choices" in spec and value not in spec["choices"]:
        die(f"parameter '{name}' must be one of {spec['choices']}")
    if "model_folder" in spec:
        files = comfy("/models/" + spec["model_folder"])
        if value not in files:
            die(f"'{value}' is not in ComfyUI's {spec['model_folder']} folder", available=files)
    return value


def cmd_run(name, pairs):
    templates = load_templates()
    if name not in templates:
        die(f"unknown workflow '{name}'", available=list(templates))
    t = templates[name]
    given = {}
    for p in pairs:
        if "=" not in p:
            die(f"parameters must be key=value, got '{p}'")
        k, v = p.split("=", 1)
        if k not in t["params"]:
            die(f"workflow '{name}' has no parameter '{k}'", params=list(t["params"]))
        given[k] = v
    missing = [k for k, s in t["params"].items() if s.get("required") and k not in given]
    if missing:
        die(f"missing required parameters: {missing}")

    need_comfy()   # fail before touching the GPU if ComfyUI is down
    graph = json.loads(json.dumps(t["graph"]))
    used = {}
    for k, spec in t["params"].items():
        if k in given:
            val = cast(k, spec, given[k])
            if spec.get("type") == "image":
                val = upload(val if os.path.isabs(val) else os.path.join("/home/user/workspace", val))
        elif spec.get("type") == "seed":
            val = random.randint(1, 2**31 - 1)
        else:
            continue
        if spec.get("type") == "seed":
            val = int(val)
        graph[spec["node"]]["inputs"][spec["input"]] = val
        used[k] = val

    timeout = int(t.get("timeout_seconds", 900))
    released = broker("/release", post=True)
    result = {"ok": False, "workflow": name, "params": used}
    try:
        try:
            q = comfy("/prompt", {"prompt": graph, "client_id": uuid.uuid4().hex}, timeout=60)
        except urllib.error.HTTPError as e:
            result["error"] = "ComfyUI rejected the workflow"
            result["details"] = json.loads(e.read() or b"{}")
            return result
        pid = q["prompt_id"]
        start = time.time()
        hist = None
        while time.time() - start < timeout:
            h = comfy("/history/" + pid)
            if pid in h:
                hist = h[pid]
                break
            time.sleep(2)
        if hist is None:
            comfy("/interrupt", {})
            result["error"] = f"timed out after {timeout} s; job interrupted"
            return result
        status = hist.get("status", {})
        if status.get("status_str") == "error":
            msgs = [m[1] for m in status.get("messages", []) if m[0] == "execution_error"]
            result["error"] = "ComfyUI execution error"
            result["details"] = [{k: m.get(k) for k in ("node_type", "exception_message")} for m in msgs]
            return result
        os.makedirs(OUT_DIR, exist_ok=True)
        files = []
        for node_out in hist.get("outputs", {}).values():
            for kind in ("images", "gifs", "videos"):
                for item in node_out.get(kind, []):
                    if item.get("type") == "temp":
                        continue
                    qs = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")})
                    dest = os.path.join(OUT_DIR, item["filename"])
                    open(dest, "wb").write(comfy("/view?" + qs, timeout=120, raw=True))
                    files.append(dest)
        result.update(ok=True, seconds=round(time.time() - start, 1), files=files)
        return result
    finally:
        result["gpu"] = {"released": released, "reclaimed": broker("/reclaim", post=True)}


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__)
    elif a[0] == "status":
        cmd_status()
    elif a[0] == "models":
        cmd_models(a[1] if len(a) > 1 else None)
    elif a[0] == "workflows":
        cmd_workflows()
    elif a[0] == "upload" and len(a) == 2:
        need_comfy()
        print(json.dumps({"ok": True, "name": upload(a[1])}))
    elif a[0] == "run" and len(a) >= 2:
        res = cmd_run(a[1], a[2:])
        print(json.dumps(res, indent=1))
        sys.exit(0 if res.get("ok") else 1)
    else:
        die("unknown command; run comfy.py help")


if __name__ == "__main__":
    main()
