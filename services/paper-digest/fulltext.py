"""Full text of a paper: arXiv HTML (LaTeXML) first, PDF (pypdf) as the fallback.

fetch(paper) -> {"text", "sections": [{"title", "text"}], "source": "html"|"pdf", "pdf_bytes"}
or raises FulltextError with a plain reason. chunks(ft, max_tokens) splits on section lines.
"""

import io
import logging
import re

import requests
from bs4 import BeautifulSoup, NavigableString

from engine import cfg

log = logging.getLogger("paper-digest")

MIN_WORDS = 2000
CHARS_PER_TOKEN = 3.5
INTRO_RE = re.compile(r"abstract|introduction|overview", re.I)
EXPERIMENT_RE = re.compile(r"experiment|result|evaluation|ablation|benchmark|empirical|analysis|findings|study", re.I)
REFERENCES_RE = re.compile(r"^\s*(references|bibliography)\s*$", re.I)
BLOCK_TAGS = ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "figcaption", "caption", "tr",
              "table", "figure", "section", "blockquote", "pre", "br")


class FulltextError(Exception):
    """The full text could not be fetched or failed the checks. str(e) says why."""


# ------------------------------------------------------------------ helpers
def _headers() -> dict:
    return {"User-Agent": cfg().get("user_agent", "ultron-paper-digest/1.0")}


def _words(text: str) -> int:
    return len(text.split())


def _clean_lines(text: str) -> str:
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    out, blank = [], False
    for ln in lines:
        if not ln:
            if not blank and out:
                out.append("")
            blank = True
            continue
        blank = False
        out.append(ln)
    return "\n".join(out).strip()


def _arxiv_id(paper: dict) -> str | None:
    if paper.get("arxiv_id"):
        return paper["arxiv_id"]
    pid = paper.get("id") or ""
    return pid.split(":", 1)[1] if pid.startswith("arxiv:") else None


def _check(sections: list[dict], text: str) -> str | None:
    """Return the reason the text is not good enough, or None."""
    n = _words(text)
    if n <= MIN_WORDS:
        return f"only {n} words (need more than {MIN_WORDS})"
    titles = " ".join(s["title"] for s in sections)
    if not (INTRO_RE.search(titles) or re.search(r"\babstract\b", text[:4000], re.I)):
        return "no abstract or introduction found"
    if not EXPERIMENT_RE.search(titles):
        return "no experiments or results section found"
    return None


def _assemble(sections: list[dict]) -> str:
    return "\n\n".join(f"## {s['title']}\n{s['text']}" if s["text"] else f"## {s['title']}" for s in sections)


# ------------------------------------------------------------------ HTML (LaTeXML)
def _prepare(node):
    """Turn math into $alttext$, tables into ' | ' rows, and add line breaks after block tags."""
    for m in node.find_all("math"):
        alt = (m.get("alttext") or "").strip()
        m.replace_with(NavigableString(f"${alt}$" if alt else ""))
    for t in node.select(".ltx_note, .ltx_bibliography, .ltx_page_footer, script, style, .ltx_rdf, "
                         "span.ltx_ERROR, .ltx_pagination, .ltx_listingline .ltx_tag"):
        t.decompose()
    for tbl in node.find_all("table"):
        for st in list(tbl.find_all(string=True)):
            if not st.strip() and not isinstance(st, type(None)):
                st.replace_with(NavigableString(""))  # source newlines between cells
    for c in node.find_all(["td", "th"]):
        c.append(NavigableString(" | "))
    for tag in node.select(".ltx_tag"):
        tag.append(NavigableString(" "))
    for eq in node.select(".ltx_equation, .ltx_equationgroup"):
        eq.append(NavigableString("\n"))
    for tag in node.find_all(BLOCK_TAGS):
        tag.append(NavigableString("\n"))


def _node_text(node) -> str:
    _prepare(node)
    text = node.get_text("")
    text = re.sub(r"(\s*\|\s*)+\n", "\n", text)  # trailing cell separators
    text = re.sub(r"\s*\|\s*\|\s*", " | ", text)
    return _clean_lines(text)


def _heading(sec) -> str:
    h = sec.find(["h1", "h2", "h3", "h4", "h5", "h6"], class_=re.compile("ltx_title"), recursive=False)
    if h is None:
        h = sec.find(class_=re.compile("ltx_title"))
    if h is None:
        return ""
    for tag in h.select(".ltx_tag"):
        tag.append(NavigableString(" "))
    return re.sub(r"\s+", " ", h.get_text("")).strip()


def _subtitles(sec) -> list[str]:
    out = []
    for h in sec.find_all(class_=re.compile(r"ltx_title_(sub)*section|ltx_title_appendix|ltx_title_subsection")):
        for tag in h.select(".ltx_tag"):
            tag.append(NavigableString(" "))
        t = re.sub(r"\s+", " ", h.get_text("")).strip()
        if t:
            out.append(t)
    return out


def parse_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    root = soup.find("article") or soup.find(class_="ltx_page_content") or soup.body or soup
    sections: list[dict] = []
    abstract = root.find(class_="ltx_abstract")
    if abstract is not None:
        for t in abstract.select(".ltx_title"):
            t.decompose()
        sections.append({"title": "Abstract", "text": _node_text(abstract)})
        abstract.decompose()
    for sec in root.select("section.ltx_section, section.ltx_appendix"):
        if sec.find_parent("section", class_=re.compile("ltx_section|ltx_appendix")):
            continue  # nested; handled with its parent
        title = _heading(sec)
        if REFERENCES_RE.match(re.sub(r"^\s*[\dA-Z.]*\s+", "", title) or title) or "ltx_bibliography" in (sec.get("class") or []):
            continue
        if "ltx_appendix" in (sec.get("class") or []):
            subs = _subtitles(sec)
            sections.append({"title": title, "text": "\n".join(s for s in subs if s != title)})
            continue
        for h in sec.find_all(class_=re.compile("ltx_title"), limit=1):
            h.decompose()
        sections.append({"title": title or "Untitled", "text": _node_text(sec)})
    return [s for s in sections if s["title"] or s["text"]]


# ------------------------------------------------------------------ PDF
_HEADING_RE = re.compile(
    r"^(?:(\d{1,2})\.?\s+([A-Z][^\n]{2,80})|(Abstract|Introduction|Related Work|Conclusions?|"
    r"Acknowledg(?:e)?ments?|References|Limitations|Discussion|Appendix[^\n]{0,60}|"
    r"ABSTRACT|INTRODUCTION|CONCLUSIONS?|REFERENCES|APPENDIX[^\n]{0,60}))\s*$")


def parse_pdf_text(raw: str) -> list[dict]:
    raw = re.sub(r"-\n(?=[a-z])", "", raw)
    lines = [ln.strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if not re.fullmatch(r"\d{1,3}", ln)]  # page numbers
    sections: list[dict] = []
    title, buf, in_refs, in_app = "Front matter", [], False, False

    def flush():
        txt = _clean_lines("\n".join(buf))
        if in_refs:
            return
        if in_app:
            txt = ""  # appendix: keep titles only
        if txt or title != "Front matter":
            sections.append({"title": title, "text": txt})

    for ln in lines:
        m = _HEADING_RE.match(ln)
        if m and len(ln) < 90:
            name = (ln if not m.group(1) else ln).strip()
            low = name.lower()
            if low in ("references", "bibliography"):
                flush(); title, buf, in_refs = name.title(), [], True
                continue
            if low.startswith("appendix"):
                flush(); title, buf, in_refs, in_app = name, [], False, True
                continue
            if in_refs and not (m.group(1) is None and low.startswith("appendix")):
                continue  # numbered lines inside the bibliography
            flush(); title, buf = name, []
            continue
        if in_app and re.match(r"^[A-Z](?:\.\d+)*\.?\s+[A-Z][^\n]{2,80}$", ln):
            sections.append({"title": ln, "text": ""})
            continue
        buf.append(ln)
    flush()
    return [s for s in sections if not REFERENCES_RE.match(s["title"])]


def parse_pdf(data: bytes) -> list[dict]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    raw = "\n".join((page.extract_text() or "") for page in reader.pages)
    return parse_pdf_text(raw)


# ------------------------------------------------------------------ fetch
def _get(url: str, timeout: int = 60) -> requests.Response | None:
    try:
        r = requests.get(url, headers=_headers(), timeout=timeout)
    except requests.RequestException as e:
        log.warning("fulltext: %s failed (%s)", url, str(e)[:120])
        return None
    return r


def _download_pdf(url: str | None) -> bytes | None:
    if not url:
        return None
    r = _get(url, timeout=120)
    if r is not None and r.status_code == 200 and r.content[:4] == b"%PDF":
        return r.content
    log.warning("fulltext: PDF %s not available", url)
    return None


def fetch(paper: dict) -> dict:
    aid = _arxiv_id(paper)
    pdf_url = paper.get("pdf_url") or (f"https://arxiv.org/pdf/{aid}" if aid else None)
    html_url = paper.get("html_url") or (f"https://arxiv.org/html/{aid}" if aid else None)
    reasons: list[str] = []
    sections, source = None, None

    if html_url:
        r = _get(html_url)
        if r is None:
            reasons.append("HTML page could not be reached")
        elif r.status_code != 200:
            reasons.append(f"no HTML version (HTTP {r.status_code})")
        else:
            try:
                secs = parse_html(r.text)
                why = _check(secs, _assemble(secs))
                if why is None:
                    sections, source = secs, "html"
                else:
                    reasons.append(f"HTML text unusable: {why}")
            except Exception as e:  # parser problems must not kill the run
                reasons.append(f"HTML could not be parsed ({str(e)[:80]})")

    pdf_bytes = _download_pdf(pdf_url)
    if sections is None:
        if pdf_bytes is None:
            reasons.append("no PDF available")
        else:
            try:
                secs = parse_pdf(pdf_bytes)
                why = _check(secs, _assemble(secs))
                if why is None:
                    sections, source = secs, "pdf"
                else:
                    reasons.append(f"PDF text unusable: {why}")
            except Exception as e:
                reasons.append(f"PDF could not be read ({str(e)[:80]})")
    if sections is None:
        raise FulltextError("Full text not available: " + "; ".join(reasons))
    return {"text": _assemble(sections), "sections": sections, "source": source, "pdf_bytes": pdf_bytes}


# ------------------------------------------------------------------ chunks
def chunks(ft: dict, max_tokens: int) -> list[str]:
    """Split on section lines; a section longer than the limit is split on its lines."""
    limit = int(max_tokens * CHARS_PER_TOKEN)
    pieces: list[str] = []
    for s in ft["sections"]:
        block = f"## {s['title']}\n{s['text']}".strip()
        if len(block) <= limit:
            pieces.append(block)
            continue
        head, cur = f"## {s['title']} (continued)\n", ""
        for ln in block.splitlines():
            while len(ln) > limit:  # one absurdly long line
                if cur:
                    pieces.append(cur); cur = ""
                pieces.append(ln[:limit]); ln = ln[limit:]
            if len(cur) + len(ln) + 1 > limit and cur:
                pieces.append(cur)
                cur = head
            cur += ln + "\n"
        if cur.strip():
            pieces.append(cur.rstrip())
    out, cur = [], ""
    for p in pieces:
        if cur and len(cur) + len(p) + 2 > limit:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        out.append(cur)
    return out
