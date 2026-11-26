# paper-digest: module contracts

The product plan is `logs/plans/paper-digest.md` (read sections 4–9 before coding). This file
fixes the interfaces so modules can be written in parallel. Python 3.12, `requests`, `PyYAML`;
add other dependencies to `requirements.txt` with exact pinned versions.

Rules for every module:
- Code owns the order; every model call goes through `engine.llm_json` (see engine.py), with a
  JSON schema and a `check` function. Paper or web text passed to the model is wrapped with
  `engine.untrusted()`.
- Settings live in `config.yaml`, prompts in `prompts/<name>.md`, never hard-coded in Python.
- Each function that talks to the network fails on its own and logs; it never takes down the run.
- Plain, short English in every user-visible string. No emoji.
- Unit tests in `tests/test_<module>.py` (unittest, no network: use fixtures in `tests/fixtures/`).

## Data shapes

**Paper** (dict), produced by `collect.py`:
```
{ "id": "arxiv:2511.01234" | "url:<sha1 of url>[:12]",
  "arxiv_id": "2511.01234" | None, "title": str, "authors": [str], "abstract": str,
  "url": abs page URL, "pdf_url": str | None, "html_url": "https://arxiv.org/html/<id>" | None,
  "categories": [str], "published": "YYYY-MM-DD", "comment": str (arXiv comment field, may name a venue),
  "sources": ["arxiv", "hf", "queue"], "hf_upvotes": int | None,
  "s2": {"citations": int, "influential": int, "max_author_hindex": int | None, "venue": str | None,
         "references": [{"title": str, "abstract": str | None}]} | None,
  "labs": [str]   # watched labs matched in authors/affiliations/comment, may be empty
}
```

**Scored** (dict), produced by `score.py`: the Paper plus
```
{ "scores": {"career_fit": 0-3, "expert_expectation": 0-3, "foundational": 0-3,
             "impact": 0-3, "evidence": 0-3, "applicability": 0-3},
  "track": "genai" | "robotics" | "other_ai" | "mechatronics",
  "one_liner": str (what it is, <= 160 chars), "why": str (why it might matter to the user, <= 160 chars),
  "total": float (weighted, from config), "level": "deep" | "overview" | "brief" | "skip",
  "number": int (1-based position in today's digest, set by select) }
```

## Modules and owners

| File | Contents |
|---|---|
| `engine.py` | Done. `cfg()`, `prompt(name)`, `untrusted(text)`, `Run`, `llm_json(...)`, `StepFailed` |
| `history.py` | SQLite at `STATE_DIR/history.db`. `History()`: `seen(id)->bool`, `add(scored, digest_date)`, `get(id)->dict|None`, `feedback_add(id, level, source)`, `feedback_examples(n)->[{title, one_liner, level}]`, `concepts()->[str]`, `concepts_add([str], paper_id)`, `drive_folder(id)->str|None`, `set_drive_folder(id, folder_id, url)`, `next_paper_number(year, month)->int`, `set_report(id, markdown, chat_id)`, `report(id)->{markdown, chat_id}|None`, `queue_add(url, source)`, `queue_next()->dict|None`, `queue_done(qid, ok, note)`, `digest_paper(date, number)->id|None` |
| `collect.py` | `collect(run, cfg, history, today) -> [Paper]`: arXiv API (categories in config, last listing day), HF Daily Papers API, merge duplicates by arxiv id, drop `history.seen`, keyword prefilter (config `topics.*.keywords`), Semantic Scholar batch enrichment (`/graph/v1/paper/batch`, no key; tolerate 429 by skipping), lab matching. `paper_from_url(url) -> Paper` for queued links (arXiv abs/pdf/html links → arXiv API lookup; other PDF URLs → minimal Paper with pdf_url). Weekend rule: `select` stores relevant papers that lost only on budget with level `runner_up`; when arXiv has no new listing, `collect` adds `history.runners_up(days=7)` (add that method) to the HF papers. |
| `score.py` | `score(run, cfg, papers, history) -> [Scored]` (batches of 10, model, schema enforced, reason lines), `select(cfg, scored) -> [Scored]` (code: weights, deep gate foundational==3 and career_fit>=2, budget minutes per level from config, 50/50 genai/robotics balance, other_ai/mechatronics capped at brief unless total >= config threshold, assigns `number`). |
| `fulltext.py` | `fetch(paper) -> {"text": str, "sections": [{"title": str, "text": str}], "source": "html"|"pdf", "pdf_bytes": bytes|None}` or raises `FulltextError`. arXiv HTML first (keep section headings, table captions, equations as LaTeX alt text), PDF→text fallback (pypdf). Check: > 2000 words and has an abstract/intro and an experiments/results-like section. `chunks(ft, max_tokens) -> [str]` split on section lines (estimate tokens as chars/3.5). |
| `verify.py` | `numbers_in(text)->[str]`, `unsupported_numbers(text, source)->[str]` (numbers like 12.3, 45%, 7B, 1,024 present in text but not in source; ignore list numbers 1-10, years, section numbers), `quote_ok(quote, source)->bool` (normalised fuzzy, >= 0.9 of tokens in order), `refs_ok(text, sections)->[bad refs]` (§N, Table N, Fig. N, Eq. N must exist in the paper). |
| `reports.py` | `deep_read(run, cfg, paper, history) -> {"markdown", "short_title", "concepts":[str], "fulltext": ft, "stats": {...}}` = W3 steps 1–8 (plan §6), A–M format (plan §5.1). `overview(run, cfg, scored) -> {"markdown", "fulltext": ft|None}` (sections A,B,C,D,G,H,J,L; full text when fetchable, abstract-only fallback marked as such). Writer model for deep-read steps 6–8 = `cfg["writer_model"]`. |
| `common.py` | Open WebUI + ntfy helpers copied from `services/assistant-cron/briefing.py` (`webui_api`, folder lookup/creation, `create_chat(title, user_line, text, system=None, folder=name) -> chat_id`, `get_chat(id)`, `push(title, body)`). |
| `digest.py` | Entry point and scheduler. `--run-now [--dry-run] [--no-push] [--limit N]`, `--queue URL`, `--doc CHAT_ID`, default = long-lived scheduler (02:00 nightly run, hard stop 05:45, push 06:10, poll the "Papers" folder every 2 min for commands, process the queue, HTTP queue endpoint on :8095 with `PAPER_QUEUE_KEY`), composes the digest markdown, creates the chats, writes heartbeat `/tmp/heartbeat`. |
| `drive.py` | Google Drive (`drive.file` scope) via the shared `/mcp/google_auth.GoogleSession`. `enabled() -> bool` (False and a clear log line when the scope is missing), `paper_folder(history, paper, date) -> (folder_id, url)` creating `Phase 9 — Ongoing/<YYYY>/<MM - Month>/<N - Short name>/`, `upload_pdf(folder_id, name, data)`, `upsert_doc(folder_id, title, docx_bytes) -> url` (upload converting to Google Doc, replace existing of same name). |
| `doc.py` | W7 `/doc`: `make_doc(run, cfg, history, chat_id) -> url`: report + follow-up Q&A from the chat → model maps Q&A to sections (JSON) → rewrite affected sections → verify numbers/refs → Open questions → markdown → pandoc → docx (equation native + matplotlib mathtext image, data-flow diagram as image) → `drive.upsert_doc`. |
| `tools/paper_reader.py` (repo root `tools/`) | Open WebUI tool: `read_paper(url)` POSTs to `http://paper-digest:8095/queue` with the key valve; returns "Queued; you'll get a push when the report is ready." |

## Chats

- Folder **"Papers"** (Open WebUI). Digest chat title `Papers · Tue 25 Nov`; Deep-read chat title
  `Paper · <short title>`. Model `ultron`.
- Deep-read chat carries a chat-level system prompt = `prompts/tutor.md` (follow-up rules and the
  shortcuts `/eli5 /visual /deep /code /compare /quiz /defend /doc`) + the paper's full text in
  `<untrusted>` tags. `/doc` in that chat is acted on by `digest.py` polling (code, not the model);
  the tutor prompt tells the model to reply only "Saving the updated report to Drive; you'll get a push."
- Digest chat carries a short system prompt explaining the reply commands. Poll parser (code):
  lines matching `^(deep|overview|brief|skip)\s+(\d+)$` or `^(\d+)\s+(deep|overview|brief|skip)$`
  (case-insensitive) → `history.feedback_add`; `deep` also queues a Deep read of that paper.
