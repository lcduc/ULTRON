"""Rain alerts: one push when rain is about to start. Used by briefing.py's scheduler.

Every rain_alerts.check_minutes the scheduler calls check(). Code decides everything, no model:
it is dry now, rain is likely to start within lookahead_minutes (a 15-minute forecast slot with
rain, backed by the hourly rain chance), it is not quiet hours, nothing was sent in the last
cooldown_hours (a rain warning from a time-to-leave reminder counts) and the rain is not already in
the morning briefing's rain window. The alert time is saved before sending; if the state file cannot
be read or written nothing is sent (fail closed, never risk a repeat).

The helpers of briefing.py (push, chat link, state) are passed in as `B` to avoid a circular import.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import reminders

log = logging.getLogger("rain")

STATE_PATH = Path(os.environ.get("RAIN_STATE", "/app/state/rain.json"))
DEFAULTS = {
    "enabled": False, "check_minutes": 15, "lookahead_minutes": 60, "cooldown_hours": 3,
    "quiet_start": "22:00", "quiet_end": "06:00",
}
DRY_MM = 0.1  # below this a slot or the current reading counts as dry


def settings(cfg) -> dict:
    return {**DEFAULTS, **(cfg.get("rain_alerts") or {})}


# ---------------------------------------------------------------------------- state (fail closed)

def load_state(path: Path) -> dict:
    """{"last_alert": unix_time or None}. A missing file is an empty state; any other problem raises."""
    if not path.exists():
        return {"last_alert": None}
    data = json.loads(path.read_text(encoding="utf-8"))
    last = data.get("last_alert")
    return {"last_alert": None if last is None else float(last)}


def save_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".rain-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def note_warning(now, path: Path = None):
    """A time-to-leave reminder just warned about rain: count it as a rain alert (cooldown)."""
    path = path or STATE_PATH
    state = load_state(path)
    state["last_alert"] = now.timestamp()
    save_state(path, state)


# ---------------------------------------------------------------------------- data

def fetch_forecast(cfg):
    """(current, slots, hourly) from Open-Meteo. Outside Europe and North America the 15-minute
    values are interpolated from hourly data, which is fine for a heads-up."""
    import requests

    c = cfg["city"]
    r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=20, params={
        "latitude": c["latitude"], "longitude": c["longitude"], "timezone": cfg["timezone"],
        "current": "precipitation,rain,weather_code",
        "minutely_15": "precipitation,rain,weather_code",
        "hourly": "precipitation_probability", "forecast_days": 2})
    r.raise_for_status()
    d = r.json()
    m, h = d["minutely_15"], d["hourly"]
    slots = [{"time": t, "precipitation": p, "weather_code": w}
             for t, p, w in zip(m["time"], m["precipitation"], m["weather_code"])]
    hourly = [{"time": t, "precipitation_probability": p}
              for t, p in zip(h["time"], h["precipitation_probability"])]
    cur = d.get("current") or {}
    return {"precipitation": cur.get("precipitation"), "weather_code": cur.get("weather_code")}, slots, hourly


def load_fixture(path):
    """{"current": {precipitation, weather_code}, "minutely_15": [{time, precipitation, weather_code}],
    "hourly": [{time, precipitation_probability}], "morning_window": {date, start, end} (optional)}.
    Times are local, like "2026-11-24T14:15"."""
    fx = json.loads(Path(path).read_text(encoding="utf-8"))
    return (fx.get("current") or {}), fx.get("minutely_15", []), fx.get("hourly", []), fx.get("morning_window")


# ---------------------------------------------------------------------------- rules

def is_rain(precipitation, code) -> bool:
    return (precipitation or 0) >= DRY_MM or code in reminders.RAIN_CODES


def raining_now(current) -> bool:
    return is_rain(current.get("precipitation"), current.get("weather_code"))


def find_onset(slots, hourly, now, lookahead, threshold):
    """Start of the first future 15-minute slot (start > now, start <= now + lookahead minutes) with
    rain whose hour has a rain chance >= threshold. No chance data for that hour = rain alone is enough."""
    horizon = now + timedelta(minutes=lookahead)
    prob = {h.get("time"): h.get("precipitation_probability") for h in hourly}
    for s in sorted(slots, key=lambda x: x["time"]):
        start = datetime.fromisoformat(s["time"]).replace(tzinfo=now.tzinfo)
        if not (now < start <= horizon) or not is_rain(s.get("precipitation"), s.get("weather_code")):
            continue
        p = prob.get(start.strftime("%Y-%m-%dT%H:00"))
        if p is None or p >= threshold:
            return start
    return None


def in_morning_window(window, onset) -> bool:
    """True if the onset falls in [start, end) of today's window from the morning briefing."""
    if not window or window.get("date") != onset.date().isoformat():
        return False
    start, end = window.get("start"), window.get("end")
    if not start or not end:
        return False
    return start <= f"{onset:%H:%M}" < end  # "24:00" sorts after every time of day


def alert_text(onset, now) -> str:
    minutes = (onset - now).total_seconds() / 60
    if minutes <= 10:
        return "Rain expected within minutes, sir. Take the umbrella if you're heading out."
    n = max(5, int(minutes / 5 + 0.5) * 5)
    return f"Rain expected in about {n} minutes, sir. Take the umbrella if you're heading out."


# ---------------------------------------------------------------------------- check

def check(B, cfg, now, *, state_path=STATE_PATH, briefing_state_path=None, dry_run=False, fixture=None):
    """Sends (or, in a dry run, prints) a rain alert if one is due. Returns the text or None.
    The morning rain window comes from the briefing state (briefing_state_path, default the real one);
    a dry run never reads it, a fixture supplies "morning_window" instead."""
    s = settings(cfg)

    def skip(reason):
        log.info("rain: %s", reason)
        if dry_run:
            print(f"REASON: {reason}")
        return None

    if reminders.in_quiet(now, s):
        return skip("quiet hours")
    try:
        state = load_state(state_path)
    except Exception as e:
        log.warning("rain: state file unreadable (%s); sending nothing", B.cut(e, 100))
        return skip("state file unreadable")
    last = state["last_alert"]
    if last is not None and 0 <= now.timestamp() - last < float(s["cooldown_hours"]) * 3600:
        return skip(f"cooldown (last alert {datetime.fromtimestamp(last, now.tzinfo):%H:%M})")
    window = None
    try:
        if fixture:
            current, slots, hourly, window = load_fixture(fixture)
        else:
            current, slots, hourly = fetch_forecast(cfg)
    except Exception as e:
        log.warning("rain: forecast unavailable (%s)", B.cut(e, 100))
        return skip("forecast unavailable")
    if current.get("precipitation") is None and current.get("weather_code") is None:
        return skip("no current weather reading")
    if raining_now(current):
        return skip("already raining")
    onset = find_onset(slots, hourly, now, int(s["lookahead_minutes"]),
                       reminders.settings(cfg)["rain_threshold"])
    if onset is None:
        return skip(f"no rain likely in the next {int(s['lookahead_minutes'])} minutes")
    if not fixture and not dry_run:
        window = B.load_state(briefing_state_path or B.STATE_PATH).get("rain")
    if in_morning_window(window, onset):
        return skip(f"rain at {onset:%H:%M} already in the morning forecast")
    text = alert_text(onset, now)
    # Remember it first and fail closed: if this cannot be saved, nothing is sent.
    state["last_alert"] = now.timestamp()
    try:
        save_state(state_path, state)
    except Exception as e:
        log.warning("rain: state file not writable (%s); sending nothing", B.cut(e, 100))
        return skip("state file not writable")
    if dry_run:
        print(f"PUSH: {text}\nONSET: {onset:%H:%M}\nREASON: rain likely at {onset:%H:%M}, dry now")
    else:
        try:
            B.send(cfg, "Ultron — rain", text, B.chat_url("", cfg.get("model", "ultron")))
        except Exception:
            log.exception("rain push failed (not retried)")
    log.info("rain alert %s: onset %s", "previewed" if dry_run else "sent", f"{onset:%H:%M}")
    return text
