"""Nightly paper digest: collect, score, select, write reports, deliver as Open WebUI chats and one push.

Run with no arguments: a long-lived scheduler (nightly run at run_at, push at push_at, polling of the
"Papers" chat folder for replies and /doc, a queue worker, and an HTTP endpoint for pasted links).
One-off modes: `--run-now [--dry-run] [--no-push] [--limit N] [--no-deep]`, `--queue URL`, `--doc CHAT_ID`.
Code owns the order (see DESIGN.md); the model only does the narrow steps inside the other modules.
"""

import argparse
import hmac
import importlib
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import common
import engine

log = logging.getLogger("paper-digest")

HEARTBEAT = Path("/tmp/heartbeat")
HTTP_PORT = 8095
SYSTEM_CAP = 60000       # chars of chat system prompt (tutor rules plus paper text)
STATE_FILE = "digest_state.json"
TRACKS = [("genai", "GenAI"), ("robotics", "Robotics"), ("other_ai", "Other AI"), ("mechatronics", "Mechatronics")]
SCORE_LABELS = [("career_fit", "fit"), ("expert_expectation", "expert"), ("foundational", "found"),
                ("impact", "impact"), ("evidence", "evid"), ("applicability", "apply")]
CMD_A = re.compile(r"^(deep|overview|brief|skip)\s+(\d+)$", re.I)
CMD_B = re.compile(r"^(\d+)\s+(deep|overview|brief|skip)$", re.I)

RUN_LOCK = threading.Lock()    # one heavy job (nightly run, queued deep read, /doc) at a time
STATE_LOCK = threading.Lock()


def mod(name):
    """Sibling module by name, imported on first use (tests put fakes into sys.modules)."""
    return sys.modules.get(name) or importlib.import_module(name)


def cut(text, n) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def plural(n, word) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def tz_of(c) -> ZoneInfo:
    return ZoneInfo(c.get("timezone", "UTC"))


# ---------------------------------------------------------------------------- state
def load_state() -> dict:
    try:
        d = json.loads((engine.STATE_DIR / STATE_FILE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning("digest state unreadable (%s); starting empty", cut(e, 100))
        return {}


def update_state(fn) -> dict:
    """Read, change (fn(state) mutates it), write back; safe across threads."""
    with STATE_LOCK:
        st = load_state()
        fn(st)
        engine.STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = engine.STATE_DIR / (STATE_FILE + ".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(engine.STATE_DIR / STATE_FILE)
        return st


# ---------------------------------------------------------------------------- time helpers
def at_time(now: datetime, text) -> datetime:
    h, m = str(text).split(":")
    return now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


def in_quiet(c, now: datetime) -> bool:
    start, end = at_time(now, c.get("quiet_start", "05:45")), at_time(now, c.get("quiet_end", "06:15"))
    return start <= now < end if start <= end else (now >= start or now < end)


# ---------------------------------------------------------------------------- digest text
def short_name(title) -> str:
    t = re.split(r"[:\-–—]", str(title), maxsplit=1)[0].strip() or str(title)
    return cut(t, 40)


def cut_block(text, n) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def tldr(markdown) -> str:
    """Section A of a report (its TL;DR); the start of the report if the section is not found."""
    lines = markdown.splitlines()
    for i, ln in enumerate(lines):
        if "tl;dr" in ln.lower():
            first = re.sub(r"^[\s#>*A\.\)\-]*\**\s*TL;DR\s*\**\s*[—:\-–]*\s*", "", ln, flags=re.I).strip(" *")
            out = [first] if first else []
            for nxt in lines[i + 1:]:
                if re.match(r"^\s*(#+\s*)?\**\s*B[\.\)]", nxt) or (nxt.startswith("#") and out):
                    break
                if nxt.strip() or out:
                    out.append(nxt.rstrip())
            text = "\n".join(out).strip()
            if text:
                return cut_block(text, 600)
    return cut_block(markdown.strip(), 400)


def scores_line(p) -> str:
    s = p.get("scores") or {}
    if not s:
        return ""
    parts = " · ".join(f"{lab} {s.get(k, 0)}" for k, lab in SCORE_LABELS)
    return f"scores: {parts} = {float(p.get('total') or 0):.1f}"


def source_notes(c, papers, today: date) -> list[str]:
    notes = []
    src = {s for p in papers for s in p.get("sources", [])}
    if "arxiv" not in src:
        notes.append("no new arXiv listing today (weekend)" if today.weekday() >= 5 else "arXiv unavailable tonight")
    if c.get("hf_daily_papers") and "hf" not in src:
        notes.append("Hugging Face unavailable tonight")
    if c.get("semantic_scholar") and papers and not any(p.get("s2") for p in papers):
        notes.append("Semantic Scholar unavailable tonight")
    return notes


def counts(items) -> dict:
    out = {"deep": 0, "overview": 0, "brief": 0}
    for p in items:
        if p["level"] in out:
            out[p["level"]] += 1
    return out


def counts_all(items) -> dict:
    out: dict[str, int] = {}
    for p in items:
        lv = p.get("level", "?")
        out[lv] = out.get(lv, 0) + 1
    return out


def counts_text(cn) -> str:
    return f"{plural(cn['deep'], 'deep read')}, {plural(cn['overview'], 'overview')}, {plural(cn['brief'], 'brief')}"


def compose_digest(c, items, reports, chats, notes, extra_notes=(), dry=False) -> str:
    """The digest chat text. items: shown papers (level deep/overview/brief, with number);
    reports: {paper id: {"markdown": ...}}; chats: {paper id: chat id} of the deep-read chats."""
    show = bool(c.get("show_scores"))
    items = sorted(items, key=lambda p: p.get("number", 0))
    head = f"**Tonight: {counts_text(counts(items))}.**"
    if notes:
        head += " Sources: " + "; ".join(notes) + "."
    if extra_notes:
        head += " " + " ".join(extra_notes)
    out = [head]
    if not items:
        out.append("No new papers made the cut tonight.")

    deep = [p for p in items if p["level"] == "deep"]
    if deep:
        out.append("## Deep reads")
        for p in deep:
            md = (reports.get(p["id"]) or {}).get("markdown", "")
            block = [f"**{p['number']}. {p['title']}**", tldr(md) if md else (p.get("one_liner") or "")]
            if chats.get(p["id"]):
                block.append(f"[Open the deep-read chat]({common.chat_path(chats[p['id']])})")
            else:
                block.append("The deep-read chat would be created on a real run." if dry
                             else "The deep-read chat could not be saved tonight.")
            if show and scores_line(p):
                block.append(scores_line(p))
            out.append("\n\n".join(block))

    ov = [p for p in items if p["level"] == "overview"]
    if ov:
        out.append("## Overviews")
        for p in ov:
            md = (reports.get(p["id"]) or {}).get("markdown", "") or p.get("one_liner", "")
            md = re.sub(r"^# .*\n+", "", md.lstrip())       # the paper title is already the heading
            md = re.sub(r"(?m)^### ", "#### ", md)           # sections sit below the paper's ### heading
            note = f" ({p['note']})" if p.get("note") else ""
            link = f"[arXiv]({p['url']})" if p.get("url") else ""
            sc = scores_line(p) if show else ""
            out.append("\n\n".join(x for x in [f"### {p['number']}. {p['title']}{note}", link, md, sc] if x))

    br = [p for p in items if p["level"] == "brief"]
    if br:
        out.append("## Briefs")
        known = dict(TRACKS)
        for key, label in TRACKS:
            group = [p for p in br if (p.get("track") if p.get("track") in known else "other_ai") == key]
            if not group:
                continue
            lines = [f"**{label}**"]
            for p in group:
                title = f"[{p['title']}]({p['url']})" if p.get("url") else p["title"]
                note = f" ({p['note']})" if p.get("note") else ""
                lines.append(f"{p['number']}. {title}{note}: {p.get('one_liner', '')}\n   Why: {p.get('why', '')}")
                if show and scores_line(p):
                    lines.append(f"   {scores_line(p)}")
            out.append("\n".join(lines))

    out.append("---\nReply in this chat with `deep 3` to get a full read of paper 3, or `3 skip` if it was not worth "
               "showing; the next nights learn from your replies. In a deep-read chat, type `/doc` to save the "
               "updated report to Google Docs in Drive.")
    return "\n\n".join(out)


def build_system(tutor, text, cap=SYSTEM_CAP) -> tuple[str, bool]:
    """Tutor prompt plus the paper text in <untrusted> tags, at most `cap` chars. Returns (prompt, truncated)."""
    note = ("\n\nThe paper text below was cut for length. If the reader asks about a part you cannot see, "
            "say that it was cut.")
    budget = cap - len(tutor) - len(note) - len(engine.untrusted("")) - 80
    truncated = len(text) > budget
    body = text[: max(budget, 0)] + "\n[... text cut here ...]" if truncated else text
    return tutor + (note if truncated else "") + "\n\nPaper text:\n" + engine.untrusted(body), truncated


# ---------------------------------------------------------------------------- delivery pieces
def paper_pdf(p, ft):
    data = (ft or {}).get("pdf_bytes")
    if data:
        return data
    url = p.get("pdf_url")
    if not url:
        return None
    r = requests.get(url, timeout=60, headers={"User-Agent": engine.cfg().get("user_agent", "ultron-paper-digest/1.0")})
    r.raise_for_status()
    return r.content if r.content[:4] == b"%PDF" else None


def save_to_drive(H, p, ft, day: date):
    """PDF into the paper's Drive folder. Every failure is logged and swallowed."""
    try:
        drive = mod("drive")
        if not drive.enabled():
            return
        folder_id, url = drive.paper_folder(H, p, day)
        data = paper_pdf(p, ft)
        if data:
            drive.upload_pdf(folder_id, f"{p.get('short_title') or short_name(p['title'])}.pdf", data)
        log.info("Drive: saved %s (%s)", p["id"], url)
    except Exception as e:
        log.warning("Drive save failed for %s (%s)", p.get("id"), cut(e, 150))


def deep_chat(c, p, d):
    """The deep-read chat for one paper; returns its id, or None if it could not be saved."""
    ft = d.get("fulltext") or {}
    text = ft.get("text") or p.get("abstract", "")
    system, truncated = build_system(engine.prompt("tutor"), text)
    header = ""  # the report itself starts with the title, authors and link
    if truncated:
        header += (f"_Only the first part of the paper text ({len(system):,} of {len(text):,} characters) "
                   "is kept for follow-up questions._")
    title = c.get("deep_title", "Paper · {short_title}").format(
        short_title=d.get("short_title") or short_name(p["title"]))
    try:
        return common.create_chat(title, f"Deep read: {p['title']}", "\n\n".join(x for x in (header, d["markdown"]) if x), system=system,
                                  folder=c.get("chat_folder", "Papers"),
                                  model=engine.pick_chat_model(c.get("deep_chat_model")))
    except Exception as e:
        log.warning("deep-read chat not saved for %s (%s)", p["id"], cut(e, 150))
        return None


def record_paper(H, p, level, day: date):
    try:
        H.add({**p, "level": level}, day.isoformat())
    except Exception as e:
        log.warning("history.add failed for %s (%s)", p.get("id"), cut(e, 150))


def save_report(H, p, d, chat_id):
    try:
        H.set_report(p["id"], d["markdown"], chat_id)
        if d.get("concepts"):
            H.concepts_add(d["concepts"], p["id"])
    except Exception as e:
        log.warning("history report failed for %s (%s)", p.get("id"), cut(e, 150))


# ---------------------------------------------------------------------------- the nightly run
class Opts:
    def __init__(self, dry_run=False, no_push=False, limit=None, no_deep=False):
        self.dry_run, self.no_push, self.limit, self.no_deep = dry_run, no_push, limit, no_deep


def run_night(opts: Opts, now: datetime | None = None) -> dict:
    c = engine.cfg()
    tz = tz_of(c)
    now = now or datetime.now(tz)
    today = now.date()
    run = engine.Run("nightly")
    H = mod("history").History()
    dl = at_time(now, c.get("hard_stop", "05:45"))
    deadline = dl if now < dl else None   # a run started after the hard stop (--run-now by day) has none

    def late():
        return deadline is not None and datetime.now(tz) >= deadline

    got = mod("collect").collect(run, c, H, today)
    papers, collect_notes = got if isinstance(got, tuple) else (got, [])
    if opts.limit:
        papers = papers[: opts.limit]
    run.record("collect", ok=True, papers=len(papers))
    scored = mod("score").score(run, c, papers, H) if papers else []
    selected = mod("score").select(c, scored) if scored else []
    run.record("select", ok=True, levels=counts_all(selected))
    by = {lv: [p for p in selected if p.get("level") == lv] for lv in ("deep", "overview", "brief", "skip")}
    reports: dict[str, dict] = {}

    def demote(p, level, why):
        p["level"], p["note"] = level, why
        by[level].append(p)

    reports_mod = mod("reports")
    for p in list(by["deep"]):   # Deep reads, clock-checked; failures fall back to overviews
        by["deep"].remove(p)
        if opts.no_deep:
            demote(p, "overview", "deep reads are off")
            continue
        if late():
            demote(p, "overview", "time ran out")
            continue
        try:
            d = reports_mod.deep_read(run, c, p, H)
            p["short_title"] = d.get("short_title") or short_name(p["title"])
            reports[p["id"]] = d
            by["deep"].append(p)
        except Exception as e:
            log.warning("deep read failed for %s (%s)", p["id"], cut(e, 150))
            run.record("deep_read", ok=False, paper=p["id"], error=str(e)[:200])
            demote(p, "overview", "deep read failed")

    for p in list(by["overview"]):   # Overviews; failures fall back to briefs
        by["overview"].remove(p)
        if late():
            demote(p, "brief", "time ran out")
            continue
        try:
            o = reports_mod.overview(run, c, p)
            p["short_title"] = short_name(p["title"])
            reports[p["id"]] = o
            by["overview"].append(p)
        except Exception as e:
            log.warning("overview failed for %s (%s)", p["id"], cut(e, 150))
            run.record("overview", ok=False, paper=p["id"], error=str(e)[:200])
            demote(p, "brief", "overview failed")

    shown = by["deep"] + by["overview"] + by["brief"]
    notes = list(collect_notes) or source_notes(c, papers, today)
    demoted = [p for p in shown if p.get("note")]
    extra = [f"{plural(len(demoted), 'paper')} shown at a lower level ("
             + "; ".join(sorted({p['note'] for p in demoted})) + ")."] if demoted else []

    chats: dict[str, str] = {}
    digest_id = None
    if not opts.dry_run:
        save_levels = set(c.get("drive_save_levels", ["deep", "overview"]))
        for p in by["deep"] + by["overview"]:
            if p["level"] in save_levels:
                save_to_drive(H, p, reports[p["id"]].get("fulltext"), today)
        for p in by["deep"]:
            cid = deep_chat(c, p, reports[p["id"]])
            if cid:
                chats[p["id"]] = cid

    text = compose_digest(c, shown, reports, chats, notes, extra, dry=opts.dry_run)
    if opts.dry_run:
        print(text)
    top = shown[0] if shown else None
    body = counts_text(counts(shown)) + (f"\nTop: {cut(top['title'], 90)}" if top else "")

    if not opts.dry_run:
        err = None
        try:
            title = c.get("digest_title", "Papers · {date:%a %d %b}").format(date=now)
            digest_id = common.create_chat(title, "Tonight's papers", text, system=engine.prompt("digest_chat"),
                                           folder=c.get("chat_folder", "Papers"), model=c.get("model", "ultron"))
            update_state(lambda st: st.setdefault("digests", {}).__setitem__(digest_id, today.isoformat()))
        except Exception as e:
            err = e
            log.error("digest chat not saved (%s)", cut(e, 200))
        for p in selected:   # every scored paper is remembered, skipped ones too, so nothing repeats
            record_paper(H, p, p.get("level", "skip"), today)
        for p in by["deep"]:
            save_report(H, p, reports[p["id"]], chats.get(p["id"]))
        for p in by["overview"]:
            save_report(H, p, reports[p["id"]], digest_id)
        if err:
            run.save()
            raise err
    path = run.save()
    log.info("run saved: %s %s", path, run.summary())
    return {"digest_chat_id": digest_id, "counts": counts(shown), "markdown": text,
            "push": {"title": "Papers ready", "body": body, "click": common.chat_url(digest_id) if digest_id else ""}}


# ---------------------------------------------------------------------------- queue (pasted links, deep upgrades)
QUEUE_TRIES = 4            # a link that keeps hitting temporary errors is tried this often in total
QUEUE_RETRY_MINUTES = 15   # wait between those tries


def is_transient(e: Exception) -> bool:
    """Rate limits, outages and network trouble: worth trying the link again later."""
    if type(e).__name__ == "TransientError":
        return True
    return bool(re.search(r"HTTP (429|5\d\d)|\b(429|50[234])\b|timed? ?out|Connection|unreachable|Temporary",
                          str(e), re.I))


def process_queue_item(item) -> bool:
    """One queued link: full deep read, chat, push. Never raises. Returns True on success."""
    H = mod("history").History()
    qid = item.get("id", item.get("qid"))
    url = item.get("url", "")
    c = engine.cfg()
    run = engine.Run("queue")
    try:
        paper = mod("collect").paper_from_url(url)
        paper["level"] = "deep"
        d = mod("reports").deep_read(run, c, paper, H)
        paper["short_title"] = d.get("short_title") or short_name(paper["title"])
        today = datetime.now(tz_of(c)).date()
        cid = deep_chat(c, paper, d)
        if not cid:
            raise RuntimeError("the chat could not be saved")
        if not H.get(paper["id"]):
            record_paper(H, {"scores": {}, "track": "other_ai", "one_liner": "", "why": "", "total": 0.0, **paper},
                         "deep", today)
        save_report(H, paper, d, cid)
        if "deep" in set(c.get("drive_save_levels", ["deep", "overview"])):
            save_to_drive(H, paper, d.get("fulltext"), today)
        H.queue_done(qid, True, "")
        common.push("Deep read ready", f"{cut(paper['title'], 120)}", common.chat_url(cid))
        return True
    except Exception as e:
        reason = cut(e, 140)
        tries = int(item.get("tries") or 0)
        if is_transient(e) and tries + 1 < QUEUE_TRIES:
            try:
                n = H.queue_retry(qid, reason, QUEUE_RETRY_MINUTES)
                log.warning("queued paper hit a temporary error (%s): %s; try %d of %d in %d min",
                            url, reason, n + 1, QUEUE_TRIES, QUEUE_RETRY_MINUTES)
                return False
            except Exception as e2:
                log.warning("could not requeue (%s)", cut(e2, 100))
        log.warning("queued paper failed (%s): %s", url, reason)
        try:
            H.queue_done(qid, False, reason)
            common.push("Paper not read", f"{cut(url, 80)}: {reason}", "")
        except Exception as e2:
            log.warning("could not report the failure (%s)", cut(e2, 100))
        return False
    finally:
        try:
            run.save()
        except Exception:
            pass


def queue_once(now: datetime | None = None, force=False) -> bool:
    """Process the next queued link if the box is free. Returns True if one was handled."""
    c = engine.cfg()
    now = now or datetime.now(tz_of(c))
    if not force and (in_quiet(c, now) or nightly_pending(c, now, load_state())):
        return False
    if not RUN_LOCK.acquire(blocking=False):
        return False
    try:
        item = mod("history").History().queue_next()
        if not item:
            return False
        process_queue_item(item)
        return True
    finally:
        RUN_LOCK.release()


# ---------------------------------------------------------------------------- reply commands and /doc
def parse_commands(text) -> list[tuple[str, int]]:
    out = []
    for ln in str(text).splitlines():
        ln = ln.strip().strip("`").strip()
        m = CMD_A.match(ln)
        if m:
            out.append((m.group(1).lower(), int(m.group(2))))
            continue
        m = CMD_B.match(ln)
        if m:
            out.append((m.group(2).lower(), int(m.group(1))))
    return out


def digest_date_of(row, tz) -> str:
    known = load_state().get("digests", {})
    if row["id"] in known:
        return known[row["id"]]
    created = row.get("created_at") or row.get("updated_at") or time.time()
    return datetime.fromtimestamp(created, tz).date().isoformat()


def handle_digest_chat(row, tz, handled: set) -> list[str]:
    """Applies new reply commands in a digest chat. Returns the message ids it used."""
    H = mod("history").History()
    day = digest_date_of(row, tz)
    used = []
    for m in common.chat_messages(row["id"]):
        if m["role"] != "user" or m["id"] in handled:
            continue
        used.append(m["id"])
        for level, number in parse_commands(m["content"]):
            pid = H.digest_paper(day, number)
            if not pid:
                log.info("reply %s %d: no paper %d in the %s digest", level, number, number, day)
                continue
            H.feedback_add(pid, level, "reply")
            if level == "deep":
                rec = H.get(pid) or {}
                if rec.get("level") != "deep" and rec.get("url"):
                    H.queue_add(rec["url"], "reply")
                    log.info("queued a deep read of %s", pid)
    return used


def handle_doc(row, handled: set) -> str | None:
    """If the newest user message of a deep-read chat is `/doc` and new, saves the Doc. Returns its id."""
    users = [m for m in common.chat_messages(row["id"]) if m["role"] == "user"]
    if not users or users[-1]["content"].strip() != "/doc" or users[-1]["id"] in handled:
        return None
    mid = users[-1]["id"]
    if not mod("drive").enabled():
        common.push("Drive isn't connected yet", "Run scripts/google-auth.py, then send /doc again.", "")
        return mid
    if not RUN_LOCK.acquire(blocking=False):
        return None   # busy with a long job: try again at the next poll
    try:
        run = engine.Run("doc")
        try:
            url = mod("doc").make_doc(run, engine.cfg(), mod("history").History(), row["id"])
            common.push("Report saved to Drive", cut(row.get("title", ""), 100), url or "")
        except Exception as e:
            log.warning("/doc failed (%s)", cut(e, 150))
            common.push("Report not saved", cut(e, 140), "")
        finally:
            try:
                run.save()
            except Exception:
                pass
    finally:
        RUN_LOCK.release()
    return mid


def poll(c, tz) -> None:
    st = load_state()
    since = st.get("poll_since") or time.time() - 86400
    t0 = time.time()
    rows = common.list_folder_chats(c.get("chat_folder", "Papers"), since)
    handled = set(st.get("handled", []))
    new: list[str] = []
    for row in rows:
        title = row.get("title", "")
        try:
            if title.startswith("Papers ·"):
                new += handle_digest_chat(row, tz, handled)
            elif title.startswith("Paper ·"):
                mid = handle_doc(row, handled)
                if mid:
                    new.append(mid)
        except Exception as e:
            log.warning("poll: chat %s failed (%s)", row.get("id"), cut(e, 150))

    def save(s):
        s["handled"] = (s.get("handled", []) + new)[-500:]
        s["poll_since"] = t0 - 5

    update_state(save)


# ---------------------------------------------------------------------------- scheduler
def nightly_pending(c, now: datetime, st) -> bool:
    """True when tonight's run is due but has not started (queued papers then wait for it)."""
    return (st.get("last_run") != now.date().isoformat()
            and at_time(now, c.get("run_at", "02:00")) <= now < at_time(now, c.get("hard_stop", "05:45")))


def push_due(c, now: datetime, st) -> bool:
    pend = st.get("pending_push")
    return bool(pend) and (pend.get("date") != now.date().isoformat() or now >= at_time(now, c.get("push_at", "06:10")))


def nightly_job(opts: Opts):
    with RUN_LOCK:
        try:
            res = run_night(opts)
        except Exception as e:
            log.exception("nightly run failed")
            try:
                common.push("Papers failed", cut(e, 160), "")
            except Exception:
                pass
            return
    push = {**res["push"], "date": datetime.now(tz_of(engine.cfg())).date().isoformat()}
    update_state(lambda st: st.__setitem__("pending_push", push))


def tick(c, now: datetime, last_poll: float) -> float:
    """One scheduler pass. Returns the monotonic time of the last poll."""
    st = load_state()
    if nightly_pending(c, now, st):
        update_state(lambda s: s.__setitem__("last_run", now.date().isoformat()))  # mark first: never twice
        threading.Thread(target=nightly_job, args=(Opts(),), daemon=True, name="nightly").start()
    if push_due(c, now, st):
        p = st["pending_push"]
        try:
            common.push(p["title"], p["body"], p.get("click", ""))
            update_state(lambda s: s.pop("pending_push", None))
        except Exception as e:
            log.warning("push failed (%s); will retry", cut(e, 120))
    if time.monotonic() - last_poll >= float(c.get("poll_minutes", 2)) * 60:
        last_poll = time.monotonic()
        try:
            poll(c, now.tzinfo)
        except Exception as e:
            log.warning("poll failed (%s)", cut(e, 150))
    return last_poll


def heartbeat_loop():
    while True:
        try:
            HEARTBEAT.write_text(str(time.time()))
        except Exception as e:
            log.warning("heartbeat not written (%s)", cut(e, 80))
        time.sleep(60)


def queue_loop():
    while True:
        try:
            if not queue_once():
                time.sleep(30)
        except Exception:
            log.exception("queue worker error")
            time.sleep(60)


# ---------------------------------------------------------------------------- HTTP endpoint
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/queue":
            return self._send(404, {"error": "not found"})
        key = os.environ.get("PAPER_QUEUE_KEY", "")
        if not key or not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {key}"):
            return self._send(401, {"error": "unauthorized"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            url = str(json.loads(self.rfile.read(min(n, 10000)) or b"{}").get("url", "")).strip()
        except Exception:
            return self._send(400, {"error": "bad request"})
        if not re.match(r"^https?://\S{4,2000}$", url):
            return self._send(400, {"error": "url must start with http:// or https://"})
        try:
            mod("history").History().queue_add(url, "tool")
        except Exception as e:
            log.warning("queue_add failed (%s)", cut(e, 100))
            return self._send(500, {"error": "could not queue"})
        log.info("queued %s", cut(url, 100))
        self._send(200, {"ok": True, "queued": url})

    def log_message(self, fmt, *args):
        log.debug("http " + fmt, *args)


def make_server(host="0.0.0.0", port=HTTP_PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def scheduler():
    c = engine.cfg()
    log.info("scheduler started (run %s, hard stop %s, push %s)", c.get("run_at"), c.get("hard_stop"), c.get("push_at"))
    try:
        n = mod("history").History().queue_reset_running()
        if n:
            log.info("%d queued link(s) interrupted by a restart are queued again", n)
    except Exception as e:
        log.warning("could not reset interrupted queue items (%s)", cut(e, 100))
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threading.Thread(target=make_server().serve_forever, daemon=True).start()
    threading.Thread(target=queue_loop, daemon=True).start()
    last_poll = 0.0
    while True:
        try:
            c = engine.cfg()
            last_poll = tick(c, datetime.now(tz_of(c)), last_poll)
        except Exception:
            log.exception("scheduler loop error")
        time.sleep(20)


# ---------------------------------------------------------------------------- CLI
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-now", action="store_true", help="run the nightly pipeline now")
    ap.add_argument("--dry-run", action="store_true", help="with --run-now: print the digest; no chats, Drive, history or push")
    ap.add_argument("--no-push", action="store_true", help="with --run-now: no phone push")
    ap.add_argument("--limit", type=int, help="with --run-now: use only the first N collected papers")
    ap.add_argument("--no-deep", action="store_true", help="with --run-now: Deep reads become overviews")
    ap.add_argument("--queue", metavar="URL", help="read one paper link now (deep read, chat, push)")
    ap.add_argument("--doc", metavar="CHAT_ID", help="save the updated report of a deep-read chat to Drive now")
    args = ap.parse_args()
    if args.run_now:
        res = run_night(Opts(args.dry_run, args.no_push, args.limit, args.no_deep))
        if not args.dry_run and not args.no_push:
            common.push(**res["push"])
        log.info("done: %s", res["counts"])
    elif args.queue:
        mod("history").History().queue_add(args.queue, "cli")
        queue_once(force=True)
    elif args.doc:
        print(mod("doc").make_doc(engine.Run("doc"), engine.cfg(), mod("history").History(), args.doc))
    else:
        scheduler()


if __name__ == "__main__":
    main()
