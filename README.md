# Ultron — runbook

Private, unfiltered local chat assistant. Design and reasoning are in [PLAN.md](PLAN.md).

## What runs where

| Piece | Address (this PC only) | Notes |
|---|---|---|
| Chat UI (Open WebUI 0.13.3) | http://localhost:3000 | The only thing published to Tailscale |
| Model server (llama.cpp b12360) | 127.0.0.1:8080 | Native, GPU, API key required |
| Gateway (LiteLLM 1.109.1) | http://localhost:4000 | Token logs and keys; UI at `/ui`, log in with `LITELLM_MASTER_KEY` |
| Grafana | http://localhost:3001 | Dashboard "Ultron"; login is `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` |
| Prometheus | http://localhost:9090 | |
| Uptime Kuma | http://localhost:3002 | Create the admin and monitors on first visit |
| GPU exporter | 127.0.0.1:9835 | Native |

| Web search (SearXNG) | internal only | Used by the chat UI; no published port |
| Agent sandbox (Open Terminal 0.17.8) | internal only | Shell and files for `ultron-agent`; sees only the workspace folder |

All secrets are in `compose/.env` and `monitoring/secrets/` (git-ignored). This includes the Google Calendar refresh token, which the daily backup copies with the other secrets.

## Models

The model server runs in router mode (`scripts/models.ini`): one model is in VRAM at a time and it swaps on demand when a chat uses a different model name.

| Name in the picker | Model | Measured here |
|---|---|---|
| `ultron` | Gemma 4 12B Heretic, 24k context, thinking off | ~37 tok/s, ~8–9 GB VRAM, loaded at startup |
| `ultron-think` | Same loaded model with reasoning on | Same speed; several hundred extra tokens per answer |
| `ultron-agent` | Qwen3.6-35B-A3B Heretic, 32k context, part on CPU | ~45–50 tok/s, ~10.2 GB VRAM, ~11.6 GB RAM; ~30 s to swap in, ~13 s to swap back |

Test scripts: `scripts/test-tools.ps1`, `scripts/test-modes.ps1`, `scripts/test-refusals.ps1`, `scripts/bench-agent-model.ps1`.

## Agent sandbox

- The sandbox container can read and write only its own home volume and the workspace folder set by `AGENT_WORKSPACE` in `compose/.env`.
- It is on its own Docker network with Open WebUI only; it cannot reach the database, gateway or monitoring containers directly.
- It can reach the internet, and any service this PC publishes on localhost (model server, gateway, chat UI, Grafana, Uptime Kuma, Prometheus, GPU exporter). All but Prometheus and the GPU exporter require a key or login. Keep nothing private in the workspace.
- To connect it in Open WebUI: add an Open Terminal connection with URL `http://open-terminal:8000` and the `OPEN_TERMINAL_API_KEY` value from `compose/.env`, and enable it only for `ultron-agent`.

## Skills and the GPU broker

- `skills/<app>/` holds an instruction file (`SKILL.md`) and helper scripts for each app the agent may operate. The folder is mounted read-only in the sandbox at `/home/user/workspace/skills/`.
- `skills/comfyui/comfy.py` runs ComfyUI workflow templates (`skills/comfyui/workflows/*.json`), saves results to the workspace `outputs/` folder, and validates parameters before queueing. It never installs anything into ComfyUI and never submits arbitrary graphs.
- `scripts/gpu-broker.ps1` (localhost port 8090, started by `start-all.ps1`) lets the helper unload the chat model before a ComfyUI job and free ComfyUI's VRAM after it. The chat model reloads by itself on the next request.
- ComfyUI must be running on port 8188 (ComfyUI Desktop → instance → Manage → Startup Args: `--port 8188`). It only serves while the Desktop app has the instance launched.
- To add a workflow: export it from ComfyUI with File → Export (API) and wrap it as described in `skills/comfyui/SKILL.md`.

## Google Calendar

`tools/google_calendar.py` is an Open WebUI tool. It lets the bot read your calendar and add, move or delete events with phone reminders ("I have a haircut at 1pm this Sunday, remind me"). The reminders are Google Calendar's own notifications, so they reach every phone signed in to the Google Calendar app.

**One-time setup**

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project (e.g. "Ultron") and enable the **Google Calendar API**.
2. **Google Auth Platform → Branding/Audience:** set up the consent screen. With a personal Gmail account, choose *External*, add yourself as a test user, then click **Publish app** so the status reads *In production*. Publishing needs a home page and privacy policy link under Branding: use https://lcduc.github.io/ULTRON/ and https://lcduc.github.io/ULTRON/privacy.html (served from `docs/`), with authorized domain `lcduc.github.io`. In *Testing* status, Google expires the saved access after 7 days. The app stays unverified, which is fine for your own use: at sign-in, click *Advanced → Go to Ultron (unsafe)*. With a company Google Workspace account, choose *Internal* instead; nothing expires, but your Workspace admin may have to allow it.
3. **Clients → Create client → Desktop app.** Download the JSON file.
4. On this PC, run `python scripts/google-auth.py <downloaded.json>`. Sign in, allow calendar access, and the script writes `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REFRESH_TOKEN` into `compose/.env`. Delete the downloaded JSON afterwards.
5. `docker compose up -d open-webui` in `compose\` so the container picks up the new values.
6. Open WebUI → **Workspace → Tools → +**, paste `tools/google_calendar.py`, save with id `google_calendar`.
7. **Admin → Settings → Models**, edit `ultron`, `ultron-think` and `ultron-agent`, and tick *Google Calendar* under Tools so it is always on.

**How access is kept:** the refresh token in `compose/.env` lets the tool get a fresh one-hour access token whenever it needs one. You sign in again only if you revoke access at https://myaccount.google.com/permissions, the app is left in *Testing* status (7 days), or the token goes unused for 6 months. The tool then answers "Google sign-in failed"; rerun step 4 and 5.

**Limits on what it may do:** the token can only touch calendar events (scope `calendar.events`). Valves on the tool (Workspace → Tools → gear): calendar id, time zone override (default: the calendar's own), default length (60 min) and reminder (30 min). By default it can move or delete only events it created itself; set `ALLOW_CHANGING_OTHER_EVENTS` to change that. It refuses to add events in the past unless the user confirms, which catches wrong date arithmetic by the model.

**How the bot handles incomplete requests:** the instructions in the tool's docstrings tell the model to ask when the day or time is missing or vague, never to ask for an end time but to estimate a typical length (haircut 45 min, dinner 90 min, and so on), and to use all-day events for birthdays or trips. The tool backs this up in code, because a small model does not always follow instructions. It refuses a date without a time unless `all_day` is set, adds nothing when the same event is already there, and stops on a clash with another timed event until the user agrees to the overlap.

## Open WebUI settings made in the admin pages

Settings saved in the admin UI live in Open WebUI's database and override `.env` values. Record changes here so a rebuild can repeat them.

- Sign-ups disabled.
- Open Terminal connection to `http://open-terminal:8000` with the sandbox key; default terminal set on `ultron-agent` only.
- Function Calling set to Native on all three models.
- Web search (engine `searxng`, URL `http://searxng:8080/search`, 3 results) and code interpreter (Pyodide) enabled. These were written straight into the settings database on 2026-11-15 because the saved values overrode `.env`.

## Daily operation

- **Start everything:** `scripts\start-all.ps1` (also runs automatically at Windows sign-in, task "Ultron Start").
- **Stop containers:** `docker compose --profile gateway --profile monitoring --profile agent stop` in `compose\`.
- **Stop the model:** end the hidden PowerShell running `start-llama.ps1`, then `llama-server.exe`.
- **Docker fails with "file cannot be accessed by the system":** run `scripts\start-docker.ps1`; it moves the stale socket folders aside. Never use "Reset to factory defaults".
- **Model settings** (context size, model file): edit `scripts\start-llama.ps1`, then restart the model.

## Backups

- Task "Ultron Backup" runs `scripts\backup.ps1` daily at 03:00 and keeps 14 copies in `backups\`.
- Each backup holds the chat data, Grafana and Uptime Kuma data, the LiteLLM database dump, and the secrets.
- Copy `backups\` to another disk or cloud periodically; a backup on the same disk does not survive a disk failure.
- **Restore chat data:** stop the stack, then
  `docker run --rm -v ultron_open-webui-data:/data -v <backup folder>:/backup alpine:3.22 sh -c "rm -rf /data/* && tar xzf /backup/ultron_open-webui-data.tar.gz -C /data"`, then start again.

## Updating (monthly)

1. Read the release notes (Open WebUI has had serious security fixes this year).
2. Run a backup.
3. Change the pinned tag in `compose\docker-compose.yml`, then `docker compose --profile gateway --profile monitoring up -d`.
4. Send one chat message and check Grafana.

For llama.cpp, unpack a newer release over `bin\llama\` and re-check the flags in `start-llama.ps1` (flag names change between builds).

## Remote access (Tailscale)

1. Install Tailscale on this PC and sign in; install it on the phone/laptop with the same account.
2. In the Tailscale admin console, enable MagicDNS and HTTPS certificates.
3. Run `tailscale serve --bg 3000` once (also re-applied by `start-all.ps1`).
4. Open `https://<pc-name>.<tailnet>.ts.net` from any of your devices.
