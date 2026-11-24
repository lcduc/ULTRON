"""Code checks on model output: numbers, quotes and cross-references must exist in the paper."""

import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

_NUM = re.compile(
    r"(?<![\w.])(?:(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<frac>\.\d+)?|(?P<lead>\.\d+))"
    r"(?:(?P<suf>\s?%|\spercent\b|[BMKT](?![A-Za-z])|[x×](?![A-Za-z])))?")
_MATH = re.compile(r"\$\$.*?\$\$|\$[^$\n]+\$", re.S)
_CITE = re.compile(r"\[\s*\d+(?:\s*[,–-]\s*\d+)*\s*\]")
_FENCE = re.compile(r"```.*?```", re.S)
_LABEL_BEFORE = re.compile(
    r"(§|\bsections?|\bsec\.|\btables?|\btab\.|\bfig\.?|\bfigures?|\bfigs\.|\beq\.?|\bequations?|\bappendix|"
    r"\bchapter|\bstep|\bpart|\balgorithm|\bline|\bpage|\bpp?\.|\bpoint|\bpoints|\bnote|\bq)\s*\(?$", re.I)


def _canon(m: re.Match) -> tuple[str, str]:
    """(canonical text, value as string) for a number match."""
    if m.group("lead"):
        num = "0" + m.group("lead")
    else:
        num = m.group("int").replace(",", "") + (m.group("frac") or "")
    try:
        val = Decimal(num).normalize()
        val_s = format(val, "f")
    except InvalidOperation:
        val_s = num
    suf = m.group("suf") or ""
    suf = suf.strip()
    suf = "%" if suf.lower() == "percent" else suf.replace("×", "x")
    return val_s + suf, val_s


def _all_numbers(text: str) -> list[tuple[str, str, int]]:
    """All numbers outside math, with (canonical, value, start) - no ignore rules."""
    text = _MATH.sub(" ", text)
    text = _CITE.sub(" ", text)
    out = []
    for m in _NUM.finditer(text):
        canon, val = _canon(m)
        out.append((canon, val, m.start()))
    return out


def _ignored(text: str, start: int, canon: str, val: str) -> bool:
    before = text[max(0, start - 14):start]
    if _LABEL_BEFORE.search(before):
        return True
    line_start = text.rfind("\n", 0, start) + 1
    if re.fullmatch(r"\s*[-*>]?\s*\d{1,2}[.)]\s*", text[line_start:start]):
        return True  # list numbering
    if canon == val:  # bare number without a unit
        if re.fullmatch(r"\d", val) or val == "10":
            return True  # list numbers 1-10
        if re.fullmatch(r"(19|20)\d\d", val):
            return True  # years
        if "." in val and re.fullmatch(r"\d{1,2}\.\d{1,2}", val) and _LABEL_BEFORE.search(text[max(0, start - 14):start]):
            return True
    return False


def numbers_in(text: str) -> list[str]:
    """Numbers worth checking in text (12.3, 45%, 7B, 1024). Normalised, in order, no duplicates.
    Ignores list numbers 1-10, years, section/table/figure numbers, citations [12] and math."""
    text = _FENCE.sub(" ", text)
    clean = _MATH.sub(lambda m: " " * len(m.group(0)), text)
    clean = _CITE.sub(lambda m: " " * len(m.group(0)), clean)
    seen, out = set(), []
    for m in _NUM.finditer(clean):
        canon, val = _canon(m)
        if _ignored(clean, m.start(), canon, val):
            continue
        if canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def unsupported_numbers(text: str, source: str) -> list[str]:
    """Numbers in text that do not occur in source. Compared by value: 1,024 = 1024, 0.5 = .5,
    45% = 45 % = 45.0, 7B matches 7."""
    have = {val for _, val, _ in _all_numbers(source)}
    # numbers inside math in the source count too (alt text like $0.5$)
    for m in _NUM.finditer(source):
        have.add(_canon(m)[1])
    bad = []
    for canon in numbers_in(text):
        val = re.match(r"\d+(?:\.\d+)?", canon).group(0)
        if val not in have:
            bad.append(canon)
    return bad


# ------------------------------------------------------------------ quotes
def _tokens(s: str) -> list[str]:
    s = s.lower().replace("’", "'").replace("–", "-").replace("—", "-")
    s = re.sub(r"(\d),(\d{3})", r"\1\2", s)
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", s)


def quote_ok(quote: str, source: str) -> bool:
    """The quote's tokens (normalised: case, punctuation, spacing) appear in order in the source:
    at least 90% of them, within one stretch of text."""
    q = _tokens(quote)
    if not q:
        return False
    src = _tokens(source)
    if not src:
        return False
    joined_src = " ".join(src)
    if " ".join(q) in joined_src:
        return True
    if len(q) < 4:
        return False
    qset = set(q)
    anchors = [i for i, t in enumerate(src) if t in qset and (t in q[:4] or t in q[-4:])]
    checked_to = -1
    for i in anchors:
        if i < checked_to:
            continue
        lo, hi = max(0, i - len(q)), min(len(src), i + 2 * len(q))
        checked_to = i + len(q) // 2
        sm = SequenceMatcher(None, q, src[lo:hi], autojunk=False)
        matched = sum(b.size for b in sm.get_matching_blocks())
        if matched / len(q) >= 0.9:
            return True
    return False


# ------------------------------------------------------------------ references
_SEC = re.compile(r"(?:§+|\b[Ss]ections?\s|\b[Ss]ec\.\s?)\s*(\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\b")
_TAB = re.compile(r"\b[Tt]ables?\s+(\d+|[A-Z]\.\d+|[IVX]+)\b")
_FIG = re.compile(r"\b(?:Fig\.|Figs\.|Figure|Figures)\s*(\d+|[A-Z]\.\d+)")
_EQ = re.compile(r"\b(?:Eq\.|Eqs\.|Equation|Equations)\s*\(?(\d+)\)?")


def _paper_text(sections) -> str:
    if isinstance(sections, str):
        return sections
    return "\n".join(f"{s.get('title', '')}\n{s.get('text', '')}" for s in sections)


def refs_ok(text: str, sections) -> list[str]:
    """References in text (section N.M, Table N, Fig. N, Eq. N) that the paper does not contain.
    Returns the bad references as written."""
    paper = _paper_text(sections)
    bad: list[str] = []
    text = _FENCE.sub(" ", text)

    def has_section(num: str) -> bool:
        pat = re.escape(num)
        if re.search(rf"(?m)^\W*(?:Appendix\s+)?{pat}\.?(?:\s|$)", paper):
            return True
        if re.search(rf"(?m)^\W*(?:Appendix\s+)?{pat}\.\d", paper):
            return True  # a subsection of it exists
        if re.search(rf"(?:§|[Ss]ections?\s|[Ss]ec\.\s?){pat}\b", paper):
            return True
        return False

    def has_label(pattern: str, num: str) -> bool:
        return bool(re.search(pattern.format(re.escape(num)), paper, re.I))

    for m in _SEC.finditer(text):
        if not has_section(m.group(1)):
            bad.append(m.group(0).strip())
    for m in _TAB.finditer(text):
        n = m.group(1)
        if not (has_label(r"\btab(?:le|\.)?\s*{}\b", n) or has_label(r"\btables?\s*\(?{}\b", n)):
            bad.append(m.group(0).strip())
    for m in _FIG.finditer(text):
        n = m.group(1)
        if not has_label(r"\b(?:fig\.?|figure)s?\s*{}\b", n):
            bad.append(m.group(0).strip())
    for m in _EQ.finditer(text):
        n = m.group(1)
        if not (has_label(r"\b(?:eq\.?|equation)s?\s*\(?{}\)?", n) or re.search(rf"\({re.escape(n)}\)", paper)):
            bad.append(m.group(0).strip())
    seen, out = set(), []
    for b in bad:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out
