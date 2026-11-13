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

All secrets are in `compose/.env` and `monitoring/secrets/` (git-ignored).

Model: `models/gemma-4-12B-it-heretic-Q4_K_M.gguf`, 16k context, thinking off. Measured on this PC: ~37 tokens/sec, ~8.8 GB VRAM, ~1.3 GB RAM.

## Daily operation

- **Start everything:** `scripts\start-all.ps1` (also runs automatically at Windows sign-in, task "Ultron Start").
- **Stop containers:** `docker compose --profile gateway --profile monitoring stop` in `compose\`.
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
