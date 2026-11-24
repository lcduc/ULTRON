"""W7 `/doc`: save the full report, updated with the chat's follow-ups, as a Google Doc.

Order (code owns it): chat -> Q&A pairs -> model maps each to a report section (JSON) -> affected
sections are rewritten and checked against the paper -> Open questions -> markdown -> pandoc .docx
(native equations, plus a matplotlib image of each key equation and of the data-flow diagram)
-> Drive. Needs pandoc on PATH (or PANDOC_CMD) and matplotlib.
"""

import logging
import os
import re
import shlex
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import common
import drive
import engine
import fulltext
import verify

log = logging.getLogger("paper-digest")

LETTERS = "ABCDEFGHIJKLM"
SEC = re.compile(r"^\s{0,3}(?:#{1,6}\s*)?(?:\*\*)?\s*([A-M])[.)](?:\s|\*|$)")
PART = re.compile(r"^\s{0,3}#{1,6}\s*Part\s+\d", re.I)
FENCE = re.compile(r"^\s{0,3}(```|~~~)")
NOISE_REPLY = re.compile(r"saving (the )?(updated )?report", re.I)

MAP_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["qa", "section", "resolved", "open_question"],
        "properties": {"qa": {"type": "integer"},
                       "section": {"type": "string", "enum": list(LETTERS) + ["none"]},
                       "resolved": {"type": "boolean"},
                       "open_question": {"type": "string"}}}}},
}
REWRITE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["markdown"],
    "properties": {"markdown": {"type": "string"}},
}


class DocError(Exception):
    """/doc cannot be made (not a Deep-read chat, pandoc missing, ...). The message is user-readable."""


class DriveNotConnected(DocError):
    pass


# ------------------------------------------------------------------ chat

def chat_messages(chat: dict) -> list:
    """[{role, content}] of the chat's current branch, oldest first."""
    c = chat.get("chat") or {}
    hist = c.get("history") or {}
    msgs, cur, out = hist.get("messages") or {}, hist.get("currentId"), []
    if msgs and cur:
        while cur in msgs and len(out) <= len(msgs):
            m = msgs[cur]
            out.append({"role": m.get("role"), "content": m.get("content") or ""})
            cur = m.get("parentId")
        return out[::-1]
    return [{"role": m.get("role"), "content": m.get("content") or ""} for m in c.get("messages") or []]


def follow_ups(messages: list) -> list:
    """[(question, answer)] after the first assistant message, without /doc and its reply."""
    first = next((i for i, m in enumerate(messages) if m["role"] == "assistant"), None)
    if first is None:
        return []
    out, q = [], None
    skip_reply = False
    for m in messages[first + 1:]:
        text = str(m["content"]).strip()
        if m["role"] == "user":
            if text.lower().startswith("/doc"):
                q, skip_reply = None, True
            else:
                q, skip_reply = text, False
        elif m["role"] == "assistant":
            if skip_reply or (NOISE_REPLY.search(text) and len(text) < 300):
                skip_reply = False
                continue
            if q is not None and text:
                out.append((q, text))
            q = None
    return out


# ------------------------------------------------------------------ report sections

def split_report(md: str) -> list:
    """Chunks [{key, text}]: key is a letter A-M for a section, None for anything else (title, Part headings)."""
    chunks, cur, in_fence, nxt = [], {"key": None, "lines": []}, False, 0
    for line in md.split("\n"):
        if FENCE.match(line):
            in_fence = not in_fence
        start = None
        if not in_fence:
            m = SEC.match(line)
            if m and LETTERS.index(m.group(1)) >= nxt:
                start = m.group(1)
            elif PART.match(line):
                start = ""
        if start is not None:
            chunks.append(cur)
            cur = {"key": start or None, "lines": []}
            if start:
                nxt = LETTERS.index(start) + 1
        cur["lines"].append(line)
    chunks.append(cur)
    return [{"key": c["key"], "text": "\n".join(c["lines"]).strip("\n")} for c in chunks if "".join(c["lines"]).strip()]


def _norm_heading(line: str) -> str:
    return re.sub(r"[#*_\s]+", " ", line).strip().lower()


def rewrite_section(run, c, letter, original, qas, source, sections):
    """New text for one section, or None to keep the original."""
    old_refs = set(verify.refs_ok(original, sections)) if sections else set()

    def check(obj):
        new = obj["markdown"].strip()
        first = new.split("\n", 1)[0]
        m = SEC.match(first)
        if not m or m.group(1) != letter:
            raise ValueError(f"The first line must be the heading of section {letter}, kept as in the original.")
        bad = verify.unsupported_numbers(new, source)
        if bad:
            raise ValueError("These numbers are in neither the paper nor the report: "
                             + ", ".join(bad) + ". Remove them or use only numbers from the source.")
        if sections:
            refs = [r for r in verify.refs_ok(new, sections) if r not in old_refs]
            if refs:
                raise ValueError("These references do not exist in the paper: " + ", ".join(refs))

    user = ("Original section:\n" + engine.untrusted(original) + "\n\nFollow-up questions and answers to fold in:\n"
            + engine.untrusted("\n\n".join(f"Question: {q}\nAnswer: {a[:2500]}" for q, a in qas)))
    try:
        obj = engine.llm_json(run, f"doc_rewrite_{letter}", engine.prompt("doc_rewrite"), user, REWRITE_SCHEMA,
                              model=c.get("doc_model") or c.get("model", "ultron"), max_tokens=3000, check=check, tries=2)
    except engine.StepFailed as e:
        log.warning("/doc: section %s kept as it was (%s)", letter, e)
        return None
    return obj["markdown"].strip()


# ------------------------------------------------------------------ images and docx

def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _inches(path: Path, dpi: int) -> float:
    from matplotlib import image
    return image.imread(str(path)).shape[1] / dpi


def render_equation(latex: str, path: Path):
    """Draw a display equation with mathtext. Returns width in inches, or None when mathtext cannot."""
    try:
        latex = re.sub(r"\\(tag|label)\{[^}]*\}|\\displaystyle|\\nonumber", "", latex).strip()
        plt = _plt()
        fig = plt.figure(figsize=(0.1, 0.1), facecolor="white")
        fig.text(0.5, 0.5, f"${latex}$", fontsize=22, ha="center", va="center")
        fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.15, facecolor="white")
        plt.close(fig)
        return min(6.0, _inches(path, 200))
    except Exception as e:
        log.warning("/doc: equation image skipped (%s)", str(e)[:120])
        try:
            plt.close("all")
        except Exception:
            pass
        return None


def render_diagram(text: str, path: Path):
    """Draw a text diagram in monospace. Returns width in inches, or None on failure."""
    try:
        lines = text.rstrip().split("\n")
        w = max(len(x) for x in lines)
        plt = _plt()
        fig = plt.figure(figsize=(max(2.5, w * 0.078 + 0.3), len(lines) * 0.17 + 0.3), facecolor="white")
        fig.text(0.01, 0.99, "\n".join(lines), family="monospace", fontsize=9, ha="left", va="top",
                 linespacing=1.15)
        fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.12, facecolor="white")
        plt.close(fig)
        return min(6.0, _inches(path, 200))
    except Exception as e:
        log.warning("/doc: diagram image skipped (%s)", str(e)[:120])
        return None


def add_images(chunks: list, outdir: Path) -> list:
    """Insert an equation image under each display equation of E and a diagram image under D's code blocks."""
    n = {"eq": 0, "dg": 0}

    def eq(m):
        n["eq"] += 1
        p = outdir / f"eq_{n['eq']}.png"
        w = render_equation(m.group(1), p)
        return m.group(0) + (f"\n\n![Equation {n['eq']}]({p.name}){{width={w:.2f}in}}\n" if w else "")

    def dg(m):
        if m.group(1).strip().lower() not in ("", "text", "txt", "ascii", "plain"):
            return m.group(0)
        n["dg"] += 1
        p = outdir / f"diagram_{n['dg']}.png"
        w = render_diagram(m.group(2), p)
        return m.group(0) + (f"\n\n![Diagram {n['dg']}]({p.name}){{width={w:.2f}in}}\n" if w else "")

    out = []
    for c in chunks:
        t = c["text"]
        if c["key"] == "E":
            t = re.sub(r"\$\$(.+?)\$\$", eq, t, flags=re.S)
        elif c["key"] == "D":
            t = re.sub(r"```([^\n`]*)\n(.*?)```", dg, t, flags=re.S)
        out.append({**c, "text": t})
    return out


def pandoc_cmd() -> list:
    return shlex.split(os.environ.get("PANDOC_CMD", "pandoc"))


def to_docx(markdown: str, workdir: Path) -> bytes:
    """markdown -> .docx bytes with pandoc ($$..$$ becomes a native Word equation)."""
    try:
        r = subprocess.run(pandoc_cmd() + ["-f", "markdown-raw_html", "-t", "docx", "-o", "-"],
                           input=markdown.encode("utf-8"), cwd=workdir, capture_output=True, timeout=120)
    except FileNotFoundError:
        raise DocError("pandoc is not installed in the paper-digest container")
    if r.returncode != 0:
        raise DocError("pandoc failed: " + r.stderr.decode("utf-8", "replace")[:200])
    return r.stdout


# ------------------------------------------------------------------ document

def _tex(s: str) -> str:
    return s.replace("$", r"\$")


def header(paper: dict, year: str) -> str:
    authors = paper.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    names = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
    bits = [year, names, ", ".join(paper.get("labs") or [])]
    link = paper.get("url") or (f"https://arxiv.org/abs/{paper['arxiv_id']}" if paper.get("arxiv_id") else "")
    lines = [f"# {_tex(paper.get('title') or 'Paper')}", "", _tex(" · ".join(b for b in bits if b))]
    if link:
        lines += ["", f"<{link}>"]
    return "\n".join(lines)


def make_doc(run, cfg, history, chat_id) -> str:
    """Build the updated report as a Google Doc in the paper's Drive folder; returns its link."""
    if not drive.enabled():
        raise DriveNotConnected("Google Drive is not connected yet. Run scripts/google-auth.py once to allow it.")
    pid = history.paper_for_chat(chat_id)
    rep = history.report(pid) if pid else None
    paper = history.get(pid) if pid else None
    if not (rep and paper):
        raise DocError("This chat is not a Deep-read chat, so there is no report to save.")

    qas = follow_ups(chat_messages(common.get_chat(chat_id)))
    chunks = split_report(rep["markdown"])
    if chunks and chunks[0]["key"] is None and chunks[0]["text"].lstrip().startswith("# "):
        chunks = chunks[1:]  # the report's own title/authors block; header() writes the title line
    run.record("doc_chat", ok=True, follow_ups=len(qas), sections=[c["key"] for c in chunks if c["key"]])

    try:
        ft = fulltext.fetch(paper)
        source, sections = ft["text"] + "\n" + rep["markdown"], ft.get("sections") or []
    except Exception as e:  # the report alone is a weaker, but safe, source
        log.warning("/doc: paper text not available (%s); checking numbers against the report only", str(e)[:120])
        source, sections = rep["markdown"], []

    open_q = []
    if qas:
        heads = "\n".join(c["text"].split("\n", 1)[0].strip() for c in chunks if c["key"])
        user = ("Report sections:\n" + engine.untrusted(heads) + "\n\nFollow-ups:\n" + engine.untrusted(
            "\n\n".join(f"[{i}] Question: {q}\nAnswer: {a[:1500]}" for i, (q, a) in enumerate(qas, 1))))

        def check_map(obj):
            for it in obj["items"]:
                if not 1 <= it["qa"] <= len(qas):
                    raise ValueError(f"qa {it['qa']} does not exist; use 1 to {len(qas)}.")

        try:
            mapping = engine.llm_json(run, "doc_map", engine.prompt("doc_map"), user, MAP_SCHEMA,
                                      model=cfg.get("doc_model") or cfg.get("model", "ultron"), max_tokens=2000, check=check_map)["items"]
        except engine.StepFailed as e:
            log.warning("/doc: could not map follow-ups (%s); report saved without changes", e)
            mapping = [{"qa": i, "section": "none", "resolved": False, "open_question": q[:200]}
                       for i, (q, _) in enumerate(qas, 1)]
        by_sec = {}
        for it in mapping:
            q = qas[it["qa"] - 1][0]
            if not it["resolved"]:
                open_q.append(it["open_question"].strip() or q[:200])
            elif it["section"] != "none":
                by_sec.setdefault(it["section"], []).append(qas[it["qa"] - 1])
        for c in chunks:
            if c["key"] in by_sec:
                new = rewrite_section(run, cfg, c["key"], c["text"], by_sec[c["key"]], source, sections)
                if new:
                    c["text"] = new
                else:
                    open_q += [f"{q[:200]} (answered in the chat, not merged into the report)" for q, _ in by_sec[c["key"]]]

    year = str(paper.get("published") or "")[:4] or str(datetime.now().year)
    short = drive.short_name(paper)
    title = f"{year} - {short} - Report"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        body = "\n\n".join(c["text"] for c in add_images(chunks, tmp))
        questions = "\n".join(f"- {_tex(q)}" for q in open_q) or "None from the follow-up chat."
        md = f"{header(paper, year)}\n\n{body}\n\n## Open questions\n\n{questions}\n"
        docx = to_docx(md, tmp)
    run.record("doc_build", ok=True, bytes=len(docx), open_questions=len(open_q))

    today = datetime.now(ZoneInfo(cfg.get("timezone", "UTC"))).date()
    folder_id, _ = drive.paper_folder(history, paper, paper.get("digest_date") or today)
    url = drive.upsert_doc(folder_id, title, docx)
    run.record("doc_upload", ok=True, url=url)
    return url
