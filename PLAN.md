# Ultron — private, unfiltered local chat assistant

Plan date: 2026-11-13. Researched from live sources by four research agents; items marked **[verify]** were not confirmed on a primary source and get checked at the step where they matter.

## 1. Target and constraints

- **Goal:** a private chat assistant with no refusals, running on this PC, usable from phone and laptop outside the home network.
- **Hardware:** RTX 3060 12 GB (about 1.2 GB already used by the Windows desktop), 32 GB RAM, i5-14600KF, Windows 11, Docker Desktop and Git installed.
- **Cost:** zero. Every component below is free and self-hosted.
- **Out of scope for now:** agents and tools, fine-tuning, billing. Covered briefly in section 10.

## 2. Chosen stack

| Layer | Choice | Why | Rejected |
|---|---|---|---|
| Model | Gemma 4 12B, "Heretic" decensored build, Q4_K_M GGUF (~7.4 GB) | Fits fully on GPU; model card reports 0/100 refusals with very small drift from the original (KL 0.028) | Older abliterations (more quality loss), Dolphin 3.0 8B (old Llama 3.1 base) |
| Runtime | llama.cpp `llama-server`, native on Windows | Uses the model's own chat template, built-in API key, prompt cache, native `/metrics` | Ollama (simpler, kept as fallback), ik_llama.cpp (gains are for CPU/MoE), vLLM and TabbyAPI (poor fit for Windows/12 GB/GGUF) |
| Chat UI | Open WebUI, pinned version, in Docker | Best fit for one user, SQLite storage, login built in, MCP support for later | LibreChat, AnythingLLM, LobeHub (heavier or weaker fit) |
| Remote access | Tailscale (private mesh VPN) + Tailscale Serve for HTTPS | Works behind CGNAT, no domain, nothing public to attack, no stream timeout | Cloudflare Tunnel + Access (documented as option B), ngrok (1 GB/month), Tailscale Funnel (public with no edge login) |
| Token tracking | Phase 1: llama-server metrics. Phase 3: LiteLLM proxy + Postgres | Per-key token and spend logs, rate limits, all in the free tier | Langfuse v3 (needs ~11 GB RAM), Helicone (maintenance mode) |
| Metrics | Prometheus + Grafana + `nvidia_gpu_exporter` on the Windows host | Standard, light, GPU temperature/VRAM/utilisation | DCGM exporter (not confirmed on consumer GPUs under WSL2) |
| Alerts | Uptime Kuma to Telegram or Discord | Light, free push notifications | — |

Fallback models to compare during Phase 1:
- `SC117/gemma-4-26B-A4B-it-qat-heretic-GGUF` (~14.2 GB, MoE, partial CPU offload): more capable, slower, still refuses about 13/100.
- Qwen3-14B abliterated Q4_K_M (~9 GB): older generation, kept as the Vietnamese comparison.

## 3. Architecture

```
Phone / laptop (Tailscale client)
        │  encrypted tailnet, HTTPS via Tailscale Serve
        ▼
This PC
  ├─ Tailscale (Windows service)  ──►  127.0.0.1:3000
  ├─ Docker Compose
  │    ├─ open-webui   :3000  (chat UI, login, history in SQLite volume)
  │    ├─ litellm      :4000  (phase 3: token logs, keys, rate limits)
  │    ├─ postgres            (phase 3: LiteLLM data)
  │    ├─ prometheus   :9090  (phase 3)
  │    ├─ grafana      :3001  (phase 3)
  │    └─ uptime-kuma  :3002  (phase 3)
  ├─ llama-server.exe  127.0.0.1:8080  (native, GPU, API key)
  └─ nvidia_gpu_exporter :9835 (native, phase 3)
```

Rules that hold in every phase:
- The model API (port 8080) is never reachable from outside this PC.
- Only Open WebUI is published to the tailnet. Grafana and the rest stay on localhost.
- All ports bind to `127.0.0.1`, not `0.0.0.0`.

## 4. Resource budget

| Resource | Use | Budget |
|---|---|---|
| VRAM | Windows desktop | ~1.2 GB |
| VRAM | Model weights Q4_K_M | ~7.4 GB |
| VRAM | KV cache, 16k context, q8_0 | ~1 GB **[verify by measuring]** |
| VRAM | Compute buffers | ~0.5–1 GB |
| VRAM | **Total** | ~10.5 GB of 12 GB |
| RAM | llama-server (prompt cache capped at 2 GB) | ~3–4 GB |
| RAM | Docker/WSL2 (capped in `.wslconfig`) | 6 GB |
| RAM | Windows and other apps | rest of 32 GB |

If VRAM is tight: drop context to 12k, or skip loading the vision projector (`mmproj`).

## 5. Phase 1 — model running locally

1. Create the folder layout:
   ```
   Ultron/
     bin/llama/          llama.cpp release
     models/             GGUF files (git-ignored)
     compose/            docker-compose.yml, .env (git-ignored)
     scripts/            start, backup, benchmark scripts
     monitoring/         prometheus.yml, Grafana dashboards
     backups/            (git-ignored)
   ```
2. `git init`, add a `.gitignore` covering `models/`, `backups/`, `.env`, `bin/`.
3. Download the latest llama.cpp Windows CUDA 12 build from the official GitHub releases page into `bin/llama/`. **[verify]** the exact asset name for the current build.
4. Download `gemma-4-12B-it-heretic-Q4_K_M.gguf` from `igorls/gemma-4-12B-it-heretic-GGUF` into `models/`. **[verify]** the repo and file name, and check whether a Q5_K_M or Q6_K file exists; if it does and fits, prefer it.
5. Generate a random API key into `compose/.env` (never typed into chat or committed).
6. Start the server with these settings:
   ```
   llama-server -m models\<file>.gguf -ngl all -c 16384 -np 1 -fa on
     -ctk q8_0 -ctv q8_0 --cache-reuse 256 -cram 2048
     --host 127.0.0.1 --port 8080 --api-key <from .env> --metrics
   ```
   - `-np 1`: one slot, so the whole 16k context belongs to one chat. Raise to 2 only if a second person uses it.
   - `-ctk/-ctv q8_0`: halves context memory with near-zero quality loss. Do not use `q4_0`.
   - The author recommends non-thinking mode for this build; set that in the chat template options. **[verify]** the flag.
7. Acceptance checks:
   - `nvidia-smi` shows all layers on GPU and VRAM under 11 GB.
   - A request to `/v1/chat/completions` without the key is rejected; with the key it answers.
   - Speed is at least 25 tokens/sec (community figure is ~33; measure with `llama-bench`).
   - Run 10 of your own prompts that a filtered model refuses, and 10 Vietnamese prompts. Record refusals and quality.
8. Repeat step 7 with one fallback model if Vietnamese or quality disappoints, then lock the model.

## 6. Phase 2 — chat UI and access from outside

1. Write `compose/docker-compose.yml` with Open WebUI:
   - Image pinned to an exact version (currently v0.13.3), never `latest`.
   - Port `127.0.0.1:3000:8080`, volume for data, `restart: unless-stopped`, healthcheck, log rotation.
   - Environment: `OPENAI_API_BASE_URL=http://host.docker.internal:8080/v1`, the API key from `.env`, `ENABLE_OLLAMA_API=false`, a fixed `WEBUI_SECRET_KEY`.
   - **[verify]** that a container can reach a host service bound to `127.0.0.1` through `host.docker.internal`. If not, bind llama-server to the WSL virtual adapter only and add a Windows Firewall rule blocking LAN access.
2. Start it, create the admin account yourself in the browser (the first account becomes admin), then set `ENABLE_SIGNUP=false` and restart.
3. In Open WebUI admin settings: turn off code execution, web search and any tool you don't use; set your system prompt.
4. Install Tailscale on this PC and your phone/laptop (you sign in yourself; free Personal plan, 6 users).
   - Enable unattended mode so it runs before Windows login.
   - Enable MagicDNS and HTTPS certificates in the Tailscale admin console.
   - Run `tailscale serve --bg 3000` to publish Open WebUI at `https://<pc-name>.<tailnet>.ts.net`, visible only to your devices.
5. Acceptance checks:
   - From the phone on mobile data: the URL loads, login works, a long answer streams to the end.
   - From a device not on the tailnet: the URL does not resolve or connect.
   - Port 8080 and 3000 are not reachable from another device on the home Wi-Fi.

**Option B, if you later need a public URL or inbound webhooks:** Cloudflare Tunnel plus Cloudflare Access with email one-time PIN in front. Needs a domain (roughly US$10/year), and silent gaps over about 100 seconds in a stream can be cut off. Both options can run side by side.

## 7. Phase 3 — token tracking and monitoring

1. Add LiteLLM proxy and Postgres to the compose file.
   - Use the official Docker image pinned by version or digest. Do not `pip install` it: two PyPI releases were malicious in March 2026.
   - Open WebUI now points at `http://litellm:4000`; LiteLLM points at llama-server.
   - Create one virtual key per person or device. Token counts and request logs land in Postgres.
   - Enable the Prometheus callback (`/metrics` needs a bearer key).
2. Install `nvidia_gpu_exporter` on Windows as a service (port 9835 **[verify]**).
3. Add Prometheus scraping three targets: llama-server `/metrics`, LiteLLM `/metrics`, the GPU exporter.
4. Add Grafana with one dashboard: tokens per day, tokens/sec, request latency, VRAM, GPU temperature and utilisation.
5. Add Uptime Kuma checking Open WebUI, LiteLLM and llama-server health; send alerts to Telegram or Discord.
6. Acceptance checks:
   - A chat message shows up as tokens in LiteLLM and on the Grafana dashboard within a minute.
   - Stopping llama-server triggers a phone alert.
   - Total RAM for all containers stays under 3 GB (estimate is 1.5–2.5 GB).

Optional later: Arize Phoenix as a single container for full conversation traces (~0.5–1 GB, estimate).

## 8. Phase 4 — production-grade checklist

| Area | Check |
|---|---|
| Boot | llama-server starts via Task Scheduler at startup, with restart on failure |
| Boot | Docker Desktop set to start at sign-in; Windows auto-login or a scheduled task covers reboots **[verify]** |
| Power | Sleep set to Never, hibernate off, Windows Update active hours set |
| Memory | `.wslconfig` caps WSL2 at 6 GB so Docker cannot starve the model |
| Secrets | All keys in `.env`, git-ignored; nothing secret in the compose file |
| Versions | Every image and binary pinned; monthly update routine: read release notes, back up, update, re-test |
| Security | Open WebUI has had several serious CVEs in 2026, so updates are not optional |
| Backups | Nightly scheduled copy of the Open WebUI volume and a Postgres dump to `backups/` and one off-PC location |
| Backups | One restore test done and written down |
| Logs | Docker log rotation (`max-size`, `max-file`) on every service; llama-server log file rotated |
| Health | Healthcheck on every container; `docker compose ps` all healthy after a reboot test |
| Exposure | Port scan from another LAN device shows nothing open; only the tailnet URL works remotely |
| Recovery | A one-page runbook: how to start, stop, update, restore, and what each alert means |

## 9. Optimisation procedure

Do these in order, measuring before and after each change with `llama-bench` and a fixed set of 5 prompts:

1. Confirm full GPU offload and flash attention are active (largest effect).
2. Try a higher quant (Q5_K_M or Q6_K) if VRAM allows: better answers, slightly slower.
3. Tune context: 16k default; go to 24k only if VRAM stays under 11.3 GB.
4. Check that prompt caching works: the second message in a chat should start much faster than the first.
5. Try draftless speculative decoding (`--spec-type ngram-mod`): free, helps only on repetitive text.
6. Skip draft-model speculative decoding and 4-bit KV cache: both cost more than they give on 12 GB.
7. Close GPU-heavy desktop apps (browsers with hardware acceleration, games) while the model is serving. The KF-series CPU has no integrated graphics, so the ~1.2 GB desktop cost on the 3060 cannot be moved off it.
8. Test the 26B MoE fallback with `--n-cpu-moe` once, to see whether its quality is worth the lower speed.

## 10. Later, not now

- **Tools and agents:** Open WebUI supports MCP servers natively (Streamable HTTP). Start there before adding LangGraph; the framework matters less than the model's tool-calling ability.
- **Fine-tuning:** QLoRA with Unsloth fits a 12B model on 12 GB only barely. Wait until LiteLLM logs show a consistent gap worth tuning for, then use those logs as training data.
- **Bigger hardware:** a second-hand 24 GB card would allow 27–32B models and is the single biggest quality upgrade.

## 11. Known gaps in the research

- The uncensored-model leaderboard (UGI) and community threads could not be loaded, so the model ranking rests on model cards and blogs.
- Vietnamese quality is untested for every candidate; Phase 1 step 7 settles it.
- Speed figures are community numbers, not measurements on this PC.
- RAM figures for the monitoring stack are estimates.
- An unfiltered model still makes things up. Removing refusals does not make a 12B model accurate.
