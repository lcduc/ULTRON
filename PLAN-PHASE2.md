# Ultron phase 2 — from chatbot to general-purpose agent

Plan date: 2026-11-14 (second revision). Builds on the running phase 1 stack ([PLAN.md](PLAN.md), [README.md](README.md)).
Items marked **[verify]** come from research not confirmed on a primary source, or are untested on this PC.

## 1. Goal

The bot should act, not only answer. Given an instruction such as *"connect to ComfyUI on this PC and build me a working image-generation pipeline"*, it should:

1. find out how the target app works (read its API, list what is installed),
2. write and run the commands or code needed,
3. check the result, fix errors, and repeat until it works,
4. report back in the chat, including from the phone.

ComfyUI is the worked example. The same approach should extend to other apps on the PC.

It should also keep what the first draft of this plan covered: a thinking mode, tool calling, and web search.

## 2. What is already proven on this PC

Tested on 2026-11-14 against the running model (Gemma 4 12B Heretic, Q4_K_M):

| Test | Result |
|---|---|
| Single tool call with correct arguments | Pass |
| Using a tool result to write the answer | Pass |
| Choosing between tools; no tool for simple maths | Pass |
| Thinking switched on per request (`chat_template_kwargs: {"enable_thinking": true}`) | Pass |
| Reasoning and tool calls streamed through the LiteLLM gateway | Pass |
| `reasoning_effort` parameter | No effect on this model |

Single prompts only: the mechanisms work; reliability over long chains is unmeasured.

Also established: ComfyUI Desktop is installed on F:, with saved workflows that already form a pipeline and a set of workflows exported in API format. It was not running when checked.

## 3. Honest expectations

| Task type | 12B model (current) | Larger model (section 5) |
|---|---|---|
| Chat, short answers | Good, 37 tokens/sec | Slower, no real gain |
| One or two tool calls (search and answer) | Should be fine | Fine |
| Scripted task of 3–6 steps with a skill file to follow | Plausible; needs testing | Expected to be reliable **[verify]** |
| Open-ended "work out this app and build something" | Likely to lose the plan | Possible, with retries; still far from a frontier cloud model |
| Composing a ComfyUI node graph from scratch | One public test: a 12B Gemma scored 13/20 | Better, unmeasured |

Nothing here will match a top cloud coding agent. The plan is built to find out, cheaply and early, how far a local model gets on this hardware.

## 4. Design

Four pieces, each added on top of phase 1:

```
Phone / PC browser
      │
Open WebUI ── agent loop (calls tools, reads results, repeats)
      │
      ├─ LiteLLM ── llama-server in router mode (one model in VRAM at a time)
      │               ├─ ultron         Gemma 4 12B, fast chat
      │               ├─ ultron-think   same model, thinking on
      │               └─ ultron-agent   larger model, for multi-step work
      │
      ├─ SearXNG container ── web search
      │
      └─ Sandbox container (Open Terminal) ── shell, files, code
              │  workspace folder (the only host folder it can see)
              │  skills/<app>/  instruction file + helper scripts per app
              ├─► named local apps via host.docker.internal (ComfyUI, …)
              └─► GPU broker on the host: "release GPU" / "reclaim GPU"
```

| Piece | Choice | Why |
|---|---|---|
| Agent front end | Open WebUI with Open Terminal | Already reachable from the phone; the terminal gives the model a shell, files and code execution inside a container |
| Second front end (optional) | OpenCode on the PC | Ranked best for local models in one guide **[verify]**; has per-command approval; reads the same skill files |
| Sandbox | Docker container, one bind-mounted workspace folder, no Docker socket | A bare-metal terminal would give the model everything your Windows account can do |
| Skills | `workspace/skills/<app>/SKILL.md` plus helper scripts | Lets a small model follow a known route instead of rediscovering it. No measured benefit for small models yet, so test before writing many |
| GPU hand-off | Small host-side "GPU broker" with two actions | Image models and the chat model cannot share 12 GB; no existing tool does this swap |
| Model switching | llama-server router mode | Models load on demand from the picker; only one in VRAM |

## 5. The model question

**Candidate agent model:** Qwen3.6-35B-A3B in a decensored GGUF, Q4_K_M, 21.8 GB (`llmfan46/Qwen3.6-35B-A3B-uncensored-heretic-Native-MTP-Preserved-GGUF`). It is the most-cited open model for agent harnesses, and vendor benchmarks put it well ahead of the Gemma family on multi-step tool use.

What is uncertain, and gets measured before anything else is built on it:

| Question | What research found | How it is settled |
|---|---|---|
| Speed on a 3060 with CPU offload | 20–40 tokens/sec reported, from blogs with unknown settings | `llama-bench` sweep over `--n-cpu-moe` values at 32k context |
| RAM fit | About 12 GB in system RAM plus about 10 GB on GPU, alongside Docker's 6 GB cap | Measure free RAM with the full stack running |
| Refusals | Card reports 10 in 100, not zero | Same refusal prompts as for Gemma |
| Lower quants | One test saw error rates rise sharply below Q4 | Stay at Q4_K_M; do not use Q3 |
| Context | Harnesses want 32k minimum, 64k preferred | Start at 32k; raise if VRAM allows |

**Go/no-go:** adopt it as `ultron-agent` if it runs at 12 tokens/sec or better at 32k context and passes at least 4 of the 6 ladder tasks in section 9. Otherwise stay on the 12B model with skills and accept the narrower scope.

Gemma stays the default for chat either way. Switching models takes a reload each time, expected to be tens of seconds for the larger one **[verify]**.

## 6. Build stages

### Stage 1 — quick wins on the current model

1. `scripts/start-llama.ps1`: context 16k → 24k; thinking default set with `--chat-template-kwargs '{"enable_thinking":false}'` and `--reasoning-format deepseek`; samplers `--temp 1.0 --top-p 0.95 --top-k 64`.
2. `ultron-think` as a second model name. First try LiteLLM `extra_body`; a bug report describes such parameters "sticking" to later requests, so alternate 10 requests between the two names and confirm only one thinks. Fallback: define the variant inside Open WebUI.
3. SearXNG container for web search: pinned tag **[verify]**, 512 MB limit, no published port, `json` format enabled, limiter off. Open WebUI: engine `searxng`, 3 results, fetched page length capped, local-network fetch left off, tool loop capped at 8 rounds.
4. Run the thinking-versus-refusal comparison (same prompts, thinking on and off).

Accept when: VRAM under 11.3 GB, speed above 30 tokens/sec, earlier tool tests still pass, a search question is answered with a cited source.

### Stage 2 — model trial and router mode

1. Download the candidate model (21.8 GB; F: has about 92 GB free).
2. Benchmark and decide per section 5.
3. Switch `start-llama.ps1` to router mode with a presets file: one entry per model with its own context, offload and sampler settings; `--models-max 1` so loading one unloads the other.
4. Register `ultron-agent` in LiteLLM and allow it on the Open WebUI key.
5. Update `Model ON/OFF` scripts and the Grafana dashboard for router mode.

### Stage 3 — sandbox and terminal

1. Add an `open-terminal` service to the compose file: pinned tag **[verify; sources disagree on the current version]**, API key from a secret file, memory limit, no Docker socket, not published to Tailscale.
2. Bind-mount one workspace folder (outside this repository) as the only host path.
3. Connect it in Open WebUI and enable it only for `ultron-agent`.
4. Probe from inside the container which host ports it can reach, and record the result. Services with keys (model server, gateway, Grafana) stay protected by their keys; anything unauthenticated that is reachable gets listed as a known exposure or locked down.

### Stage 4 — GPU broker and the ComfyUI skill

1. **GPU broker:** a small host service on a localhost port with two actions and no secrets exposed to the sandbox: *release* (unload the chat model through the router) and *reclaim* (tell ComfyUI to free VRAM, wait until VRAM is clear).
2. **ComfyUI side:** update ComfyUI first (an unauthenticated remote-code flaw and a hijacking campaign against exposed instances were reported in 2026 **[verify the CVE]**); set a fixed port; keep it on localhost; "Console only" launch mode so it runs without the window. It only serves while the Desktop app has the instance launched.
3. **Skill folder:** `SKILL.md` describing the API and the available workflows, plus a helper script that queues an API-format workflow with parameters, waits, fetches the result into the workspace, and calls the broker before and after. Export your saved workflows in API format as the templates.
4. **Long jobs:** a start-job step that returns at once and a get-result step, with Open WebUI's tool timeout raised, since video jobs run for minutes.
5. **Results in chat:** images are returned through Open WebUI so they show on the phone; a ComfyUI link would not be reachable there.

While a GPU job runs, the bot is unloaded and silent. It reloads when the job finishes.

### Stage 5 — more skills, optional OpenCode

- Add one skill per app you want operated; each is an instruction file plus helpers.
- Optionally install OpenCode on the PC for long desktop sessions with per-command approval, pointed at the same gateway and skills.

## 7. Safety boundary

The first draft kept every tool read-only. A general agent cannot, so the boundary moves from "what tools exist" to "where they run".

| Risk | Boundary |
|---|---|
| The model runs a destructive command | It runs inside the container; only the workspace folder is at stake. Keep the workspace under git so changes can be undone |
| A web page plants instructions (the model has no refusal backstop) | Web search and the terminal are not enabled on the same model entry by default. `ultron` and `ultron-think` search; `ultron-agent` has the terminal. Turning both on for a task is a deliberate choice |
| The sandbox reaches other services on the PC | Probe and record reachable ports (stage 3); secrets never placed in the workspace or the container environment |
| The agent installs things in ComfyUI or submits arbitrary graphs | The helper script only runs known templates by default and never calls the Manager install endpoints; raw graph submission is a separate, opt-in command |
| Terminal API exposed | Not published to Tailscale; reachable only from the Open WebUI container |
| Runaway loops | Tool-round cap; GPU job timeout with interrupt |

What the boundary does not cover: the sandbox has internet access (needed to install packages), so a hijacked session could download or send data from the workspace. Keep nothing private in the workspace.

## 8. Resource budget

| Resource | Phase 1 (measured) | Phase 2 (expected) |
|---|---|---|
| VRAM, Gemma at 24k | 8.8 GB at 16k | About 9.0 GB **[verify]** |
| VRAM, agent model | — | Filled to about 10.5 GB, rest in RAM |
| System RAM with agent model loaded | 15 GB free | Tight: about 12 GB model + 6 GB Docker + Windows **[verify]** |
| Docker RAM | 2.1 GB of 6 GB | About 3 GB with SearXNG and the terminal **[verify]** |
| Disk | — | +22 GB for the model |

## 9. Acceptance ladder

Six tasks, easiest first, each run on both models where possible. Record pass/fail, rounds used and time.

1. Answer a current-events question with a cited source (search).
2. In the sandbox: write a script that fetches a public JSON API, summarise the result.
3. Fix a deliberately broken script from its error message.
4. Read a local service's API description and list what it offers (ComfyUI's node and model lists).
5. With the ComfyUI skill: generate one image from a text instruction, hand the GPU over and back, show the image in chat.
6. The headline task: from a plain instruction, chain two workflows (generate, then edit or animate) and return the result.

Also run: the thinking-versus-refusal comparison, one page with an embedded instruction, and one chat that exceeds the context window.

## 10. Order and what needs you

| Stage | Needs you? |
|---|---|
| 1. Quick wins | Admin-UI settings behind your Open WebUI login |
| 2. Model trial | Go/no-go decision after the benchmark |
| 3. Sandbox | Choice of workspace folder; your login to enable the terminal |
| 4. ComfyUI skill | Launch settings in the ComfyUI Desktop app; exporting your workflows in API format; which workflows the bot may run |
| 5. More skills | Which apps come next |

Stages 1 and 2 are independent and can run in either order. Stage 2 is the one that decides how ambitious stages 4 and 5 can be, so it is worth doing early.

## 11. Results so far (measured 2026-11-14)

### Model trial: Qwen3.6-35B-A3B Heretic, Q4_K_M (20.3 GB), 32k context

Sweep of `--n-cpu-moe` (memory-mapped load):

| `--n-cpu-moe` | VRAM used | Generation | Prompt processing |
|---|---|---|---|
| 40 | 3.5 GB | 19.5 tok/s | 133 tok/s |
| 32 | 7.3 GB | 19.8 tok/s | 161 tok/s |
| 28 | 9.2 GB | 27.6 tok/s | 198 tok/s |
| **24** | **11.0 GB** | **46.0 tok/s** | **397 tok/s** |
| 20 | 11.9 GB | 45.7 tok/s | 445 tok/s (no VRAM headroom) |

Chosen setting: `--n-cpu-moe 24 --load-mode none`. Measured with it: 50 tok/s, loads in 24 s, 10.1 GB VRAM, 11.6 GB process RAM, 8.9 GB system RAM left free with the Docker stack running.

| Check (`scripts/test-tools.ps1`, `scripts/test-refusals.ps1`) | Gemma 4 12B Heretic | Qwen3.6-35B-A3B Heretic |
|---|---|---|
| Tool tests (single call, no-tool case, 2-step chain, error recovery, thinking) | 5 of 5 | 5 of 5 |
| Refusals, thinking off (8 prompts) | 0 | 0 |
| Refusals, thinking on (8 prompts) | 0; 1 answer cut off by the token limit | 0; 3 answers cut off by the token limit |
| Speed | 37 tok/s | 50 tok/s |

The speed pass mark (12 tok/s) is cleared. The task-ladder pass mark needs the sandbox (stage 3) and is still open. The tool tests are simulated and short; they do not separate the two models.

### Stage 2 and 3 status

| Item | Status |
|---|---|
| Router mode with `scripts/models.ini`, one model in VRAM | Done; swap to the agent model takes about 30 s, back about 13 s |
| `ultron-agent` in the gateway and on the chat UI's key | Done; answers through the gateway |
| Monitoring | A per-model metrics request forces a model swap in router mode, so the model-server scrape job was removed; dashboard panels now use gateway metrics |
| Sandbox container (Open Terminal 0.17.8) | Running, API key enforced, on its own network with Open WebUI only |
| Sandbox reach, probed | Workspace writable; other containers unreachable; internet reachable; every localhost-published service on the PC reachable (Prometheus and the GPU exporter have no login) |
| Connecting the sandbox in Open WebUI and enabling it for `ultron-agent` | Not done; needs the admin login |
| Task ladder | Not run; needs the item above |

### Stage 1 status

| Item | Status |
|---|---|
| Context 24k, Google's samplers, thinking default off via template kwargs | Done; VRAM about 8.1–8.9 GB |
| `ultron-think` model name | Done; modes stayed separate over 10 alternating requests (`scripts/test-modes.ps1`) |
| SearXNG container | Done; a JSON search from inside the Open WebUI container returned results |
| Open WebUI search and code-interpreter settings | Set through environment variables; not confirmed to be active, because settings saved in the admin UI can override them. Check Admin → Settings → Web Search |
| Thinking-versus-refusal comparison | Done, table above |
| Per-model abilities (native function calling, web search, memory) and system prompt | Not done; needs the Open WebUI admin login |
