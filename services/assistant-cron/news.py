"""News for the office briefing: search, de-duplicate, read the articles, validate the model's picks.

Code finds the stories and keeps their links; the model only picks by id and writes the words, and
code checks everything it returns. Stories already reported in the last SEEN_DAYS are skipped.
"""

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

log = logging.getLogger("news")

SEEN_DAYS = 3
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"}
MIN_TEXT = 300      # an article shorter than this falls back to its search snippet
MIN_SNIPPET = 200   # default for news_min_snippet: a story with no readable article needs a snippet this long
MAX_TEXT = 1500


def words(title) -> set:
    return {w for w in re.findall(r"\w+", title.lower()) if len(w) > 3}


def same_story(a, b) -> bool:
    """Same URL, or headlines sharing most of their longer words (one event, several outlets)."""
    if a["url"] and a["url"] == b["url"]:
        return True
    wa, wb = words(a["title"]), words(b["title"])
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def source_name(url) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def search(searxng_url, query):
    r = requests.get(searxng_url, params={"q": query, "format": "json", "categories": "news", "time_range": "day"},
                     timeout=40)
    r.raise_for_status()
    out = []
    for it in r.json().get("results", []):
        title = " ".join(it.get("title", "").split())
        if title and it.get("url"):
            out.append({"title": title, "url": it["url"], "source": source_name(it["url"]),
                        "snippet": " ".join((it.get("content") or "").split())})
    return out


def read_article(url) -> str:
    """Article text, or "" if it cannot be fetched or extracted."""
    import trafilatura  # imported late: only the office briefing needs it

    try:
        r = requests.get(url, timeout=10, headers=UA)
        r.raise_for_status()
        return " ".join((trafilatura.extract(r.text, include_comments=False, include_tables=False) or "").split())
    except Exception as e:
        log.info("news: could not read %s (%s)", source_name(url), str(e)[:60])
        return ""


def seen_before(item, state, now) -> bool:
    cutoff = now - SEEN_DAYS * 86400
    return any(s.get("ts", 0) >= cutoff and same_story(item, s) for s in state.get("news_seen", []))


def candidates(cfg, searxng_url, state, now=None, pool=8):
    """Up to `pool` fresh stories with readable text: [{title, url, source, topic, text}]. Raises if none."""
    now = now or time.time()
    min_snippet = int(cfg.get("news_min_snippet", MIN_SNIPPET))
    queries = cfg.get("news_queries") or {"world": "world news headlines"}
    lists = []
    for topic, query in queries.items():
        try:
            lists.append([{**it, "topic": topic} for it in search(searxng_url, query)])
        except Exception as e:  # one failed search is fine while the other works
            log.warning("news search %s failed: %s", topic, str(e)[:100])
            lists.append([])
    merged = []
    for i in range(max(map(len, lists), default=0)):  # first of each topic, then the next ones
        for items in lists:
            if i < len(items) and not any(same_story(items[i], m) for m in merged) and not seen_before(items[i], state, now):
                merged.append(items[i])
    top = merged[: pool + 4]  # a few spares for stories that turn out unreadable
    with ThreadPoolExecutor(max_workers=6) as ex:
        texts = list(ex.map(lambda it: read_article(it["url"]), top))
    out = []
    for it, text in zip(top, texts):
        if len(text) < MIN_TEXT:
            text = it["snippet"] if len(it["snippet"]) >= min_snippet else ""
        if text:
            out.append({k: it[k] for k in ("title", "url", "source", "topic")} | {"text": text[:MAX_TEXT]})
    if not out:
        raise ValueError("no readable stories")
    return out[:pool]


def copied(summary, text, run=12) -> bool:
    """True if the summary shares `run` consecutive words with the source text."""
    norm = lambda t: re.findall(r"\w+", t.lower())
    a, b = norm(summary), norm(text)
    grams = {tuple(b[i:i + run]) for i in range(len(b) - run + 1)}
    return any(tuple(a[i:i + run]) in grams for i in range(len(a) - run + 1))


def numbers(text) -> set:
    """Every number in the text as a plain string: 3,636 -> 3636, 2.8 -> 2.8, 30% -> 30."""
    return {m.replace(",", "").rstrip(".") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def check_stories(obj, items, plain_ok, max_stories=4, max_words=10, max_chars=450, allow_copy=False):
    """Validated [{id, headline, summary}] from the model's answer, or ValueError. A summary copied
    from its article (12+ words in a row) is an error unless allow_copy (the last attempt). A number
    that is not in the article is an error too; on the last attempt the summary is dropped instead
    (empty summary = headline and link only)."""
    if not isinstance(obj, list) or not 1 <= len(obj) <= max_stories:
        raise ValueError("wrong number of stories")
    valid, out = {x["id"] for x in items}, []
    for s in obj:
        sid, head, summ = s.get("id"), str(s.get("headline", "")).strip(), str(s.get("summary", "")).strip()
        if sid not in valid or any(sid == o["id"] for o in out):
            raise ValueError("bad or repeated id")
        if not plain_ok(head, 90) or len(head.split()) > max_words:
            raise ValueError("bad headline")
        if not plain_ok(summ, max_chars) or not 2 <= len(re.findall(r"[.!?](?:\s|$)", summ)) <= 3 or "http" in summ:
            raise ValueError("bad summary")
        source = next(x["text"] for x in items if x["id"] == sid)
        if not allow_copy and copied(summ, source):
            raise ValueError("summary copied from the article")
        if numbers(summ) - numbers(source):
            if not allow_copy:
                raise ValueError("summary has a number that is not in the article")
            log.warning("news: dropped a summary with a number not in the article (%s)", sid)
            summ = ""
        out.append({"id": sid, "headline": head, "summary": summ})
    return out


def remember(state, shown, items, now=None):
    """Adds the stories shown (by id) to state["news_seen"] and drops entries older than SEEN_DAYS."""
    now = now or time.time()
    index = {x["id"]: x for x in items}
    seen = [s for s in state.get("news_seen", []) if s.get("ts", 0) >= now - SEEN_DAYS * 86400]
    seen += [{"url": index[i]["url"], "title": index[i]["title"], "ts": now} for i in shown if i in index]
    state["news_seen"] = seen
