"""W2 score and select. The model scores papers in batches (JSON); code decides levels and the budget."""

import logging
import re

import engine

log = logging.getLogger("paper-digest")

DIMS = ("career_fit", "expert_expectation", "foundational", "impact", "evidence", "applicability")
TRACKS = ("genai", "robotics", "other_ai", "mechatronics")
ABSTRACT_CHARS = 1200
ONE_LINER_MAX = 160
SLACK = 40                 # the check allows this much over before it asks again; code then trims
MAX_FEEDBACK = 10

_SCHEMA = {
    "type": "object",
    "properties": {"papers": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "track": {"type": "string", "enum": list(TRACKS)},
            "one_liner": {"type": "string"},
            "why": {"type": "string"},
            **{d: {"type": "integer", "enum": [0, 1, 2, 3]} for d in DIMS},
        },
        "required": ["index", "track", "one_liner", "why", *DIMS],
        "additionalProperties": False}}},
    "required": ["papers"], "additionalProperties": False,
}


# ---------------------------------------------------------------- helpers

def _trim(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= n:
        return text
    cut = text[:n - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return cut + "…"


def first_sentence(text: str, n: int = ONE_LINER_MAX) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    m = re.search(r"(?<=[A-Za-z0-9\)\]])[.!?](?=\s+[A-Z])", text)
    return _trim(text[:m.end()] if m else text, n)


def venue_of(paper: dict, c: dict) -> str | None:
    """Venue from Semantic Scholar, else a configured venue named in the arXiv comment."""
    v = (paper.get("s2") or {}).get("venue")
    if v:
        return v
    for name in c.get("venues") or []:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", paper.get("comment", "")):
            return name
    return None


def _describe(i: int, p: dict, c: dict) -> str:
    s2 = p.get("s2") or {}
    lines = [
        f"[{i}] {p.get('title', '')}",
        f"categories: {', '.join(p.get('categories') or []) or 'unknown'}",
        f"labs: {', '.join(p.get('labs') or []) or 'none'}",
        f"venue: {venue_of(p, c) or 'none'}",
        f"hf_upvotes: {p['hf_upvotes'] if p.get('hf_upvotes') is not None else 'not on Hugging Face'}",
        f"citations: {s2.get('citations', 'unknown')}",
        f"abstract: {_trim(p.get('abstract', ''), ABSTRACT_CHARS) or '(none)'}",
    ]
    return "\n".join(lines)


def _user_message(batch: list[dict], c: dict, examples: list[dict]) -> str:
    parts = [f"Reader profile:\n{(c.get('profile') or '').strip()}"]
    if examples:
        ex = "\n".join(f"- \"{e['title']}\" ({e['one_liner']}) -> reader wanted: {e['level']}" for e in examples)
        parts.append(f"Earlier corrections by the reader:\n{ex}")
    parts.append(f"Score these {len(batch)} papers. Answer with one entry per number 1 to {len(batch)}.")
    parts.append(engine.untrusted("\n\n".join(_describe(i, p, c) for i, p in enumerate(batch, 1))))
    return "\n\n".join(parts)


def _make_check(n: int):
    def check(obj):
        rows = obj.get("papers") if isinstance(obj, dict) else None
        if not isinstance(rows, list):
            raise ValueError("answer must be an object with a 'papers' array")
        seen = [r.get("index") for r in rows]
        if sorted(seen) != list(range(1, n + 1)):
            missing = sorted(set(range(1, n + 1)) - set(seen))
            raise ValueError(f"need exactly one entry for each index 1..{n}; got {seen}; missing {missing}")
        for r in rows:
            for d in DIMS:
                v = r.get(d)
                if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 3:
                    raise ValueError(f"paper {r['index']}: {d} must be an integer 0-3, got {v!r}")
            if r.get("track") not in TRACKS:
                raise ValueError(f"paper {r['index']}: track must be one of {', '.join(TRACKS)}")
            for k in ("one_liner", "why"):
                t = (r.get(k) or "").strip()
                if not t:
                    raise ValueError(f"paper {r['index']}: {k} is empty")
                if len(t) > ONE_LINER_MAX + SLACK:
                    raise ValueError(f"paper {r['index']}: {k} is {len(t)} characters; keep it under {ONE_LINER_MAX}")
    return check


def weighted_total(scores: dict, weights: dict) -> float:
    return round(sum(float(weights.get(d, 1.0)) * scores[d] for d in DIMS), 2)


def _fallback(p: dict, c: dict) -> dict:
    out = dict(p)
    topics = p.get("topics") or []
    track = next((t for t in ("robotics", "genai", "mechatronics") if t in topics), "other_ai")
    out.update(scores={d: 0 for d in DIMS}, track=track, one_liner=first_sentence(p.get("abstract", "")) or p.get("title", "")[:ONE_LINER_MAX],
               why="Not scored: the model gave no valid answer, so it is listed as a brief.",
               total=0.0, level="brief", fallback=True)
    return out


# ---------------------------------------------------------------- score

def prerank_key(p: dict) -> float:
    """Cheap code-only priority used when more papers pass the prefilter than max_scored allows.
    Favours community votes, watched labs and robotics (the smaller stream, kept for the 50/50 balance)."""
    upvotes = p.get("hf_upvotes") or 0
    topics = p.get("topics") or []
    return (3.0 * ("hf" in (p.get("sources") or [])) + min(upvotes, 50) / 10 + 2.0 * bool(p.get("labs"))
            + 1.5 * ("robotics" in topics) + 0.5 * len(topics))


def cap(cfg: dict, papers: list[dict]) -> tuple[list[dict], list[dict]]:
    """Splits papers into (to score, left out) by prerank_key, keeping at most max_scored."""
    limit = int(cfg.get("max_scored", 0) or 0)
    if not limit or len(papers) <= limit:
        return papers, []
    ranked = sorted(papers, key=prerank_key, reverse=True)
    return ranked[:limit], ranked[limit:]


def score(run, cfg: dict | None, papers: list[dict], history) -> list[dict]:
    """Score papers in batches. A batch that fails twice gives its papers level 'brief' (none is lost).
    Papers beyond max_scored (lowest prerank_key) are returned unscored with level 'skip'."""
    c = cfg or engine.cfg()
    papers, left_out = cap(c, papers)
    if left_out:
        run.record("prerank_cap", ok=True, kept=len(papers), left_out=len(left_out))
        log.info("scoring %d papers; %d left out by max_scored", len(papers), len(left_out))
    zero = {k: 0 for k in ("career_fit", "expert_expectation", "foundational", "impact", "evidence", "applicability")}
    capped = [dict(p, scores=dict(zero), track="other_ai", one_liner=(p.get("abstract") or "")[:160], why="",
                   total=0.0, level="skip", capped=True) for p in left_out]
    return _score(run, c, papers, history) + capped


def _score(run, c: dict, papers: list[dict], history) -> list[dict]:
    size = max(1, int(c.get("score_batch", 10)))
    weights = c.get("weights") or {}
    system = engine.prompt("score")
    examples = history.feedback_examples(MAX_FEEDBACK) if history else []
    out: list[dict] = []
    for b, start in enumerate(range(0, len(papers), size), 1):
        batch = papers[start:start + size]
        try:
            obj = engine.llm_json(run, f"score.batch{b}", system, _user_message(batch, c, examples), _SCHEMA,
                                  max_tokens=300 * len(batch) + 500, temperature=0.2, check=_make_check(len(batch)))
        except engine.StepFailed as e:
            log.warning("score batch %d failed (%s); its papers become briefs", b, e)
            out += [_fallback(p, c) for p in batch]
            continue
        by_index = {r["index"]: r for r in obj["papers"]}
        for i, p in enumerate(batch, 1):
            r = by_index[i]
            s = dict(p)
            s["scores"] = {d: int(r[d]) for d in DIMS}
            s["track"] = r["track"]
            s["one_liner"] = _trim(r["one_liner"], ONE_LINER_MAX)
            s["why"] = _trim(r["why"], ONE_LINER_MAX)
            s["total"] = weighted_total(s["scores"], weights)
            out.append(s)
    return out


# ---------------------------------------------------------------- select

def _balanced(cands: list[dict], tracks: list[str], margin: float) -> list[dict]:
    """Order by total, but alternate the balance tracks when their totals are within `margin`."""
    pool = sorted(cands, key=lambda p: -p["total"])
    out: list[dict] = []
    count = {t: 0 for t in tracks}
    while pool:
        top = pool[0]
        pick = top
        if top["track"] in count and len(tracks) > 1:
            want = min(tracks, key=lambda t: (count[t], tracks.index(t)))
            if top["track"] != want:
                alt = next((p for p in pool if p["track"] == want and p["total"] >= top["total"] - margin), None)
                if alt:
                    pick = alt
        pool.remove(pick)
        out.append(pick)
        if pick["track"] in count:
            count[pick["track"]] += 1
    return out


def select(cfg: dict | None, scored: list[dict]) -> list[dict]:
    """Pure code: levels, budget and numbers. Returns every paper, shown ones first in number order
    (deep, overview, brief), then 'runner_up' (relevant, lost on budget; flagged runner_up=True) and 'skip'."""
    c = cfg or engine.cfg()
    gate = c.get("deep_gate") or {"foundational": 3, "career_fit": 2}
    max_deep = int(c.get("max_deep_per_night", 4))
    min_over = float(c.get("min_total_overview", 9.0))
    min_brief = float(c.get("min_total_brief", 5.0))
    capped = set(c.get("capped_tracks") or [])
    capped_over = float(c.get("capped_tracks_overview_total", 13.0))
    bal = list(c.get("track_balance") or [])
    margin = float(c.get("balance_margin", 1.0))
    budget = float(c.get("budget_minutes", 90))
    mins = {"deep": 25.0, "overview": 5.0, "brief": 0.5, **(c.get("minutes_per_level") or {})}
    max_briefs = int(c.get("max_briefs", 25))
    if not c.get("deep_reads", True):   # Overviews only: a foundational paper costs an Overview's time
        mins["deep"] = mins["overview"]

    papers = [dict(p) for p in scored]
    forced = [p for p in papers if p.get("fallback")]
    deep_c, over_c, brief_c, skipped = [], [], [], []
    for p in papers:
        if p.get("fallback"):
            continue
        s, t = p["scores"], p["total"]
        is_capped = p["track"] in capped
        if s["foundational"] >= gate.get("foundational", 3) and s["career_fit"] >= gate.get("career_fit", 2) \
                and (not is_capped or t >= capped_over):
            deep_c.append(p)
        elif t >= (capped_over if is_capped else min_over):
            over_c.append(p)
        elif t >= min_brief:
            brief_c.append(p)
        else:
            skipped.append(p)

    used = 0.0
    deep: list[dict] = []
    for p in _balanced(deep_c, bal, margin):
        if len(deep) < max_deep and used + mins["deep"] <= budget:
            deep.append(p)
            used += mins["deep"]
        else:
            over_c.append(p)          # lost on count or budget: an Overview instead
    overview: list[dict] = []
    demoted: list[dict] = []
    reserve = float(c.get("brief_reserve_minutes", 0))   # Overviews never eat the Briefs' share
    for p in _balanced(over_c, bal, margin):
        if used + mins["overview"] <= budget - reserve:
            overview.append(p)
            used += mins["overview"]
        else:
            demoted.append(p)         # lost on budget: a Brief if there is room
    pool = sorted(demoted + brief_c, key=lambda p: -p["total"])
    room = max_briefs if mins["brief"] <= 0 else min(max_briefs, int((budget - used) / mins["brief"] + 1e-9))
    briefs = pool[:max(room, 0)]
    runners = pool[max(room, 0):]

    for p in deep:
        p["level"] = "deep"
    for p in overview:
        p["level"] = "overview"
    for p in briefs:
        p["level"] = "brief"
    for p in forced:
        p["level"] = "brief"
    for p in runners:
        p["level"], p["runner_up"] = "runner_up", True
    for p in skipped:
        p["level"] = "skip"

    shown = deep + overview + briefs + forced
    for n, p in enumerate(shown, 1):
        p["number"] = n
    return shown + runners + skipped
