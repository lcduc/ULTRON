"""Deep reads (W3) and Overviews (W4). Code owns the order; the model does one narrow JSON job per step.

deep_read(run, cfg, paper, history) -> {"markdown", "short_title", "concepts", "fulltext", "stats"}
overview(run, cfg, scored)          -> {"markdown", "fulltext": ft | None}
"""

import logging
import re
import time

import fulltext
import verify
from engine import StepFailed, llm_json, prompt, untrusted

log = logging.getLogger("paper-digest")

# Headings exactly as in prompts/tutor_spec.md
PARTS = {"A": 1, "B": 1, "C": 1, "D": 1, "E": 1, "F": 1, "G": 1, "H": 1, "I": 2, "J": 2, "K": 3, "L": 3, "M": 3}
PART_TITLES = {1: "Part 1 — The paper", 2: "Part 2 — In practice", 3: "Part 3 — Study"}
NAMES = {"A": "TL;DR", "B": "The problem", "C": "What's new", "D": "How it works", "E": "Key equation",
         "F": "How they tested it", "G": "What the evidence shows", "H": "Limits and what came next",
         "I": "Picture it at work", "J": "When to use it", "K": "Reading guide", "L": "Interview question",
         "M": "Check yourself"}
GROUPS = [("deep_AD", "ABCD", 0.40), ("deep_EH", "EFGH", 0.30), ("deep_IJ", "IJ", 0.20), ("deep_KM", "KLM", 0.15)]
SECTION_CAP = {"D": 1.0, "I": 0.8}  # extra room (share of deep_words) for the mechanism and the example
OVERVIEW_SECTIONS = "ABCDGHJL"
FENCE = re.compile(r"```.*?```", re.S)

NOTES_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["claims", "method_steps", "results", "limits", "equations", "figures"],
    "properties": {
        "claims": {"type": "array", "items": {"type": "string"}},
        "method_steps": {"type": "array", "items": {"type": "string"}},
        "results": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["value", "metric", "dataset", "baseline", "table", "quote"],
            "properties": {k: {"type": "string"} for k in ["value", "metric", "dataset", "baseline", "table", "quote"]}}},
        "limits": {"type": "array", "items": {"type": "string"}},
        "equations": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["latex", "meaning"],
            "properties": {"latex": {"type": "string"}, "meaning": {"type": "string"}}}},
        "figures": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["label", "shows"],
            "properties": {"label": {"type": "string"}, "shows": {"type": "string"}}}},
    },
}


def _words(text: str) -> int:
    return len(FENCE.sub(" ", text).split())


# ------------------------------------------------------------------ steps 3-4: notes
def _clean_latex(s: str) -> str:
    return re.sub(r"\s+", "", s.strip().strip("$"))


def verify_notes(notes: dict, chunk: str, source: str) -> tuple[dict, int]:
    """Step 4. Keep only results whose value and quote are in the text; equations that occur in the
    text; table labels that exist. Returns (clean notes, number dropped)."""
    dropped = 0
    results = []
    for r in notes.get("results", []):
        value, quote = (r.get("value") or "").strip(), (r.get("quote") or "").strip()
        if not re.search(r"\d", value) or verify.unsupported_numbers(value, source):
            dropped += 1  # no number, or the number is not in the paper
            continue
        if not quote or not (verify.quote_ok(quote, chunk) or verify.quote_ok(quote, source)):
            dropped += 1  # quote not found in the text
            continue
        if verify.unsupported_numbers(value, quote) or not any(verify._all_numbers(quote)):
            dropped += 1  # the quote does not contain the number it should support
            continue
        r = dict(r)
        if r.get("table") and verify.refs_ok(r["table"], source):
            r["table"] = ""
        results.append(r)
    flat_src = _clean_latex(source)
    eqs = []
    for e in notes.get("equations", []):
        if _clean_latex(e.get("latex", "")) and _clean_latex(e["latex"]) in flat_src:
            eqs.append(e)
        else:
            dropped += 1
    return {**notes, "results": results, "equations": eqs}, dropped


def merge_notes(all_notes: list[dict]) -> dict:
    out = {"claims": [], "method_steps": [], "results": [], "limits": [], "equations": [], "figures": []}
    seen = {k: set() for k in out}
    for n in all_notes:
        for k in out:
            for item in n.get(k, []):
                key = item if isinstance(item, str) else (item.get("quote") or item.get("latex") or item.get("label") or str(item))
                key = re.sub(r"\W+", " ", key.lower()).strip()
                if key and key not in seen[k]:
                    seen[k].add(key)
                    out[k].append(item)
    return out


def notes_text(notes: dict) -> str:
    lines = []
    if notes["claims"]:
        lines.append("CLAIMS")
        lines += [f"- {c}" for c in notes["claims"]]
    if notes["method_steps"]:
        lines.append("METHOD STEPS")
        lines += [f"{i}. {s}" for i, s in enumerate(notes["method_steps"], 1)]
    if notes["results"]:
        lines.append("VERIFIED RESULTS (value | metric | dataset | baseline | table)")
        for r in notes["results"]:
            lines.append(f"- {r['value']} | {r['metric']} | {r['dataset']} | {r['baseline'] or 'n/a'} | "
                         f"{r['table'] or 'n/a'} | \"{r['quote']}\"")
    if notes["limits"]:
        lines.append("LIMITS")
        lines += [f"- {c}" for c in notes["limits"]]
    if notes["equations"]:
        lines.append("EQUATION CANDIDATES")
        lines += [f"- ${e['latex'].strip().strip('$')}$ : {e['meaning']}" for e in notes["equations"]]
    if notes["figures"]:
        lines.append("FIGURES")
        lines += [f"- {f['label']}: {f['shows']}" for f in notes["figures"]]
    return "\n".join(lines)


def _note_chunk(run, system: str, chunk: str, step: str, source: str, depth: int = 0):
    """Notes for one chunk. If the model cannot produce valid JSON, split the chunk and try the halves."""
    try:
        raw = llm_json(run, step, system, untrusted(chunk), NOTES_SCHEMA, max_tokens=4500, temperature=0.1)
    except StepFailed as e:
        lines = chunk.splitlines()
        if depth >= 1 or len(lines) < 6:
            log.warning("%s failed: %s", step, e)
            return [], 0, 1
        mid = len(lines) // 2
        out, dropped, failed = [], 0, 0
        halves = ["\n".join(lines[:mid]), "\n".join(lines[mid:])]
        for k, part in enumerate(halves, 1):
            n, d, f = _note_chunk(run, system, part, f"{step}.{k}", source, depth + 1)
            out += n; dropped += d; failed += f
        return out, dropped, failed
    n, d = verify_notes(raw, chunk, source)
    run.record(f"verify_{step}", ok=True, dropped=d, kept_results=len(n["results"]))
    return [n], d, 0


def take_notes(run, chunk_list: list[str], source: str, tag: str = "notes") -> tuple[dict, int, int]:
    """Steps 3 and 4 for a list of chunks. Returns (merged verified notes, dropped, failed chunks)."""
    system = prompt("notes")
    clean, dropped, failed = [], 0, 0
    for i, chunk in enumerate(chunk_list, 1):
        n, d, f = _note_chunk(run, system, chunk, f"{tag}[{i}/{len(chunk_list)}]", source)
        clean += n; dropped += d; failed += f
    return merge_notes(clean), dropped, failed


# ------------------------------------------------------------------ step 5: context
def build_context(cfg: dict, paper: dict, history) -> str:
    refs = ((paper.get("s2") or {}).get("references")) or []
    n = int(cfg.get("context_references", 6))
    parts = []
    for r in [r for r in refs if r.get("abstract")][:n]:
        parts.append(f"- {r.get('title', '')}: {r['abstract'][:600]}")
    taught = list(history.concepts()) if history else []
    known = cfg.get("known_concepts", [])
    txt = ""
    if parts:
        txt += "PAPERS THIS ONE BUILDS ON (abstracts):\n" + "\n".join(parts) + "\n\n"
    txt += "THE READER ALREADY KNOWS (do not re-explain):\n" + "\n".join(f"- {k}" for k in known) + "\n\n"
    txt += "CONCEPTS ALREADY TAUGHT IN EARLIER REPORTS (mention in one clause, link back):\n"
    txt += "\n".join(f"- {k}" for k in taught) if taught else "- none yet"
    return txt


# ------------------------------------------------------------------ step 6: writing
def _schema(letters: str, extra: dict | None = None) -> dict:
    props = {"sections": {"type": "object", "additionalProperties": False, "required": list(letters),
                          "properties": {L: {"type": "string"} for L in letters}},
             "concepts_taught": {"type": "array", "items": {"type": "string"}}}
    req = ["sections", "concepts_taught"]
    if extra:
        props.update(extra)
        req += list(extra)
    return {"type": "object", "additionalProperties": False, "required": req, "properties": props}


def _strip_heading(text: str) -> str:
    """Drop heading lines the model added; the code writes the headings."""
    names = {re.sub(r"\W+", "", n.lower()) for n in NAMES.values()}
    text = re.sub(r"\s*<br\s*/?>\s*", "\n", text)  # the model sometimes joins bullets with <br>
    lines = text.strip().splitlines()
    # An echo of the prompt's spec line, e.g. "TL;DR - 3 plain lines: the problem, ..."
    spec = re.compile(r"^\W*(?:[A-M][.:)]\s*)?(" + "|".join(re.escape(n) for n in NAMES.values()) + r")\s*[-–—]\s", re.I)
    if lines and len(lines[0]) < 200 and spec.match(lines[0]):
        lines = lines[1:]
    while lines and len(lines[0]) < 80:
        first = lines[0].strip()
        plain = re.sub(r"\W+", "", re.sub(r"^\W*[A-M][.:)]\s+", "", first).lower())
        if re.match(r"^\s*(#{1,6}\s|\*\*[A-M][.:)])", first) or plain in names:
            lines = lines[1:]
        else:
            break
    return "\n".join(lines).strip()


def _make_check(letters: str, budget: int):
    """budget = target words for these sections together (diagrams excluded)."""
    def check(obj):
        secs = obj.get("sections") or {}
        total = 0
        for L in letters:
            t = (secs.get(L) or "").strip()
            if len(t) < 40:
                raise ValueError(f"section {L} is missing or too short")
            w = _words(t)
            cap = int(budget * (0.6 if len(letters) > 2 else 0.8))
            if w > cap:
                raise ValueError(f"section {L} is too long ({w} words); keep it under {cap} words")
            total += w
            if L == "D" and "```" not in t:
                raise ValueError("section D needs a text diagram inside a fenced code block")
            if L == "E" and "```" in t:
                raise ValueError("section E: the equation must be display LaTeX between $$ and $$, not a code block")
            if L == "E" and "$$" not in t and "no single central formula" not in t.lower():
                raise ValueError("section E needs display LaTeX between $$ and $$, or the no-formula sentence")
            if L == "M":
                # "1. ... 2. ... 3. ..." on one line is fine: put each question on its own line.
                t = re.sub(r"(?<=[?.!\"')])\s+(?=(?:\*\*)?[2-9][.)]\s)", "\n", t)
                secs["M"] = t
                if len(re.findall(r"(?m)^\s*(?:\*\*)?\d+[.)]", t)) < 3:
                    raise ValueError("section M needs 3 numbered questions, each on its own line")
        if total > budget * 1.35:
            raise ValueError(f"too long overall ({total} words); these sections together should be about {budget} words")
        # short_title is not checked: _short_title() falls back to the paper title when it is unusable.
    return check


def write_sections(run, cfg: dict, paper: dict, notes_txt: str, ctx: str, section_list: str) -> tuple[dict, list, str]:
    model = cfg.get("writer_model")
    words = int(cfg.get("deep_words", 1000))
    system_base = prompt("deep_system").replace("{words}", str(words))
    written: dict[str, str] = {}
    concepts: list[str] = []
    short_title = ""
    for name, letters, share in GROUPS:
        budget = int(words * share)
        system = system_base + "\n\n" + prompt(name)
        so_far = "\n\n".join(f"[{L}. {NAMES[L]}]\n{written[L]}" for L in written)
        user = (f"PAPER: {paper.get('title', '')}\n\nSECTIONS OF THE PAPER (titles):\n{section_list}\n\n"
                f"VERIFIED NOTES:\n{untrusted(notes_txt)}\n\n{ctx}\n\n"
                + (f"REPORT SO FAR:\n{so_far}\n\n" if so_far else "")
                + f"Write sections {', '.join(letters)}. Length: about {budget} words for these sections together "
                  f"(hard limit {int(budget * 1.35)}). Be brief; cut examples before cutting the mechanism.")
        extra = {"short_title": {"type": "string"}} if name == "deep_AD" else None
        try:
            obj = llm_json(run, f"write_{letters}", system, user, _schema(letters, extra), model=model,
                           max_tokens=4000, temperature=0.4, check=_make_check(letters, budget), tries=3)
        except StepFailed as e:
            if "A" in letters:  # without the core (TL;DR to How it works) there is no report
                raise
            # A later group failing costs only its own sections, not the whole Deep read.
            for L in letters:
                written[L] = ("_This part could not be written tonight. Ask about it in this chat, "
                              f"or send /doc later to try again._ ({str(e)[:80]})")
            continue
        for L in letters:
            written[L] = _strip_heading(obj["sections"][L])
        concepts += [c.strip() for c in obj.get("concepts_taught", []) if c.strip()]
        if extra:
            short_title = obj["short_title"].strip()
    return written, concepts, short_title


def assemble(title: str, paper: dict, sections: dict, letters: str = "ABCDEFGHIJKLM", overview: bool = False) -> str:
    out = [f"# {title}", ""]
    meta = []
    if paper.get("authors"):
        a = paper["authors"]
        meta.append(", ".join(a[:3]) + (" et al." if len(a) > 3 else ""))
    if paper.get("url"):
        meta.append(paper["url"])
    if meta:
        out += ["*" + " · ".join(meta) + "*", ""]
    part = 0
    for L in letters:
        if L not in sections:
            continue
        if not overview and PARTS[L] != part:
            part = PARTS[L]
            out += [f"## {PART_TITLES[part]}", ""]
        out += [f"### {L}. {NAMES[L]}", "", sections[L].strip(), ""]
    return "\n".join(out).strip() + "\n"


# ------------------------------------------------------------------ steps 7-8: critique, fix, final checks
CRITIQUE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["flagged"], "properties": {
    "flagged": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                           "required": ["sentence", "reason"],
                                           "properties": {"sentence": {"type": "string"}, "reason": {"type": "string"}}}}}}
FIX_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["fixes"], "properties": {
    "fixes": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                         "required": ["original", "replacement"],
                                         "properties": {"original": {"type": "string"},
                                                        "replacement": {"type": "string"}}}}}}


def _line_of(report: str, sentence: str) -> str:
    for ln in report.splitlines():
        if sentence in ln:
            return ln
    return ""


def critique_and_fix(run, cfg: dict, report: str, notes_txt: str, source: str) -> tuple[str, int]:
    """Steps 7 and 8a. Returns (report, number of sentences flagged and changed)."""
    model = cfg.get("writer_model")
    ctx = f"VERIFIED NOTES:\n{untrusted(notes_txt)}\n\nPAPER TEXT:\n{untrusted(source[:60000])}\n\n"
    try:
        crit = llm_json(run, "critique", prompt("critique"), ctx + "REPORT:\n" + report, CRITIQUE_SCHEMA,
                        model=model, max_tokens=3500, temperature=0.1, tries=3)
    except StepFailed as e:
        log.warning("critique failed: %s", e)
        return report, 0
    flagged = []
    for f in crit["flagged"]:
        s = f["sentence"].strip()
        if not s or s not in report:
            continue
        line = _line_of(report, s)
        if line.lstrip("-*> 0123456789.)").startswith("Background:") or s.startswith("Background:"):
            continue
        flagged.append({"sentence": s, "reason": f["reason"]})
    run.record("critique_filtered", ok=True, flagged=len(flagged))
    if not flagged:
        return report, 0
    listing = "\n".join(f"- SENTENCE: {f['sentence']}\n  REASON: {f['reason']}" for f in flagged)
    try:
        fx = llm_json(run, "fix", prompt("fix"), ctx + "FLAGGED SENTENCES:\n" + listing, FIX_SCHEMA,
                      model=model, max_tokens=2500, temperature=0.1)
    except StepFailed as e:
        log.warning("fix failed: %s", e)
        fx = {"fixes": [{"original": f["sentence"], "replacement": ""} for f in flagged]}
    allowed = {f["sentence"] for f in flagged}
    changed = 0
    for f in fx["fixes"]:
        o = f["original"].strip()
        if o in allowed and o in report:
            report = report.replace(o, f["replacement"].strip(), 1)
            changed += 1
    # anything flagged but not answered is deleted
    answered = {f["original"].strip() for f in fx["fixes"]}
    for s in allowed - answered:
        report = report.replace(s, "", 1)
        changed += 1
    return report, changed


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(*$\"'])")


def strip_unverified(report: str, source: str, sections: list[dict]) -> tuple[str, int]:
    """Step 8b (code). Remove sentences with a number the source does not contain, or a reference
    (section, table, figure, equation) the paper does not have. Skips headings, diagrams and the
    labelled invented example in section I. Returns (report, number removed)."""
    removed = 0
    out: list[str] = []
    in_fence, current = False, ""
    for ln in report.splitlines():
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(ln)
            continue
        m = re.match(r"^###\s+([A-M])\.", ln)
        if m:
            current = m.group(1)
        if in_fence or ln.startswith("#") or not ln.strip() or ln.startswith("$$") or ln.startswith("*") and "http" in ln:
            out.append(ln)
            continue
        if current == "I":
            bad_refs = verify.refs_ok(ln, sections)
            if not bad_refs:
                out.append(ln)
                continue
        prefix = re.match(r"^\s*(?:[-*>]\s+|\d+[.)]\s+)?", ln).group(0)
        body = ln[len(prefix):]
        if body.lstrip().startswith("|"):
            sentences = [body]
        else:
            sentences = _SENT.split(body)
        keep = []
        for s in sentences:
            bad_n = verify.unsupported_numbers(s, source) if current != "I" else []
            bad_r = verify.refs_ok(s, sections)
            if bad_n or bad_r:
                removed += 1
                continue
            keep.append(s)
        if keep:
            out.append(prefix + " ".join(keep))
        elif sentences:
            continue
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n", removed


def _finish(report: str, source: str, sections: list[dict], removed_before: int = 0) -> tuple[str, int]:
    report, removed = strip_unverified(report, source, sections)
    if removed:
        report = report.rstrip() + f"\n\n*Removed {removed} unverified statement{'s' if removed != 1 else ''}.*\n"
    return report, removed


def _short_title(paper: dict, given: str) -> str:
    t = (given or "").strip()
    if 3 <= len(t) <= 40:
        return t
    base = (paper.get("title") or "Paper").split(":")[0].strip()
    return base[:40].rstrip()


def _section_list(ft: dict) -> str:
    return "\n".join(s["title"] for s in ft["sections"])


# ------------------------------------------------------------------ W3
def deep_read(run, cfg: dict, paper: dict, history) -> dict:
    t0 = time.time()
    ft = fulltext.fetch(paper)  # 1. raises FulltextError: no report without the text
    run.record("fulltext", ok=True, source=ft["source"], words=len(ft["text"].split()),
               sections=len(ft["sections"]))
    chunk_list = fulltext.chunks(ft, int(cfg.get("deep_chunk_tokens", 6000)))  # 2.
    run.record("chunks", ok=True, count=len(chunk_list))
    notes, dropped, failed = take_notes(run, chunk_list, ft["text"])  # 3. + 4.
    if not notes["claims"] and not notes["results"] and failed:
        raise StepFailed("notes: every chunk failed")
    n_txt = notes_text(notes)
    ctx = build_context(cfg, paper, history)  # 5.
    sections, concepts, short = write_sections(run, cfg, paper, n_txt, ctx, _section_list(ft))  # 6.
    report = assemble(paper.get("title", "Paper"), paper, sections)
    source = n_txt + "\n\n" + ft["text"]
    report, _ = critique_and_fix(run, cfg, report, n_txt, ft["text"])  # 7. + 8.
    report, removed = _finish(report, source, ft["sections"])
    stats = {"words": _words(report), "notes_dropped": dropped, "removed": removed,
             "seconds": round(time.time() - t0)}
    if failed:
        stats["chunks_failed"] = failed
    run.record("deep_read_done", ok=True, **stats)
    seen, uniq = set(), []
    for c in concepts:
        if c.lower() not in seen:
            seen.add(c.lower())
            uniq.append(c)
    return {"markdown": report, "short_title": _short_title(paper, short), "concepts": uniq,
            "fulltext": ft, "stats": stats}


# ------------------------------------------------------------------ W4
KEY_SECTION = re.compile(r"abstract|intro|result|experiment|evaluation|conclusion|limitation|discussion|method|approach", re.I)


def _condensed(ft: dict, max_chars: int) -> list[dict]:
    """The sections an overview needs, capped in size."""
    keep, total = [], 0
    for s in ft["sections"]:
        if KEY_SECTION.search(s["title"]) and s["text"]:
            t = s["text"][: max(1500, (max_chars - total) // 2)]
            keep.append({"title": s["title"], "text": t})
            total += len(t)
            if total >= max_chars:
                break
    return keep or ft["sections"][:4]


def overview(run, cfg: dict, scored: dict) -> dict:
    words = int(cfg.get("overview_words", 400))
    ft, notes_txt, source = None, "", ""
    try:
        ft = fulltext.fetch(scored)
    except fulltext.FulltextError as e:
        run.record("fulltext", ok=False, error=str(e)[:200])
    abstract_only = ft is None
    if ft:
        run.record("fulltext", ok=True, source=ft["source"], words=len(ft["text"].split()))
        cond = {"sections": _condensed(ft, int(cfg.get("deep_chunk_tokens", 6000) * 3.5 * 2))}
        cl = fulltext.chunks(cond, int(cfg.get("deep_chunk_tokens", 6000)))
        notes, _, failed = take_notes(run, cl, ft["text"], tag="ov_notes")
        notes_txt = notes_text(notes)
        source = notes_txt + "\n\n" + ft["text"]
        material = f"VERIFIED NOTES:\n{untrusted(notes_txt)}\n\nABSTRACT:\n{untrusted(scored.get('abstract', ''))}"
    else:
        abstract = scored.get("abstract", "")
        source = abstract
        material = f"ABSTRACT:\n{untrusted(abstract)}"
    note = ("This paper's full text was not available, so write only from the abstract. Do not guess details "
            "the abstract does not give; say \"The abstract does not say.\"") if abstract_only else ""
    system = prompt("overview").replace("{words}", str(words)).replace("{abstract_only}", note)
    schema = _schema(OVERVIEW_SECTIONS, {"short_title": {"type": "string"}})
    user = (f"PAPER: {scored.get('title', '')}\n\n{material}\n\n"
            "THE READER ALREADY KNOWS (do not re-explain):\n" + "\n".join(f"- {k}" for k in cfg.get("known_concepts", [])))

    def check(obj):
        secs = obj.get("sections") or {}
        for L in OVERVIEW_SECTIONS:
            if len((secs.get(L) or "").strip()) < 20:
                raise ValueError(f"section {L} is missing or too short")
        total = sum(_words(secs[L]) for L in OVERVIEW_SECTIONS)
        if total > words * 2.2:
            raise ValueError(f"too long ({total} words); aim for about {words}")

    obj = llm_json(run, "overview_write", system, user, schema, max_tokens=2500, temperature=0.4, check=check)
    sections = {L: _strip_heading(obj["sections"][L]) for L in OVERVIEW_SECTIONS}
    report = assemble(scored.get("title", "Paper"), scored, sections, OVERVIEW_SECTIONS, overview=True)
    secs_for_refs = ft["sections"] if ft else []
    if abstract_only:
        report = report.rstrip() + "\n\n*Based on the abstract only.*\n"
        report, removed = strip_unverified(report, source, [{"title": "", "text": source}])
        if removed:
            report = report.rstrip() + f"\n\n*Removed {removed} unverified statement{'s' if removed != 1 else ''}.*\n"
    else:
        report, _ = _finish(report, source, secs_for_refs)
    return {"markdown": report, "fulltext": ft}
