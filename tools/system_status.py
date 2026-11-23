"""
title: System Status
description: Read-only health report of this PC: GPU, model server, generation speed and every service.
version: 1.0.0
license: MIT
"""

# Open WebUI tool (tool id: system_status). Install: see "System status" in the README.
#
# Strictly read-only. It only sends GET requests (and opens TCP connections to check a port):
#   - Prometheus queries for the GPU and the generation speed. They are the same PromQL
#     expressions as the Grafana dashboard "Ultron", so the numbers match.
#   - The model server's /health. It never asks for per-model metrics, so it can never load
#     or swap a model.
#   - A quick probe of each service from inside this container, run at the same time.
# No keys or tokens are used or returned. Any failure is reported in the result; one failing
# check never fails the tool.

import asyncio
import math
import socket
import time
from typing import Callable, Optional
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, Field

# Same expressions as monitoring/grafana/dashboards/ultron.json.
GPU_QUERIES = {
    "temp": "nvidia_smi_temperature_gpu",
    "used": "nvidia_smi_memory_used_bytes",
    "total": "nvidia_smi_memory_total_bytes",
    "util": "nvidia_smi_utilization_gpu_ratio * 100",
    "power": "nvidia_smi_power_draw_watts",
    "name": "nvidia_smi_gpu_info",
}


def _speed_query(window: str) -> str:
    return (
        f"1 / (sum(rate(litellm_deployment_latency_per_output_token_sum[{window}])) "
        f"/ sum(rate(litellm_deployment_latency_per_output_token_count[{window}])))"
    )


GIB = 1024**3


class Tools:
    class Valves(BaseModel):
        PROMETHEUS_URL: str = Field(
            default="http://prometheus:9090", description="Prometheus base URL."
        )
        LLAMA_HEALTH_URL: str = Field(
            default="http://host.docker.internal:8080/health",
            description="Model server (llama.cpp) health URL. Only /health is ever requested.",
        )
        SERVICES: str = Field(
            default=(
                "gateway=http://litellm:4000/health/liveliness,"
                "search=http://searxng:8080/healthz,"
                "voice=http://kokoro:8880/health,"
                "calendar=http://calendar-mcp:8000/health,"
                "phone pushes=http://ntfy:80/v1/health,"
                "grafana=http://grafana:3000/api/health,"
                "uptime-kuma=http://uptime-kuma:3001/,"
                "prometheus=http://prometheus:9090/-/healthy,"
                "database=tcp://postgres:5432"
            ),
            description="Services to probe, as name=url, comma separated. tcp://host:port only checks the port.",
        )
        PROBE_TIMEOUT_SECONDS: float = Field(
            default=2.0, description="Time allowed for each check."
        )

    def __init__(self):
        self.valves = self.Valves()

    # ------------------------------------------------------------------ helpers

    def _timeout(self) -> float:
        try:
            return max(0.2, min(float(self.valves.PROBE_TIMEOUT_SECONDS), 5.0))
        except Exception:
            return 2.0

    def _prom(self, query: str):
        """Returns the list of result rows for an instant query. Raises on failure."""
        r = requests.get(
            self.valves.PROMETHEUS_URL.rstrip("/") + "/api/v1/query",
            params={"query": query},
            timeout=self._timeout(),
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "success":
            raise RuntimeError("query failed")
        return data["data"]["result"]

    def _prom_value(self, query: str) -> Optional[float]:
        rows = self._prom(query)
        if not rows:
            return None
        v = float(rows[0]["value"][1])
        return None if math.isnan(v) or math.isinf(v) else v

    def _probe(self, name: str, url: str) -> dict:
        """One check. Always returns a dict, never raises."""
        start = time.time()
        try:
            p = urlparse(url)
            if p.scheme == "tcp":
                with socket.create_connection((p.hostname, p.port), timeout=self._timeout()):
                    pass
                ok, detail = True, ""
            else:
                r = requests.get(url, timeout=self._timeout(), allow_redirects=False)
                # Any answer below 500 means the service is alive; a 401 from a protected
                # health path still shows that it is up.
                ok = r.status_code < 500
                detail = "" if ok else f"HTTP {r.status_code}"
            return {"name": name, "ok": ok, "detail": detail, "ms": int((time.time() - start) * 1000)}
        except Exception as e:
            kind = type(e).__name__
            if isinstance(e, (requests.exceptions.Timeout, socket.timeout)):
                kind = "no answer in time"
            elif isinstance(e, (requests.exceptions.ConnectionError, ConnectionError, OSError)):
                kind = "connection refused"
            return {"name": name, "ok": False, "detail": kind, "ms": int((time.time() - start) * 1000)}

    def _model_health(self) -> dict:
        try:
            r = requests.get(self.valves.LLAMA_HEALTH_URL, timeout=self._timeout())
            if r.status_code == 200:
                return {"state": "ok"}
            if r.status_code == 503:
                return {"state": "loading"}
            return {"state": "down", "detail": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"state": "down", "detail": type(e).__name__}

    def _gpu(self) -> dict:
        out: dict = {}
        rows = self._prom(GPU_QUERIES["name"])
        if rows:
            out["name"] = rows[0]["metric"].get("name", "GPU")
        for key in ("temp", "used", "total", "util", "power"):
            try:
                v = self._prom_value(GPU_QUERIES[key])
            except Exception:
                v = None
            if v is not None:
                out[key] = v
        return out

    def _speed(self) -> dict:
        """Generation speed from LiteLLM metrics; widens the window once if idle."""
        for window, label in (("5m", "last 5 min"), ("30m", "last 30 min")):
            v = self._prom_value(_speed_query(window))
            if v is not None:
                return {"tokens_per_s": round(v, 1), "window": label}
        return {}

    def _prom_up(self) -> dict:
        return {
            r["metric"].get("job", "?"): r["value"][1] == "1" for r in self._prom("up")
        }

    def _collect(self) -> dict:
        report: dict = {"problems": []}

        # Everything below runs at the same time; each part catches its own failures.
        from concurrent.futures import ThreadPoolExecutor

        services = []
        for part in self.valves.SERVICES.split(","):
            if "=" in part:
                n, u = part.split("=", 1)
                services.append((n.strip(), u.strip()))

        with ThreadPoolExecutor(max_workers=len(services) + 5) as pool:
            f_model = pool.submit(self._model_health)
            f_gpu = pool.submit(self._gpu)
            f_speed = pool.submit(self._speed)
            f_up = pool.submit(self._prom_up)
            f_probes = [pool.submit(self._probe, n, u) for n, u in services]

            report["model_server"] = f_model.result()
            probes = [f.result() for f in f_probes]

            prom_ok = True
            try:
                report["gpu"] = f_gpu.result()
            except Exception:
                prom_ok = False
                report["gpu"] = {}
            try:
                report["speed"] = f_speed.result()
            except Exception:
                prom_ok = False
                report["speed"] = None
            try:
                report["prometheus_jobs"] = f_up.result()
            except Exception:
                prom_ok = False
                report["prometheus_jobs"] = {}

        report["services"] = probes
        report["prometheus_reachable"] = prom_ok

        # Problems come first in the output.
        problems = report["problems"]
        ms = report["model_server"]
        if ms["state"] != "ok":
            problems.append(f"model server is {ms['state']}" + (f" ({ms['detail']})" if ms.get("detail") else ""))
        for p in probes:
            if not p["ok"]:
                problems.append(f"{p['name']} is down" + (f" ({p['detail']})" if p["detail"] else ""))
        if not prom_ok:
            problems.append("could not read Prometheus, so GPU figures or speed may be missing")
        for job, up in report["prometheus_jobs"].items():
            if not up:
                problems.append(f"Prometheus cannot scrape '{job}'")
        gpu = report["gpu"]
        if gpu.get("temp", 0) >= 83:
            problems.append(f"GPU is hot at {gpu['temp']:.0f} C")
        if gpu.get("used") and gpu.get("total") and gpu["used"] / gpu["total"] > 0.97:
            problems.append("GPU memory is almost full")
        return report

    def _render(self, rep: dict, detail: bool) -> str:
        lines = []
        problems = rep["problems"]
        lines.append("PROBLEMS: " + ("; ".join(problems) if problems else "none, everything is up"))

        g = rep["gpu"]
        if g:
            parts = [g.get("name", "GPU")]
            if "temp" in g:
                parts.append(f"{g['temp']:.0f} C")
            if "util" in g:
                parts.append(f"{g['util']:.0f}% busy")
            if "used" in g and "total" in g:
                parts.append(f"VRAM {g['used'] / GIB:.1f} of {g['total'] / GIB:.1f} GB")
            if "power" in g:
                parts.append(f"{g['power']:.0f} W")
            lines.append("GPU: " + ", ".join(parts))
        else:
            lines.append("GPU: no data (Prometheus or the GPU exporter did not answer)")

        ms = rep["model_server"]
        sp = rep.get("speed")
        if sp:
            speed = f"generating about {sp['tokens_per_s']} tokens/s ({sp['window']})"
        elif rep["prometheus_reachable"]:
            speed = "no recent requests, so no speed reading"
        else:
            speed = "speed unknown (Prometheus unreachable)"
        lines.append(f"Model server: {ms['state']}; {speed}")

        probes = rep["services"]
        up = [p for p in probes if p["ok"]]
        lines.append(f"Services: {len(up)} of {len(probes)} up")
        if detail:
            for p in probes:
                lines.append(f"  - {p['name']}: {'up' if p['ok'] else 'DOWN'} ({p['ms']} ms)" + (f" {p['detail']}" if p["detail"] else ""))
            if rep["prometheus_jobs"]:
                lines.append(
                    "Prometheus scrape jobs: "
                    + ", ".join(f"{j} {'up' if u else 'DOWN'}" for j, u in rep["prometheus_jobs"].items())
                )
        else:
            lines.append("  up: " + ", ".join(p["name"] for p in up))
            down = [p["name"] for p in probes if not p["ok"]]
            if down:
                lines.append("  down: " + ", ".join(down))
        return "\n".join(lines)

    # ------------------------------------------------------------------ tool

    async def system_status(
        self, detail: bool = False, __event_emitter__: Callable = None
    ) -> str:
        """
        Get the live status of this PC and the assistant. ALWAYS call this tool for any
        question about how the PC, computer, system, server or Ultron is doing ("how's the
        PC?", "is everything running?", "any problems?", "how are you doing?"), the GPU
        (temperature, load, memory, power), or the model's speed. Never answer such
        questions from memory: the figures change every minute. It returns GPU temperature,
        load, memory and power, whether the model server is ready, the generation speed in
        tokens per second, and whether each service is up, with problems listed first.
        Read-only.
        :param detail: Set true to list every service with its response time.
        :return: A short plain-text status report.
        """
        if __event_emitter__:
            try:
                await __event_emitter__(
                    {"type": "status", "data": {"description": "Checking the system", "done": False}}
                )
            except Exception:
                pass
        try:
            rep = await asyncio.to_thread(self._collect)
            text = self._render(rep, bool(detail))
        except Exception as e:
            text = f"PROBLEMS: the status check itself failed ({type(e).__name__})."
        if __event_emitter__:
            try:
                await __event_emitter__(
                    {"type": "status", "data": {"description": "System checked", "done": True}}
                )
            except Exception:
                pass
        return text
