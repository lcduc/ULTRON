# Ultron — one model for chat, voice and agent work

Plan date: 2026-11-22. Builds on [PLAN-PHASE2.md](PLAN-PHASE2.md) (router mode, agent model) and [PLAN-ASSISTANT.md](PLAN-ASSISTANT.md) (voice, briefings, speed targets).
Items marked **[verify]** are untested on this PC.

## 1. Goal

Replace today's two models (Gemma 4 12B for chat, Qwen3.6-35B-A3B Heretic for agent work, swapped on demand) with **one model that stays loaded**: no ~30 s swaps, tools and vision available in every chat, one model to tune.

**Decided 2026-11-22:**

| Question | Answer |
|---|---|
| Uncensored model needed? | No. Official releases are fine (they also call tools more reliably) |
| ComfyUI | Probably not used again, so the model never has to leave the GPU |
| Vision | Yes: photos of receipts, letters, screenshots |
| Language | English is enough |
| Unused parts | Stay on disk and in the repo: old model files, Gemma and Heretic presets, GPU broker, ComfyUI skill, `model-idle.ps1` |
| Downloads and benchmarks | Approved 2026-11-22 night; run unattended overnight by subagents, reviewed by the main session |
| If Qwen misses a pass mark (e.g. voice delay) after the levers | Switch to Qwen anyway. Exception: a hard failure (won't load or fit, tool calls broken, vision broken) keeps today's setup running so the app works in the morning |
| Commit | One local commit on `assistant-phase3` after stage 4 passes; not pushed |

## 2. The choice

**Main pick: Qwen3.6-35B-A3B, official, with vision.** File: `unsloth/Qwen3.6-35B-A3B-MTP-GGUF`, `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` (22.66 GB) plus `mmproj-F16.gguf` (0.9 GB). This build keeps the multi-token prediction (MTP) layers, so the MTP speed-up can be tested without a second download.

| | Qwen3.6-35B-A3B (main pick) | Gemma 4 12B official (fallback) |
|---|---|---|
| Agent ability | Strongest that fits. Vendor: SWE-bench Verified 73.4, Terminal-Bench 2.0 51.5, MCP-Atlas 62.8 | Vendor: tau2 69.0. Some reports of malformed tool calls |
| Generation | 45–50 tok/s measured here (Heretic build, same size) | ~33–37 tok/s |
| Prompt reading | ~400 tok/s published for a 3060 with experts on the CPU **[verify]** | ~1,150 tok/s published |
| Memory | ~10 GB VRAM + ~11.6 GB RAM | ~8 GB VRAM, little RAM |
| Vision | Yes | Yes |

Ruled out:
- **Gemma 4 26B-A4B:** about the same tool score as the 12B, but needs offload.
- **Qwen3.6-27B and Gemma 4 31B:** too big for 12 GB.
- **gpt-oss-20b:** no vision.
- **October 2026 releases:** no agent track record yet.

**The one real risk is voice delay.** Reading a 3k-token prompt from scratch at ~400 tok/s takes ~7 s. Normally the start of the prompt is cached, so a voice turn only reads its few new tokens. Stage 2 measures whether the cache holds in real use.

## 3. How it fits together after the change

```
Open WebUI picker / phone / briefing job
   ├─ ultron         ┐
   ├─ ultron-think   ├─ LiteLLM: three names, one backend model ("ultron"), different settings
   └─ ultron-agent   ┘
                          │
                    llama-server, router mode (kept)
                      ├─ ultron              Qwen3.6-35B-A3B official + vision, loaded at startup
                      ├─ old-gemma-12b       dormant preset, never requested
                      └─ old-qwen-heretic    dormant preset, never requested
```

- **The three names stay.** Chat links (`/?models=ultron`), the briefing job, the profile script and the benchmarks keep working unchanged. Each name keeps its own system prompt and tools in Open WebUI, so web search stays on `ultron`/`ultron-think` and the terminal stays on `ultron-agent`, as today.
- **The backend model is named `ultron`.** Scripts that call llama-server directly (`bench-assistant.py`, the GPU broker) need no change.
- **Router mode stays,** so the old models can remain as presets that never load unless asked for by name. With `--models-max 1`, a request for an old name would swap them in, which is the "just in case" path.
- **Switching between the three names is not a swap any more.** It only re-reads the prompt when the system prompts differ. `cache-ram` (2 GB, already set) keeps recent prompt caches in RAM **[verify that it restores them]**.
- **Per-name settings in LiteLLM:**

| Name | Thinking | Samplers | Timeout |
|---|---|---|---|
| `ultron` | off | Qwen's non-thinking values (temp 0.7, top-p 0.8, top-k 20) | default |
| `ultron-think` | on | Qwen's thinking values (temp 0.6, top-p 0.95, top-k 20) **[verify against the model card]** | default |
| `ultron-agent` | off | non-thinking values | 900 s |

## 4. Stages

A subagent on a cheaper model runs stages 0–2 from exact briefs. I review every number before reporting. You decide at the end of stage 2.

### Stage 0: download (~24 GB, F: has 61 GB free)

1. Download the two files above into `models/` and check their SHA-256 against Hugging Face.
2. Nothing else changes. The stack keeps running on today's setup.

### Stage 1: speed and fit (`llama-bench` plus a test preset)

Add a dormant `[ultron-next]` preset to `models.ini` for testing. Loading it unloads Gemma, so phone chat is slow during test runs.

**Other users of the model server:** the chess-coach app (`F:\Documents\GitHub\chess-coach`) calls `ultron` directly at `127.0.0.1:8080/v1` with JSON-schema output. Before stage 1 and before stage 3, tell that session to pause its LLM tests: a call to `ultron` mid-benchmark swaps Gemma back in. After stage 3, check that its JSON-schema requests still work.

| Measure | Settings tried |
|---|---|
| Fit: VRAM, RAM, load time | `n-cpu-moe` 24 / 26 / 28, with the vision file loaded. The monitor runs on the 3060 (the i5-14600KF has no built-in graphics), so 24 may not fit |
| Prompt reading speed | `-ub` / `-b` 512 / 1024 / 2048 |
| Generation speed | 0, 4k and 16k tokens of context |
| Context | 32k (today's agent value); 48k only if VRAM allows |
| MTP | off vs `--spec-type draft-mtp --spec-draft-n-max 1` and `2`. Kept only if faster overall at the chosen `n-cpu-moe` |

### Stage 2: quality and real-use delay (through the gateway as `ultron-next`)

**Changed for the unattended overnight run (2026-11-22):** stage 3 goes first, and these tests run on the live names. They then use the real Open WebUI prompts, tools and memory, and no temporary `ultron-next` gateway entry is needed. A hard failure triggers the rollback in §5. The agent eval tasks T1–T3 need ComfyUI, so only T4 is run, compared with the Heretic baseline in `logs/agent-eval` (T4 mode A: pass, 11 rounds, 2.2 min).

| Test | How | Pass mark |
|---|---|---|
| Time to first token, one-line chat (cached) | `bench-assistant.py`, 10 runs, median | ≤ 1.5 s (PLAN-ASSISTANT target) |
| Voice: model to first sentence | Voice-turn timing as in PLAN-ASSISTANT §5 | ≤ 1.2 s (today's Gemma: 0.6–1.2 s) |
| Cache survives background calls | Chat turn, then a title request, then the next turn: time the next turn | Next turn still ≤ 1.5 s |
| Cold prompt (3k tokens, uncached) | Same script | Recorded; ≤ 5 s hoped |
| Tool choice | `test-tools.ps1` | 6/6 (as today) |
| Agent tasks | `scripts/agent-eval/run_eval.py`, official vs Heretic | Official ≥ Heretic |
| Thinking mode | `test-modes.ps1` | Reasoning appears only on `ultron-think` |
| Memory | `test-memory.ps1` | 5/5 |
| Vision | 3 sample images (receipt, letter, screenshot) | All read correctly |
| Free system RAM, full stack running | Grafana | ≥ 4 GB |
| Generation | Stage 1 numbers | ≥ 30 tok/s |

**Go/no-go (you decide):**
- **All pass:** go to stage 3.
- **Only voice delay fails:** try the levers below, then rerun stage 2.
- **Still failing:** run the same plan with Gemma 4 12B official as the single model (~8 GB download).

Voice delay levers, in order:
1. A larger `-ub`.
2. Check that `cache-ram` restores the chat prefix after a title request.
3. Turn off title generation.
4. `parallel = 2`, so background calls get their own slot (costs context).

### Stage 3: switch over

1. **Backup:** copy the Open WebUI database (`webui.db.bak-<time>-one-model`) and note the git commit to roll back to.
2. **`scripts/models.ini`:**
   - `[ultron]` becomes the official Qwen with the vision file and the chosen stage 1 settings, `load-on-startup = true`.
   - Today's Gemma entry is renamed `[old-gemma-12b]` and today's agent entry `[old-qwen-heretic]`. Both lose `load-on-startup`.
   - The test preset `[ultron-next]` is removed.
3. **`compose/litellm-config.yaml`:** all three names point to `openai/ultron` with the settings from §3.
4. **Open WebUI per-model settings** (admin pages; record them in the README):
   - Vision on for all three names.
   - Everything else stays as it is: tools, the web search / terminal split, memory, system prompts and the profile block.
5. **`scripts/start-all.ps1`:**
   - Stop starting `model-idle.ps1` (comment out with a note; the script stays).
   - The GPU broker keeps starting. It is idle and costs nothing, and the ComfyUI skill still works through it if you ever use it again. Reload after a ComfyUI job is now ~25 s instead of ~13 s.
6. Restart the stack.

### Stage 4: check end to end

1. Phone chat and a voice call over mobile data.
2. Briefing dry run.
3. An `ultron-agent` terminal task.
4. A photo of a receipt.
5. Rerun `test-tools.ps1` and `test-memory.ps1`.

### Stage 5: documentation

- **README:** models table, agent sandbox note, the `model-idle.ps1` line, Open WebUI settings.
- **PLAN-ASSISTANT.md:** speed table and the "no swaps in background jobs" note.
- **PLAN-DIGEST.md:** the models line; the deep reads no longer need a swap.
- **`docs/index.html`:** models section.

## 5. Rollback

Nothing is deleted, so rolling back is:

1. `git revert` the switch-over commit (`models.ini`, `litellm-config.yaml`, `start-all.ps1`).
2. Restore the Open WebUI database copy.
3. Restart the stack.

The old model files stay in `models/` (~29 GB). Remove them later only if you decide to.

## 6. Out of scope, worth doing later

- **Rerun the stage 5 planner test** (PLAN-ASSISTANT §5) on the official model. The Heretic build ignored the planning contract in 0 of 4 runs, and the uncensoring may be part of why.
- **Raise context above 32k** if stage 1 leaves VRAM free.

## 7. Resource budget

| Resource | Now | After |
|---|---|---|
| VRAM | Gemma ~8–9 GB, or agent ~10.2 GB during agent work | ~10–11 GB, always (with vision) **[verify]** |
| System RAM held by the model | ~0 (Gemma); ~11.6 GB during agent work | ~11.6 GB, always |
| Free system RAM, full stack | ~8.9 GB with the agent loaded | same, ≥ 4 GB target |
| Disk (`models/`) | ~29 GB | ~53 GB (old files kept) |
| Swap waits | ~30 s in, ~13 s back | none |

## 8. Results (2026-11-22)

The switch is live. Detailed logs: `logs/one-model-stage1.md` and `logs/one-model-stage2.md`.

**Chosen settings** (preset `ultron` in `scripts/models.ini`):
- Model `models/Qwen3.6-35B-A3B-UD-Q4_K_M-MTP.gguf` (Q4_K_M from `unsloth/Qwen3.6-35B-A3B-MTP-GGUF`), vision file `models/mmproj-Qwen3.6-35B-A3B-F16.gguf`.
- `n-cpu-moe 28`, 49152 context, ubatch 1024 / batch 2048.
- MTP speculative decoding (`draft-mtp`, n-max 2).
- Qwen non-thinking samplers: temp 0.7, top-p 0.8, top-k 20, presence penalty 1.5.
- Loaded at startup, never swapped. `ultron-think` (thinking on, temp 1.0, top-p 0.95) and `ultron-agent` (presence penalty 0, 900 s timeout) point to the same model.
- Old presets `old-gemma-12b` and `old-qwen-heretic` stay in `models.ini` and load only when requested by name.

**Stage 2 results:**

| Test | Target | Measured | Result |
|---|---|---|---|
| TTFT, one-line chat | ≤ 1.5 s | cached 0.33 s; uncached 1.38 s (Gemma 0.43–0.51 s / 3.5–4.5 s) | Pass |
| Voice: model to first sentence | ≤ 1.2 s | median 0.76 s | Pass |
| Cache after a title call | ≤ 1.5 s | 0.86 s | Pass |
| Cold prompt, 3k tokens | ≤ 5 s hoped | ~6–8 s (~400–600 tok/s) | Recorded, over the hope |
| Tool choice | 6/6 | `test-tools.ps1` 5/5; JSON-schema output 3/3 | Pass |
| Agent T4 | ≥ Heretic | 2/2 pass, 5 rounds, ~15 s (Heretic: 11 rounds, 2.2 min) | Pass |
| Thinking mode | Reasoning only on `ultron-think` | as intended | Pass |
| Memory | 5/5 | Memory and Google calendar/tasks tools ran correctly in a real Open WebUI chat; `test-memory.ps1` cannot pass as written | Pass in a real chat; script limitation |
| Vision | All read correctly | Read a receipt correctly | Pass |
| Free system RAM | ≥ 4 GB | ~3.4–3.9 GB | Slightly below |
| Generation | ≥ 30 tok/s | ~52–57 tok/s with MTP (44 without) | Pass |

Other numbers: VRAM ~11.1–11.3 GB of 12; llama-server working set ~14 GB; load ~25–35 s; briefing dry run 19.9 s; after a ComfyUI job the model reloads in ~25–35 s.

**Load mode:** memory-mapped loading was tried and rejected. It gave 44 tok/s and less free RAM.

**Known open items:**
- Free RAM with the full stack is slightly under the 4 GB target.
- The one-line chat prompt is 4,945 tokens with all tools, over the 4k target (Qwen's tokenizer counts more tokens than Gemma's; it was 3,680 before).
- The briefing news section returned "no results". This is the search side, not the model.
- `scripts/test-memory.ps1` needs the chat flow: a bare `/api/chat/completions` call without a `chat_id` returns raw `tool_calls` that Open WebUI does not execute. `logs/one-model-tests/chatflow.py` shows the working flow.
