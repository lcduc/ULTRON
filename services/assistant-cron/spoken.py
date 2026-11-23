"""Spoken evening briefing: a short script written by code, turned into an MP3 by Kokoro.

Nothing here may break the briefing: callers treat any exception as "no audio".
"""

import logging
import os
import re
import unicodedata

import requests

log = logging.getLogger("briefing")

DEFAULTS = {"enabled": True, "voice": "am_michael", "max_items": 6, "max_words": 90, "title_chars": 60,
            "attach_to_push": False}
MAX_BYTES = 2 * 1024 * 1024
NUMBERS = ["twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven"]
TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty"}
TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]


def settings(cfg) -> dict:
    s = dict(DEFAULTS)
    s.update(cfg.get("spoken") or {})
    return s


def minute_words(m) -> str:
    if m < 10:
        return "oh " + NUMBERS[m] if m else ""
    if m < 20:
        return TEENS[m - 10]
    return TENS[m // 10 * 10] + (" " + NUMBERS[m % 10] if m % 10 else "")


def time_words(hhmm) -> str:
    """'14:00' -> 'two p.m.', '09:30' -> 'nine thirty a.m.', '12:00' -> 'noon'."""
    h, m = (int(x) for x in hhmm.split(":")[:2])
    if (h, m) == (12, 0):
        return "noon"
    if (h, m) == (0, 0):
        return "midnight"
    parts = [NUMBERS[h % 12], minute_words(m)]
    return " ".join(p for p in parts if p) + (" p.m." if h >= 12 else " a.m.")


def clean(text, n=60) -> str:
    """Letters, digits and basic punctuation only; cut at a word boundary near n characters."""
    text = re.sub(r"https?://\S+", " ", str(text or ""))
    text = re.sub(r"(?<!\w)w/", "with ", text).replace("&", " and ").replace("@", " at ").replace("%", " percent ")
    text = "".join(c if (c.isalnum() or c in " ,.'-") else " " for c in text
                   if unicodedata.category(c) not in ("So", "Sk", "Cs") and ord(c) < 0x1F000)
    text = re.sub(r"\s+", " ", text).strip(" ,.-")
    if len(text) > n:
        text = text[:n].rsplit(" ", 1)[0].rstrip(" ,.-") or text[:n]
    return text


def script(cfg, data, day, tip, build_schedule) -> str:
    """The spoken text. build_schedule is briefing.build_schedule (passed in to avoid a circular import)."""
    s = settings(cfg)
    max_items, max_words, tn = int(s["max_items"]), int(s["max_words"]), int(s["title_chars"])
    sched = build_schedule(data, "evening") if ("calendar" in data or "tasks" in data) else None
    weather = ""
    if "weather" in data:
        w = data["weather"]
        weather = f"Weather in {clean(w['city'], 30)}: {clean(w['condition'], 40)}, {w['tmin']} to {w['tmax']} degrees"
        weather += f", rain chance {w['rain']} percent." if w["rain"] >= 30 else "."
        if clean(tip, 100):
            weather += " " + clean(tip, 100).rstrip(".") + "."
    for shown in range(max_items, 0, -1):
        parts = [f"Good evening, sir. Tomorrow, {day.strftime('%A')}"]
        if sched is None:
            parts[0] += ", I could not read your schedule."
        elif not sched:
            parts[0] = "Good evening, sir. Tomorrow is clear."
        else:
            events = [i for i in sched[:shown] if i["kind"] == "event"]
            tasks = [i for i in sched[:shown] if i["kind"] == "task"]
            bits = []
            for e in events:
                t = clean(e["title"], tn)
                bits.append(f"at {time_words(e['start'])}, {t}" if e.get("start") else f"all day, {t}")
            text = "; ".join(bits)
            if tasks:
                names = ", ".join(("overdue, " if t.get("overdue") else "") + clean(t["title"], tn) for t in tasks)
                text += ("; " if text else "") + f"tasks due: {names}"
            parts[0] += ": " + text + "."
            if len(sched) > shown:
                parts.append(f"And {len(sched) - shown} more.")
        if weather:
            parts.append(weather)
        out = " ".join(parts)
        if len(out.split()) <= max_words:
            return out
    return out


def synth(cfg, text) -> bytes:
    """Kokoro text-to-speech, MP3 bytes. One retry; rejects empty or oversized output."""
    base = os.environ.get("KOKORO_URL", "http://kokoro:8880/v1").rstrip("/")
    body = {"model": "kokoro", "voice": settings(cfg)["voice"], "input": text, "response_format": "mp3"}
    last = None
    for _ in range(2):
        try:
            r = requests.post(base + "/audio/speech", json=body, timeout=60)
            r.raise_for_status()
            if not r.content or len(r.content) > MAX_BYTES:
                raise ValueError(f"unusable audio ({len(r.content)} bytes)")
            return r.content
        except Exception as e:
            last = e
    raise last
