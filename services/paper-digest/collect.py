"""W1 collect: arXiv + Hugging Face Daily Papers, merge, drop seen, keyword prefilter, Semantic Scholar, labs.

Every source fails on its own: collect() returns (papers, notes) and notes holds short lines such as
"arXiv unavailable" for the digest to show. Nothing here raises for a network problem.
"""

import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import requests

import engine

log = logging.getLogger("paper-digest")

ARXIV_API = "https://export.arxiv.org/api/query"
HF_API = "https://huggingface.co/api/daily_papers"
S2_BATCH = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_FIELDS = "citationCount,influentialCitationCount,venue,authors.hIndex,references.title,references.abstract"
ARXIV_GAP = 3.1            # arXiv asks for 3 s between requests
WINDOW_DAYS = 2            # "most recent announcement window"
PAGE = 200
MAX_REFS = 40
NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}

_ID_NEW = r"\d{4}\.\d{4,5}"
_ID_OLD = r"[a-z\-]+(?:\.[A-Za-z]{2})?/\d{7}"
ARXIV_ID_RE = re.compile(rf"^(?:{_ID_NEW}|{_ID_OLD})$")
ARXIV_URL_RE = re.compile(rf"arxiv\.org/(?:abs|pdf|html)/((?:{_ID_NEW})|(?:{_ID_OLD}))(?:v\d+)?(?:\.pdf)?", re.I)

_last_arxiv = 0.0


def _headers(c: dict) -> dict:
    return {"User-Agent": c.get("user_agent", "ultron-paper-digest/1.0")}


# ---------------------------------------------------------------- helpers

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _arxiv_get(c: dict, params: dict) -> str:
    """One arXiv API call, at least ARXIV_GAP after the previous one; retries on 429/5xx."""
    global _last_arxiv
    last = None
    for attempt in range(3):
        wait = ARXIV_GAP - (time.monotonic() - _last_arxiv)
        if wait > 0:
            time.sleep(wait)
        _last_arxiv = time.monotonic()
        try:
            r = requests.get(ARXIV_API, params=params, headers=_headers(c), timeout=60)
            if r.status_code in (429, 500, 502, 503, 504):
                last = RuntimeError(f"arXiv HTTP {r.status_code}")
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last = e
            time.sleep(3)
    raise last or RuntimeError("arXiv failed")


def paper_id_for(arxiv_id: str | None, url: str = "") -> str:
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    return "url:" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _blank(arxiv_id, title, abstract, **kw) -> dict:
    p = {
        "id": paper_id_for(arxiv_id, kw.get("url", "")), "arxiv_id": arxiv_id, "title": title,
        "authors": [], "abstract": abstract, "url": "", "pdf_url": None,
        "html_url": f"https://arxiv.org/html/{arxiv_id}" if arxiv_id else None,
        "categories": [], "published": "", "comment": "", "sources": [], "hf_upvotes": None,
        "s2": None, "labs": [],
    }
    p.update(kw)
    return p


def parse_arxiv_feed(xml_text: str) -> list[dict]:
    """Atom feed from the arXiv API -> Papers (sources ['arxiv'])."""
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", NS):
        raw_id = (e.findtext("a:id", "", NS) or "")
        m = re.search(r"/abs/(.+?)(?:v\d+)?$", raw_id)
        if not m:
            continue
        aid = m.group(1)
        pdf = None
        for ln in e.findall("a:link", NS):
            if ln.get("title") == "pdf" or ln.get("type") == "application/pdf":
                pdf = (ln.get("href") or "").replace("http://", "https://")
        pdf = pdf or f"https://arxiv.org/pdf/{aid}"
        out.append(_blank(
            aid, _clean(e.findtext("a:title", "", NS)), _clean(e.findtext("a:summary", "", NS)),
            authors=[_clean(a.findtext("a:name", "", NS)) for a in e.findall("a:author", NS)],
            url=f"https://arxiv.org/abs/{aid}", pdf_url=pdf,
            categories=[c.get("term") for c in e.findall("a:category", NS) if c.get("term")],
            published=(e.findtext("a:published", "", NS) or "")[:10],
            comment=_clean(e.findtext("x:comment", "", NS)), sources=["arxiv"]))
    return out


# ---------------------------------------------------------------- sources

def fetch_arxiv(c: dict, today: date) -> list[dict]:
    """Newest papers in the configured categories, paged until older than the window."""
    cats = c.get("arxiv_categories") or []
    if not cats:
        return []
    cutoff = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    cap = int(c.get("arxiv_max_results", 2000))
    query = " OR ".join(f"cat:{x}" for x in cats)
    papers, start = [], 0
    while start < cap:
        feed = parse_arxiv_feed(_arxiv_get(c, {
            "search_query": query, "sortBy": "submittedDate", "sortOrder": "descending",
            "start": start, "max_results": min(PAGE, cap - start)}))
        if not feed:
            break
        papers += [p for p in feed if p["published"] >= cutoff]
        if feed[-1]["published"] < cutoff or len(feed) < PAGE:
            break
        start += PAGE
    return papers


def fetch_arxiv_ids(c: dict, ids: list[str]) -> dict[str, dict]:
    """Metadata for specific arXiv ids (100 per request)."""
    out = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        for p in parse_arxiv_feed(_arxiv_get(c, {"id_list": ",".join(chunk), "max_results": len(chunk)})):
            out[p["arxiv_id"]] = p
    return out


def hf_items(c: dict) -> list[dict]:
    """Raw items of the Daily Papers API (latest day)."""
    r = requests.get(HF_API, params={"limit": 100}, headers=_headers(c), timeout=30)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def paper_from_hf(item: dict) -> dict | None:
    """One Daily Papers item -> Paper (sources ['hf']); None when it has no arXiv id."""
    p = item.get("paper") or {}
    aid = str(p.get("id") or "")
    if not ARXIV_ID_RE.match(aid):
        return None
    org = item.get("organization") or p.get("organization") or {}
    paper = _blank(
        aid, _clean(p.get("title") or item.get("title") or ""), _clean(p.get("summary") or item.get("summary") or ""),
        authors=[_clean(a.get("name", "")) for a in p.get("authors") or [] if a.get("name")],
        url=f"https://arxiv.org/abs/{aid}", pdf_url=f"https://arxiv.org/pdf/{aid}",
        published=(p.get("publishedAt") or item.get("publishedAt") or "")[:10],
        sources=["hf"], hf_upvotes=int(p.get("upvotes") or 0))
    paper["_org"] = " ".join(filter(None, [org.get("name"), org.get("fullname")]))
    return paper


def merge(*lists: list[dict]) -> list[dict]:
    """Merge duplicates by id; the first record wins, sources and upvotes are combined."""
    by_id: dict[str, dict] = {}
    for lst in lists:
        for p in lst:
            q = by_id.get(p["id"])
            if q is None:
                by_id[p["id"]] = p
                continue
            for s in p["sources"]:
                if s not in q["sources"]:
                    q["sources"].append(s)
            if p.get("hf_upvotes") is not None:
                q["hf_upvotes"] = max(q.get("hf_upvotes") or 0, p["hf_upvotes"])
            if p.get("_org") and not q.get("_org"):
                q["_org"] = p["_org"]
            for k in ("abstract", "comment", "published"):
                if not q.get(k) and p.get(k):
                    q[k] = p[k]
            if not q.get("categories") and p.get("categories"):
                q["categories"] = p["categories"]
    return list(by_id.values())


# ---------------------------------------------------------------- prefilter and labs

def _kw_regex(kw: str) -> re.Pattern:
    parts = [re.escape(x) for x in re.split(r"[\s\-]+", kw.strip()) if x]
    body = r"[\s\-]+".join(parts)
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?:s|es)?(?![A-Za-z0-9])", re.I)


def topic_matchers(c: dict) -> dict[str, list[re.Pattern]]:
    return {t: [_kw_regex(k) for k in (spec or {}).get("keywords", [])] for t, spec in (c.get("topics") or {}).items()}


def topic_hits(paper: dict, matchers: dict) -> list[str]:
    text = f"{paper.get('title', '')}\n{paper.get('abstract', '')}"
    return [t for t, pats in matchers.items() if any(p.search(text) for p in pats)]


def prefilter(papers: list[dict], c: dict) -> list[dict]:
    """Keep papers matching any topic keyword; Hugging Face papers always pass. Sets paper['topics']."""
    m = topic_matchers(c)
    keep = []
    for p in papers:
        p["topics"] = topic_hits(p, m)
        if p["topics"] or "hf" in p["sources"] or "queue" in p["sources"]:
            keep.append(p)
    return keep


def match_labs(paper: dict, labs: list[str]) -> list[str]:
    """Watched labs named in the comment, abstract, authors or the Hugging Face organisation.
    Case-sensitive on purpose (so 'meta-learning' is not Meta); a name followed by a digit or hyphen
    (Qwen3, Qwen-VL: a model name, not the lab) does not count."""
    text = " ".join([paper.get("comment", ""), paper.get("abstract", ""), " ".join(paper.get("authors", [])),
                     paper.get("_org", "")])
    found = []
    for lab in labs:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(lab)}(?![A-Za-z0-9\-])", text):
            found.append(lab)
    return found


# ---------------------------------------------------------------- Semantic Scholar

def enrich_s2(papers: list[dict], c: dict) -> str | None:
    """Fill paper['s2'] in place. Returns a note when enrichment was skipped, else None. Never raises."""
    todo = [p for p in papers if p.get("arxiv_id") and not p.get("s2")]
    if not todo:
        return None
    failed = False
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        try:
            for attempt in range(2):      # one retry on 429 (the free pool is shared)
                r = requests.post(S2_BATCH, params={"fields": S2_FIELDS}, headers=_headers(c), timeout=60,
                                  json={"ids": [f"ARXIV:{p['arxiv_id']}" for p in chunk]})
                if r.status_code != 429:
                    break
                time.sleep(5)
            if r.status_code == 429:
                log.warning("Semantic Scholar rate limit; skipping enrichment")
                failed = True
                break
            if r.status_code == 400 and "No valid paper ids" in r.text:
                time.sleep(1.0)
                continue                  # none of this chunk is indexed yet (brand-new papers): not an error
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            rows = r.json()
        except Exception as e:
            log.warning("Semantic Scholar failed: %s", str(e)[:300])
            failed = True
            break
        for p, row in zip(chunk, rows):
            if row:
                p["s2"] = s2_from_row(row)
        time.sleep(1.0)
    return "Semantic Scholar unavailable (no citation data today)" if failed else None


def s2_from_row(row: dict) -> dict:
    hs = [a.get("hIndex") for a in row.get("authors") or [] if isinstance(a.get("hIndex"), int)]
    refs = []
    for ref in (row.get("references") or [])[:MAX_REFS]:
        if ref and ref.get("title"):
            refs.append({"title": ref["title"], "abstract": (ref.get("abstract") or None)})
    return {"citations": int(row.get("citationCount") or 0), "influential": int(row.get("influentialCitationCount") or 0),
            "max_author_hindex": max(hs) if hs else None, "venue": (row.get("venue") or None), "references": refs}


# ---------------------------------------------------------------- public API

def collect(run, cfg: dict | None, history, today) -> tuple[list[dict], list[str]]:
    """W1. Returns (papers, notes). notes = short lines about sources that failed or were empty."""
    c = cfg or engine.cfg()
    if isinstance(today, datetime):
        today = today.date()
    notes: list[str] = []
    arxiv: list[dict] = []
    hf: list[dict] = []
    arxiv_ok = False

    try:
        arxiv = fetch_arxiv(c, today)
        arxiv_ok = True
        run.record("collect.arxiv", ok=True, papers=len(arxiv))
    except Exception as e:
        log.warning("arXiv failed: %s", str(e)[:200])
        run.record("collect.arxiv", ok=False, error=str(e)[:200])
        notes.append("arXiv unavailable")

    if c.get("hf_daily_papers", True):
        try:
            hf = [p for p in (paper_from_hf(i) for i in hf_items(c)) if p]
            run.record("collect.hf", ok=True, papers=len(hf))
            if not hf:
                notes.append("Hugging Face Daily Papers had no papers")
        except Exception as e:
            log.warning("Hugging Face failed: %s", str(e)[:200])
            run.record("collect.hf", ok=False, error=str(e)[:200])
            notes.append("Hugging Face Daily Papers unavailable")

    new_arxiv = [p for p in arxiv if not history.seen(p["id"])]
    papers = merge(new_arxiv, [p for p in hf if not history.seen(p["id"])])

    # HF-only papers lack categories and comments: look them up on arXiv in one request.
    hf_only = [p for p in papers if p["sources"] == ["hf"]]
    if hf_only and arxiv_ok:
        try:
            meta = fetch_arxiv_ids(c, [p["arxiv_id"] for p in hf_only])
            for p in hf_only:
                m = meta.get(p["arxiv_id"])
                if m:
                    p["categories"], p["comment"] = m["categories"], m["comment"]
                    p["authors"] = p["authors"] or m["authors"]
                    p["abstract"] = p["abstract"] or m["abstract"]
        except Exception as e:
            log.warning("arXiv lookup for HF papers failed: %s", str(e)[:150])

    # Weekend rule: no new arXiv listing -> HF papers plus the week's runners-up.
    if arxiv_ok and not new_arxiv:
        ru = [p for p in history.runners_up(days=7) if all(p["id"] != q["id"] for q in papers)]
        for p in ru:
            p["_ru"] = True
        papers = merge(papers, ru)
        notes.append(f"No new arXiv listing; added {len(ru)} runner-up papers from this week")

    before = len(papers)
    papers = [p for p in papers if p.get("_ru")] + prefilter([p for p in papers if not p.get("_ru")], c)
    run.record("collect.prefilter", ok=True, before=before, after=len(papers))

    if c.get("semantic_scholar", True):
        note = enrich_s2(papers, c)
        run.record("collect.s2", ok=note is None, enriched=sum(1 for p in papers if p.get("s2")))
        if note:
            notes.append(note)

    labs = c.get("labs") or []
    for p in papers:
        p["labs"] = match_labs(p, labs)
        p.pop("_org", None)
        p.pop("_ru", None)
    return papers, notes


def paper_from_url(url: str, cfg: dict | None = None) -> dict:
    """Paper for a queued link. arXiv abs/pdf/html links are looked up on arXiv; any other URL gives
    a minimal Paper (title from the address, pdf_url = the URL). Raises ValueError if arXiv has no such paper."""
    c = cfg or engine.cfg()
    url = (url or "").strip()
    m = ARXIV_URL_RE.search(url)
    if not m:
        title = re.sub(r"[-_]+", " ", url.rstrip("/").rsplit("/", 1)[-1].rsplit(".", 1)[0]) or url
        return _blank(None, title, "", url=url, pdf_url=url, sources=["queue"], published=date.today().isoformat())
    aid = m.group(1)
    try:
        found = fetch_arxiv_ids(c, [aid]).get(aid)
    except Exception as e:
        raise ValueError(f"arXiv lookup failed: {str(e)[:120]}") from e
    if not found:
        raise ValueError(f"arXiv has no paper {aid}")
    found["sources"] = ["arxiv", "queue"]
    found["labs"] = match_labs(found, c.get("labs") or [])
    found["topics"] = topic_hits(found, topic_matchers(c))
    if c.get("semantic_scholar", True):
        enrich_s2([found], c)
    return found
