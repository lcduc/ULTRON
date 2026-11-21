"""Morning briefing and evening preview, pushed to the phone.

Run with no arguments: a small long-lived scheduler that sends each briefing at the times in
config.yaml. Run with `--run morning|evening [--dry-run] [--no-model]` to send or preview one now.

Each data section (calendar, tasks, mail, weather, news) is independent: if one fails it becomes
one short "not available" line and the rest still go out. The chat model writes the text; if it
cannot be reached for model_wait_minutes, a plain bullet list is sent instead.
"""

import argparse
import importlib
import inspect
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

CONFIG_PATH = Path(os.environ.get("BRIEFING_CONFIG", "/app/config.yaml"))
HEARTBEAT = Path("/tmp/heartbeat")
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080/search")
MAX_BODY = 600
LATE_GRACE_HOURS = 4  # still send if the container was down at the scheduled time

log = logging.getLogger("briefing")

WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers",
    81: "showers", 82: "heavy showers", 85: "snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}


class SectionError(Exception):
    pass


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def short(text, n=80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "..."


def make(module: str, method: str):
    """Import a shared module lazily and build the first class in it that has `method`."""
    try:
        mod = importlib.import_module(module)
    except ImportError as e:
        raise SectionError(f"{module} is not installed ({e.name or e})")
    for _, cls in inspect.getmembers(mod, inspect.isclass):
        if cls.__module__ == mod.__name__ and hasattr(cls, method):
            return cls()
    raise SectionError(f"{module} has no class with {method}()")


# ---------------------------------------------------------------------------- sections
# Each returns a list of plain-text lines, or raises. `day` is a date in the local time zone.

def sec_calendar(cfg, day, mode):
    from calendar_api import Calendar  # shared code from mcp/google-calendar

    cal = Calendar()
    cal.timezone = cal.timezone or cfg["timezone"]
    data = cal.list_events(start_date=day.isoformat(), days=1)
    lines = []
    for ev in data["events"]:
        when = ev["when"]
        # "Sat 2026-11-21 13:00-14:00" -> "13:00-14:00"; "2026-11-21 (all day)" -> "all day"
        when = "all day" if "(all day)" in when else when.split(" ", 2)[-1]
        loc = f" @ {short(ev['location'], 30)}" if ev.get("location") else ""
        lines.append(f"{when} {short(ev['title'], 60)}{loc}")
    return lines or ["No events."]


def sec_tasks(cfg, day, mode):
    api = make("tasks_api", "list_tasks")
    tasks = api.list_tasks(list_name="To-do", include_done=False)["tasks"]
    today = datetime.now(ZoneInfo(cfg["timezone"])).date().isoformat()
    lines = []
    for t in tasks:
        due_date = (t.get("due_date") or "")[:10]
        if not due_date or due_date > day.isoformat():
            continue
        tag = "overdue: " if due_date < today else ""
        lines.append(f"{tag}{short(t['title'], 70)}")
    return lines or ["Nothing due."]


def sec_mail(cfg, day, mode):
    api = make("gmail_api", "search_mail")
    n = int(cfg.get("mail_max_unread", 15))
    msgs = api.search_mail("is:unread newer_than:1d", max_results=n)
    lines = []
    for m in msgs[:n]:
        sender = m.get("from", "").split("<")[0].strip().strip('"') or m.get("from", "")
        lines.append(f"{short(sender, 30)}: {short(m.get('subject', ''), 70)}")
    return lines or ["No new unread mail."]


def sec_weather(cfg, day, mode):
    c = cfg["city"]
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": c["latitude"], "longitude": c["longitude"], "timezone": cfg["timezone"],
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "forecast_days": 3,
        },
        timeout=20,
    )
    r.raise_for_status()
    d = r.json()["daily"]
    if day.isoformat() not in d["time"]:
        raise SectionError("date missing in forecast")
    i = d["time"].index(day.isoformat())
    cond = WMO.get(d["weather_code"][i], "mixed")
    return [
        f"{c['name']}: {cond}, {round(d['temperature_2m_min'][i])}-{round(d['temperature_2m_max'][i])} C, "
        f"rain chance {d['precipitation_probability_max'][i]}%"
    ]


def sec_news(cfg, day, mode):
    results = []
    for extra in ({"time_range": "day"}, {}):  # prefer today's news, else whatever the engines return
        r = requests.get(
            SEARXNG_URL,
            params={"q": cfg.get("news_query", "world news headlines"), "format": "json", "categories": "news", **extra},
            timeout=30,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if results:
            break
    seen, lines = set(), []
    for item in results:
        title = short(item.get("title", ""), 90)
        if title and title.lower() not in seen:
            seen.add(title.lower())
            lines.append(title)
        if len(lines) >= int(cfg.get("news_count", 3)):
            break
    if not lines:
        raise SectionError("no results")
    return lines


SECTIONS = [
    ("calendar", "Calendar", sec_calendar),
    ("tasks", "Tasks", sec_tasks),
    ("mail", "Mail", sec_mail),
    ("weather", "Weather", sec_weather),
    ("news", "News", sec_news),
]


def gather(cfg, mode):
    """Returns (ok, failed, day): ok = [(label, lines)], failed = [line]. One log line per section."""
    tz = ZoneInfo(cfg["timezone"])
    today = datetime.now(tz).date()
    day = today if mode == "morning" else today + timedelta(days=1)
    enabled = cfg.get("sections", {}).get(mode, {})
    ok, failed = [], []
    for key, label, fn in SECTIONS:
        if not enabled.get(key, False):
            continue
        try:
            lines = fn(cfg, day, mode)
            ok.append((label, lines))
            log.info("section %s: ok (%d lines)", key, len(lines))
        except Exception as e:  # a failed section must never stop the briefing
            reason = short(e if isinstance(e, SectionError) else f"{type(e).__name__}: {e}", 90)
            failed.append(f"{label}: not available ({reason})")
            log.warning("section %s: FAILED %s", key, reason)
    return ok, failed, day


# ---------------------------------------------------------------------------- writing

def plain_body(ok):
    return "\n".join(f"{label}: " + "; ".join(lines[:5]) for label, lines in ok)


def clip(text, n=MAX_BODY):
    text = text.strip()
    if len(text) <= n:
        return text
    cut = text[:n]
    if "\n" in cut:
        cut = cut.rsplit("\n", 1)[0]
    return cut.rstrip() + "..."


def model_text(cfg, ok, mode, day):
    """One call to the chat model; retries until model_wait_minutes. Returns text or None."""
    base = os.environ.get("OPENAI_API_BASE_URL", "").rstrip("/")
    key = os.environ.get("OPENAI_API_KEY", "")
    if not base:
        log.warning("model: OPENAI_API_BASE_URL not set")
        return None
    data = "\n".join(f"## {label}\n" + "\n".join(f"- {l}" for l in lines) for label, lines in ok)
    when = "today" if mode == "morning" else "tomorrow"
    system = (
        "You write a short phone notification for one person. English, plain text only: no markdown, "
        f"no emojis, no greeting. At most 6 short lines and under {MAX_BODY - 100} characters in total. "
        "Use only the facts given; never invent anything. Start with the most time-critical item. "
        f"For mail, name at most {int(cfg.get('mail_top', 5))} important messages (sender and subject, "
        "a few words) and ignore newsletters and promotions. Keep news to short headlines."
    )
    user = f"Write the {mode} briefing for {when} ({day:%A %d %B}).\n\n{data}"
    deadline = time.time() + float(cfg.get("model_wait_minutes", 30)) * 60
    timeout = float(cfg.get("model_timeout_seconds", 180))
    attempt = 0
    while True:
        attempt += 1
        try:
            r = requests.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": cfg.get("model", "ultron"),
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "temperature": 0.3,
                    "max_tokens": 400,
                },
                timeout=timeout,
            )
            r.raise_for_status()
            text = (r.json()["choices"][0]["message"].get("content") or "").strip()
            if text:
                log.info("model: ok on attempt %d (%d chars)", attempt, len(text))
                return text
            log.warning("model: empty answer (attempt %d)", attempt)
        except Exception as e:
            log.warning("model: attempt %d failed: %s", attempt, short(e, 120))
        if time.time() + 60 >= deadline:
            log.warning("model: giving up, sending plain list")
            return None
        time.sleep(60)


# ---------------------------------------------------------------------------- sending

def new_chat_url(model="ultron"):
    """Link for tapping a push: a fresh Ultron chat with the chat model selected.
    Open WebUI reads ?models=<id> on its new-chat page. On iPhone it opens in Safari."""
    base = os.environ.get("ULTRON_PUBLIC_URL", "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/?models={model}"


def push_ntfy(title, body, model="ultron"):
    url = os.environ.get("NTFY_URL", "http://ntfy:80").rstrip("/")
    payload = {"topic": os.environ["NTFY_TOPIC"], "title": title, "message": body}
    click = new_chat_url(model)
    if click:
        payload["click"] = click
    r = requests.post(
        url, json=payload, headers={"Authorization": f"Bearer {os.environ['NTFY_TOKEN']}"}, timeout=20
    )
    r.raise_for_status()


def push_email(title, body):
    make("gmail_api", "send_to_self").send_to_self(title, body)


def send(cfg, title, body):
    if cfg.get("channel", "ntfy") != "email":
        try:
            push_ntfy(title, body, cfg.get("model", "ultron"))
            log.info("sent via ntfy")
            return
        except Exception as e:
            log.warning("ntfy failed (%s); trying email", short(e, 120))
    push_email(title, body)
    log.info("sent via email")


# ---------------------------------------------------------------------------- run

def run(mode, dry_run=False, no_model=False):
    cfg = load_config()
    ok, failed, day = gather(cfg, mode)
    text = None
    if ok and not no_model:
        text = model_text(cfg, ok, mode, day)
    if text is None:
        text = plain_body(ok)
    body = clip(text)
    if failed:
        body = (body + "\n" if body else "") + "\n".join(failed)
    if not body:
        body = "Nothing to report."
    title = f"Ultron — {mode}"
    if dry_run:
        click = new_chat_url(cfg.get("model", "ultron"))
        print(f"TITLE: {title}\nCLICK: {click}\n---\n{body}\n---\n({len(body)} chars)")
        return
    send(cfg, title, body)


def due(cfg, mode, now, done):
    t = (cfg.get("times", {}) or {}).get(mode) or ""
    if not t:
        return False
    if now.strftime("%A") in (cfg.get("quiet_days") or []):
        return False
    h, m = map(int, t.split(":"))
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return at <= now < at + timedelta(hours=LATE_GRACE_HOURS) and done.get(mode) != now.date()


def scheduler():
    done = {}
    log.info("scheduler started")
    while True:
        try:
            HEARTBEAT.write_text(str(time.time()))
            cfg = load_config()
            now = datetime.now(ZoneInfo(cfg["timezone"]))
            for mode in ("morning", "evening"):
                if due(cfg, mode, now, done):
                    done[mode] = now.date()  # mark first: never send twice, even if it fails
                    log.info("running %s briefing", mode)
                    try:
                        run(mode)
                    except Exception:
                        log.exception("%s briefing failed", mode)
        except Exception:
            log.exception("scheduler loop error")
        time.sleep(20)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", choices=["morning", "evening"])
    ap.add_argument("--dry-run", action="store_true", help="print instead of sending")
    ap.add_argument("--no-model", action="store_true", help="skip the model, use the plain list")
    args = ap.parse_args()
    if args.run:
        run(args.run, args.dry_run, args.no_model)
    else:
        scheduler()


if __name__ == "__main__":
    main()
