# Ultron — AI digest (papers, models, frameworks, news)

Plan date: 2026-11-21. Builds on [PLAN-ASSISTANT.md](PLAN-ASSISTANT.md) (pushes, briefing job, Open WebUI API key).
Items marked **[verify]** are untested on this PC.

## 1. Goal

Every morning Ultron prepares an AI digest while you travel to work, so it is waiting when you reach the office:

- **Papers:** new research in your four areas, with **one paper read in depth every day** using a fixed, multi-step reading workflow.
- **Models:** new open-weight models, and whether they fit this PC (12 GB GPU, 32 GB RAM).
- **Frameworks and tools:** new releases of the software Ultron runs on, plus notable new open-source projects.
- **News:** the AI stories worth knowing, without duplicates.
- **Sunday deep dive:** 3–5 papers read in depth, plus the week's trends.

Each digest arrives as **its own chat in Ultron**, so you can keep going right there ("compare paper 2 with last week's", "can I run that model?", "set it up in ComfyUI"). A push to the iPhone carries a short teaser and links to that chat.

**Decided 2026-11-21:**

| Question | Answer |
|---|---|
| Topics | Open/local LLMs; agents and tools; image and video generation; voice and speech |
| Where reports live | Saved as Ultron chats (the digest job uses your API key) |
| Rhythm | Daily digest plus a Sunday deep dive |
| Timing | Starts 08:00 when you leave for work; ready at the office |

## 2. The main design decision: workflows are run by code, not by the model

You want each section to follow its workflow strictly. The stage 5 test answered whether a local model will do that by itself. Given a planning contract in its system prompt, the 35B agent model **never once followed it** (0 of 4 runs used `plan.py`), even on a 27-step task. A prompt is a suggestion to these models, not a rule.

So the digest is a **workflow engine in Python**:

- **Code owns the order.** Each workflow is a fixed list of steps. The model is never asked "what next?"
- **The model does one narrow job per step,** such as "score these 10 items" or "extract the claims from this section". Every step has its own short prompt.
- **Structured output:** each model step must return JSON that matches a schema. llama.cpp can enforce this while it generates (`response_format` with a JSON schema), so the model cannot produce anything else **[verify that LiteLLM passes it through]**.
- **Checks in code after every step:** right fields, length limits, and above all **every number and quote must appear in the source text**. A failed check is retried with the error message (2 tries), then that item is skipped with a note. A bad step never silently reaches you.
- **An audit log per run:** every step's input, output, checks and timing go to a JSON log, so "did it follow the workflow?" has a factual answer.
- **Editable without code:** each workflow's steps, prompts and limits live in `workflows/*.yaml` and `prompts/*.md`.

This is the same engine stage 5b describes ("an orchestrator in code"), so the planner work for the agent can reuse it later.

## 3. Sources (all free, no accounts)

| Section | Sources | Signal used to filter |
|---|---|---|
| Papers | Hugging Face Daily Papers API; arXiv API (cs.CL, cs.LG, cs.CV, cs.AI, cs.MA, cs.SD, eess.AS), last 24 h | HF upvotes; arXiv listing as the long tail |
| Models | Hugging Face Hub API, trending, by task (text generation, text-to-image/video, TTS, ASR) | Trending score, downloads, whether a GGUF / ComfyUI-ready version exists |
| Frameworks | GitHub releases of a watchlist; GitHub search for new AI repos (created in the last 7 days) | Stars; watchlist = always |
| News | Hacker News (Algolia API), r/LocalLLaMA top of day **[verify unauthenticated access]**, lab blogs by RSS (Hugging Face, Google DeepMind, Meta AI, Mistral, Qwen, OpenAI, Anthropic …) | Points, upvotes, cross-source mentions |

**Watchlist** (what Ultron runs, so updates matter to you): llama.cpp, Open WebUI, LiteLLM, ComfyUI, Kokoro-FastAPI, faster-whisper, ntfy, SearXNG, plus Wan, Qwen and Gemma model repos. It is editable in `config.yaml`.

Only public pages are fetched; nothing about you is sent. A small SQLite history (Docker volume) remembers every item already reported, so nothing repeats from one day to the next.

## 4. Workflows

### W1 — collect (code only, ~2 min, from 07:45)

Fetch every source and normalize each item to `{id, kind, title, url, source, date, summary, signals}`. Remove items already in the history, and merge duplicates across sources (same arXiv id, same repo, same link). Result: today's candidates, typically 150–300.

### W2 — triage (model, ~3 min)

1. **Hard filters (code):** signal thresholds per source, and the topic keyword prefilter.
2. **Scoring (model, batches of 10, JSON):** for each item, relevance 0–3 for each of your four topics, plus one line on why, judged against a short interest profile (your topics, your hardware, your projects).
3. **Selection (code):** the daily digest gets 1 paper for a deep read, about 5 more papers as one-liners, up to 4 models, the watchlist releases, about 3 new repos and up to 5 news items. Sunday: 3–5 deep reads.
4. **Feedback (from stage D7):** items you rated 👍/👎 in past digest chats become examples in the scoring prompt.

### W3 — read a paper in depth (the strict one, ~10–15 min per paper)

| # | Step | Who | Output | Check |
|---|---|---|---|---|
| 1 | Fetch the paper: arXiv HTML first (keeps sections and tables), PDF→text if there is none | code | clean text with section headings | over 2,000 words, has abstract and experiments |
| 2 | Map the structure: abstract, intro, method, experiments, limitations, conclusion, table captions; cut into chunks of ≤ 6k tokens along section lines | code | section list | each chunk fits the context |
| 3 | **Section notes**, one call per chunk | model | JSON: claims, method details, results `{value, metric, dataset, baseline, quote}`, stated limitations, links to code/weights | schema valid |
| 4 | **Verify** every `quote` against the paper text (fuzzy match) | code | verified notes | unverified numbers and quotes are dropped and counted |
| 5 | **Write the report** from verified notes only, into a fixed template (below) | model (agent model, 32k context) | report | all template sections present, within length limits |
| 6 | **Critique**: a second call compares the report to the notes and lists sentences not supported by them | model | list of problems | — |
| 7 | **Fix**: rewrite only the flagged sentences, or delete them | model, then code | final report | every number in the report is in the verified notes |
| 8 | **Can I run it?** Whether code and weights exist, the license, and VRAM need vs 12 GB, estimated from parameter count and quantization | code + model | short section | — |

**Report template** (identical every time, so reports can be compared):

1. **TL;DR**: two sentences.
2. **Problem**: what is broken or missing today.
3. **Key idea**: in plain words.
4. **How it works**: 3–6 bullets.
5. **Results**: verified numbers only, each with its baseline.
6. **What's actually new** compared with earlier work.
7. **Limitations**: the paper's own, plus a reviewer's view.
8. **Can I run it?** Code, weights, license, fit on this PC.
9. **Relevance to you**: Ultron, the animated series, or neither.
10. **Verdict**: read / skim / skip.
11. **Questions to ask me next.**

For follow-up questions, the paper's full text is attached to its chat as a file, so answers come from the paper itself and not from memory **[verify file upload through the API]**.

### W4 — models and releases (model, short)

- **New model:** what it is, size, license, whether a GGUF / ComfyUI version exists, fits-on-this-PC (code computes it from size and quantization), and one line on how to try it here.
- **Watchlist release:** what changed that matters for this setup, with **security fixes and breaking changes flagged first**. This also replaces "read the release notes" in the monthly update routine.
- **New repo:** what it does, stars, activity, and whether it is worth a look.

### W5 — news (model, short)

Group items about the same story, then write one line on what happened and one on why it matters, with the source link. No opinion pieces unless they score 3 on a topic.

### W6 — compose and deliver (code, plus a 1-call teaser)

1. Build the digest in Markdown, sections in a fixed order. The deep-read report is linked as its own chat.
2. Through the Open WebUI API (`ULTRON_API_KEY`), create a chat titled **"AI digest · Mon 23 Nov"** with the digest as the bot's first message, model `ultron`, inside a folder **"AI digest"** **[verify folder API]**. Each deep-read paper gets its own chat, "Paper · <short title>", with the paper attached.
3. Push to the iPhone. Title: "AI digest ready"; body: the 3 top lines; link: **that chat** (`/c/<id>`). Tapping opens the digest itself, not an empty chat. It still opens in Safari, the iOS limit noted earlier.

### W7 — Sunday deep dive

Same pipeline with 3–5 deep reads, plus a **trends** section built from the week's stored items: which topics moved, which models and repos kept coming up, and what to try this week.

## 5. Schedule and resources

| Time | What | GPU |
|---|---|---|
| 07:00 | Morning briefing (unchanged) | ~10 s |
| 07:45 | W1 collect | none |
| 08:00 | W2–W6 | ~15–25 min (Sunday ~60–90 min) |
| by ~08:30 (Sunday ~09:30) | Push: "AI digest ready" | — |

- **Models:** triage and short sections on `ultron` (Gemma 12B, fast). Deep reads on `ultron-agent` (Qwen 35B-A3B, 32k context, better at long text): one swap of about 30 s each way.
- **If you chat during the run,** your messages wait behind the current step (one request at a time). Steps are short, so the wait is seconds, except while the model swaps.
- **If ComfyUI holds the GPU,** the job waits up to 45 minutes, then sends what is ready and finishes the rest later.
- **Memory:** the job itself is small (~300 MB). The binding limit is the agent model's ~11.6 GB of RAM; it is never loaded together with a ComfyUI video job.

## 6. Build stages

| Stage | What | Done when |
|---|---|---|
| D1 | Container `services/ai-digest/`, history database, **W1 collect**, dry run that prints candidates | 3 days of dry runs: every source returns items, no item repeats |
| D2 | Workflow engine (steps, JSON schemas, checks, retries, audit log); confirm that schema-enforced output works through LiteLLM | A deliberately broken step is caught, retried and logged |
| D3 | **W2 triage** | On 40 items you rate once (10 minutes), the top 10 contain at least 8 you rated relevant |
| D4 | **W3 deep read** | On 5 known papers: all template sections present, 100 % of reported numbers traced to the paper, under 15 min each; you review 2 reports and approve the style |
| D5 | W4 models/releases, W5 news | One week of daily runs without a failed section |
| D6 | **W6 delivery** to Ultron chats and push | The chat opens from the push; follow-up questions about the paper are answered from its text |
| D7 | Feedback loop (👍/👎 in digest chats → triage examples) and the **W7** Sunday deep dive | Two Sundays delivered; triage uses your ratings |

Order: D1 → D2 → D3 → D4 → D5 → D6 → D7. A first useful digest (papers only, no deep read) exists after D3 + D6; it is worth shipping at that point and adding the rest week by week.

## 7. Safety

| Risk | Boundary |
|---|---|
| A paper or web page contains instructions for the model | Fetched text is only ever *data* inside a narrow step, wrapped in untrusted-content markers. The digest job has no tools that act: it cannot touch the calendar, mail, sandbox or files outside its own volume |
| Made-up numbers or claims | Quotes and numbers are verified against the source in code, plus the critique step. A report that fails is sent with the failing section removed and a note |
| The API key in another container | It stays in `compose/.env`, only the digest container gets it, and that container has no published port and is not on the agent network |
| Upstream APIs change or rate-limit | Each source fails on its own, and the digest says which source was missing |

## 8. Open questions

- **Digest length:** start with "readable in 5 minutes" (about 600–900 words plus the paper chat) and adjust from your feedback.
- **Watchlist additions:** anything you follow beyond the stack Ultron already runs?
- **Language:** English throughout (default), or Vietnamese summaries?

## 9. Related finding from stage 5 (2026-11-21)

During ComfyUI video jobs, the agent sandbox lost its network route to ComfyUI once (`Network is unreachable`), and free RAM dropped to about 1.3 GB. This is probably memory pressure from the Wan model, the agent model and Docker together, after the Windows update to build 26300 **[verify]**. It does not affect the digest (no ComfyUI), but the agent's video tasks need it fixed. That is a separate task.
