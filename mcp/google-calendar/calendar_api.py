"""Google Calendar logic: sign-in, API calls, date parsing and the safety checks.

Nothing in this file knows about MCP. It is plain Python that takes simple arguments and
returns dicts, so it can be tested on its own. server.py turns these methods into MCP tools.

Ported from tools/google_calendar.py (the Open WebUI tool), with the same behaviour.
"""

import os
import time
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
# Private extended property marking events the assistant created.
MARK_KEY = "createdBy"
MARK_VALUE = "ultron"


class CalendarError(Exception):
    """A problem the model should read and react to (bad date, clash, missing sign-in...)."""


def _env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Calendar:
    def __init__(self):
        # Settings come from environment variables (set in compose/docker-compose.yml).
        self.client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        self.client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
        self.refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
        self.calendar_id = os.environ.get("CALENDAR_ID", "primary")
        self.timezone = os.environ.get("CALENDAR_TIMEZONE", "")
        self.default_duration = int(os.environ.get("DEFAULT_DURATION_MINUTES", "60"))
        self.default_reminders = os.environ.get("DEFAULT_REMINDER_MINUTES", "30")
        self.allow_changing_others = _env_bool("ALLOW_CHANGING_OTHER_EVENTS", False)
        self._token: Optional[str] = None
        self._token_expiry = 0.0
        self._tz_name: Optional[str] = None

    # ------------------------------------------------------------------ Google sign-in and HTTP

    def _get_token(self) -> str:
        """Swap the long-lived refresh token for a one-hour access token, and cache it."""
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        if not (self.client_id and self.client_secret and self.refresh_token):
            raise CalendarError(
                "Google Calendar is not connected: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET or "
                "GOOGLE_REFRESH_TOKEN is missing in the calendar-mcp container. Tell the user to run "
                "scripts/google-auth.py and restart the container."
            )
        r = requests.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        if r.status_code != 200:
            detail = r.json().get("error", r.text[:200]) if r.content else r.status_code
            raise CalendarError(
                f"Google sign-in failed ({detail}). The saved permission has probably expired or "
                "been revoked. Tell the user to run scripts/google-auth.py again."
            )
        data = r.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _call(self, method: str, path: str, params=None, body=None) -> dict:
        """One Calendar API request. Retries once with a fresh token if Google says 401."""
        url = f"{API}/calendars/{requests.utils.quote(self.calendar_id, safe='')}{path}"
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {self._get_token()}"}
            r = requests.request(method, url, params=params, json=body, headers=headers, timeout=20)
            if r.status_code == 401 and attempt == 0:
                self._token = None
                continue
            break
        if r.status_code == 204:
            return {}
        if r.status_code >= 400:
            try:
                msg = r.json()["error"]["message"]
            except Exception:
                msg = r.text[:300]
            raise CalendarError(f"Google Calendar error {r.status_code}: {msg}")
        return r.json()

    # ------------------------------------------------------------------ helpers

    def _tz(self) -> ZoneInfo:
        if self.timezone:
            return ZoneInfo(self.timezone)
        if not self._tz_name:
            # events.list returns the calendar's time zone and only needs the events scope.
            data = self._call("GET", "/events", params={"maxResults": 1})
            self._tz_name = data.get("timeZone") or "UTC"
        return ZoneInfo(self._tz_name)

    def _parse_when(self, text: str, tz: ZoneInfo):
        """Return (datetime or date, is_date_only)."""
        text = (text or "").strip().replace("/", "-")
        if not text:
            raise CalendarError("A start date/time is required, e.g. '2026-11-22 13:00'.")
        if len(text) == 10:
            try:
                return date.fromisoformat(text), True
            except ValueError:
                pass
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise CalendarError(
                f"Could not read the date/time '{text}'. Use the format YYYY-MM-DD HH:MM, "
                "e.g. '2026-11-22 13:00'. Call calendar_today to get exact dates."
            )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt, False

    def _reminders(self, text: str) -> dict:
        text = str(text if text not in (None, "") else self.default_reminders)
        minutes = []
        for part in text.replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                m = int(float(part))
            except ValueError:
                raise CalendarError(f"Reminder '{part}' is not a number of minutes.")
            if not 0 <= m <= 40320:
                raise CalendarError("Reminders must be between 0 and 40320 minutes (4 weeks) before.")
            minutes.append(m)
        minutes = sorted(set(minutes))[:5]
        return {"useDefault": False, "overrides": [{"method": "popup", "minutes": m} for m in minutes]}

    def _describe(self, ev: dict, tz: ZoneInfo) -> dict:
        """Turn a raw Google event into the short summary the model sees."""
        start, end = ev.get("start", {}), ev.get("end", {})
        if "date" in start:
            when = f"{start['date']} (all day)"
        else:
            s = datetime.fromisoformat(start["dateTime"]).astimezone(tz)
            e = datetime.fromisoformat(end["dateTime"]).astimezone(tz)
            when = f"{s:%a %Y-%m-%d %H:%M}-{e:%H:%M}"
        rem = ev.get("reminders", {})
        reminders = (
            "calendar default"
            if rem.get("useDefault")
            else ", ".join(f"{o['minutes']} min" for o in rem.get("overrides", [])) or "none"
        )
        out = {"id": ev.get("id"), "title": ev.get("summary", "(no title)"), "when": when, "reminders": reminders}
        if ev.get("location"):
            out["location"] = ev["location"]
        if ev.get("description"):
            out["notes"] = ev["description"][:300]
        props = ev.get("extendedProperties", {}).get("private", {})
        out["created_by_bot"] = props.get(MARK_KEY) == MARK_VALUE
        return out

    def _check_may_change(self, event_id: str) -> dict:
        ev = self._call("GET", f"/events/{requests.utils.quote(event_id, safe='')}")
        mine = ev.get("extendedProperties", {}).get("private", {}).get(MARK_KEY) == MARK_VALUE
        if not mine and not self.allow_changing_others:
            raise CalendarError(
                "This event was not created by the assistant, and changing such events is turned "
                "off (ALLOW_CHANGING_OTHER_EVENTS). Tell the user to change it in Google Calendar "
                "themselves."
            )
        return ev

    # ------------------------------------------------------------------ actions

    def today(self) -> dict:
        tz = self._tz()
        now = datetime.now(tz)
        days = []
        for i in range(15):
            d = now.date() + timedelta(days=i)
            label = "today" if i == 0 else "tomorrow" if i == 1 else ""
            days.append(f"{d:%A} {d.isoformat()}" + (f" ({label})" if label else ""))
        return {
            "now": f"{now:%A %Y-%m-%d %H:%M}",
            "time_zone": str(tz),
            "next_days": days,
            "note": "'This <weekday>' means the first such day in next_days from today on.",
        }

    def list_events(self, start_date: str = "", days: int = 7, search: str = "") -> dict:
        tz = self._tz()
        first = self._parse_when(start_date.strip()[:10], tz)[0] if start_date.strip() else datetime.now(tz).date()
        n = max(1, min(int(days or 7), 60))
        t0 = datetime.combine(first, datetime.min.time(), tz)
        t1 = t0 + timedelta(days=n)
        params = {
            "timeMin": t0.isoformat(),
            "timeMax": t1.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 50,
            "timeZone": str(tz),
        }
        if search.strip():
            params["q"] = search.strip()
        items = self._call("GET", "/events", params=params).get("items", [])
        events = [self._describe(e, tz) for e in items if e.get("status") != "cancelled"]
        return {
            "range": f"{t0:%a %Y-%m-%d} to {(t1 - timedelta(days=1)):%a %Y-%m-%d}",
            "count": len(events),
            "events": events,
        }

    def add_event(
        self,
        title: str,
        start: str,
        end: str = "",
        duration_minutes: int = 0,
        all_day: bool = False,
        remind_minutes_before: str = "",
        location: str = "",
        notes: str = "",
        confirm_past: bool = False,
        allow_overlap: bool = False,
    ) -> dict:
        tz = self._tz()
        s, date_only = self._parse_when(start, tz)
        if all_day and not date_only:
            s, date_only = s.date(), True
        if date_only and not all_day:
            raise CalendarError(
                f"No time was given for '{title}'. Nothing was added. Ask the user what time it is "
                "(or, if it lasts all day, call again with all_day=true). Do not guess the time."
            )
        remind = str(remind_minutes_before or "").strip()
        if date_only and not remind:
            # All-day reminders count back from midnight: 900 min = 09:00 the day before.
            remind = "900"
        body = {
            "summary": title.strip() or "(no title)",
            "reminders": self._reminders(remind),
            "extendedProperties": {"private": {MARK_KEY: MARK_VALUE}},
        }
        if location.strip():
            body["location"] = location.strip()
        if notes.strip():
            body["description"] = notes.strip()
        now = datetime.now(tz)
        if all_day:
            e = self._parse_when(end, tz)[0] if end.strip() else s
            if isinstance(e, datetime):
                e = e.date()
            body["start"] = {"date": s.isoformat()}
            body["end"] = {"date": (e + timedelta(days=1)).isoformat()}  # end is exclusive
            in_past = s < now.date()
        else:
            if end.strip():
                e, end_is_date = self._parse_when(end, tz)
                if end_is_date:
                    raise CalendarError("The end needs a time too, e.g. '2026-11-22 14:00'.")
            else:
                minutes = int(duration_minutes or 0) or self.default_duration
                if not 5 <= minutes <= 24 * 60:
                    raise CalendarError("duration_minutes must be between 5 and 1440.")
                e = s + timedelta(minutes=minutes)
            if e <= s:
                raise CalendarError("The end time must be after the start time.")
            body["start"] = {"dateTime": s.isoformat(), "timeZone": str(tz)}
            body["end"] = {"dateTime": e.isoformat(), "timeZone": str(tz)}
            in_past = s < now
        if in_past and not confirm_past:
            raise CalendarError(
                f"{start} is in the past (now is {now:%a %Y-%m-%d %H:%M}). Nothing was added. "
                "If the user said it already happened (they are logging a past event), call add_event "
                "again with exactly the same arguments plus confirm_past=true; keep the time, do not "
                "switch to all_day. Otherwise the date is probably wrong: work it out again from now."
            )

        # Look at what is already in that slot: the same event (e.g. a repeated tool call) or a clash.
        if date_only:
            t0 = datetime.combine(s, datetime.min.time(), tz)
            t1 = datetime.combine(e + timedelta(days=1), datetime.min.time(), tz)
        else:
            t0, t1 = s, e
        existing = self._call(
            "GET",
            "/events",
            params={"timeMin": t0.isoformat(), "timeMax": t1.isoformat(), "singleEvents": "true", "maxResults": 20},
        ).get("items", [])
        new_start = body["start"].get("date") or s.isoformat()
        clashes = []
        for ev in existing:
            if ev.get("status") == "cancelled":
                continue
            ev_start = ev.get("start", {})
            same_start = ev_start.get("date") == new_start or (
                "dateTime" in ev_start and not date_only and datetime.fromisoformat(ev_start["dateTime"]) == s
            )
            if same_start and ev.get("summary", "").strip().lower() == body["summary"].lower():
                return {
                    "already_exists": self._describe(ev, tz),
                    "note": "This event is already in the calendar. Nothing was added.",
                }
            # All-day entries and events marked "free" do not block a timed event.
            if date_only or "date" in ev_start or ev.get("transparency") == "transparent":
                continue
            clashes.append(self._describe(ev, tz))
        if clashes and not allow_overlap:
            return {
                "not_added": True,
                "clashes_with": clashes,
                "note": "The time overlaps the events above. Nothing was added. Tell the user and "
                "ask whether to add it anyway (then call again with allow_overlap=true) or at another time.",
            }

        ev = self._call("POST", "/events", body=body)
        out = {"added": self._describe(ev, tz), "link": ev.get("htmlLink")}
        if clashes:
            out["overlaps"] = clashes
        return out

    def update_event(
        self,
        event_id: str,
        title: str = "",
        start: str = "",
        end: str = "",
        remind_minutes_before: str = "",
        location: str = "",
        notes: str = "",
    ) -> dict:
        tz = self._tz()
        ev = self._check_may_change(event_id)
        patch = {}
        if title.strip():
            patch["summary"] = title.strip()
        if location.strip():
            patch["location"] = location.strip()
        if notes.strip():
            patch["description"] = notes.strip()
        if str(remind_minutes_before).strip():
            patch["reminders"] = self._reminders(remind_minutes_before)
        if start.strip() or end.strip():
            if "date" in ev.get("start", {}):
                raise CalendarError("Moving all-day events is not supported; change it in Google Calendar.")
            old_s = datetime.fromisoformat(ev["start"]["dateTime"])
            old_e = datetime.fromisoformat(ev["end"]["dateTime"])
            s = self._parse_when(start, tz)[0] if start.strip() else old_s
            e = self._parse_when(end, tz)[0] if end.strip() else s + (old_e - old_s)
            if not isinstance(s, datetime) or not isinstance(e, datetime):
                raise CalendarError("Start and end need a time, e.g. '2026-11-22 13:00'.")
            if e <= s:
                raise CalendarError("The end time must be after the start time.")
            patch["start"] = {"dateTime": s.isoformat(), "timeZone": str(tz)}
            patch["end"] = {"dateTime": e.isoformat(), "timeZone": str(tz)}
        if not patch:
            raise CalendarError("Nothing to change was given.")
        new = self._call("PATCH", f"/events/{requests.utils.quote(event_id, safe='')}", body=patch)
        return {"updated": self._describe(new, tz)}

    def delete_event(self, event_id: str) -> dict:
        tz = self._tz()
        ev = self._check_may_change(event_id)
        self._call("DELETE", f"/events/{requests.utils.quote(event_id, safe='')}")
        return {"deleted": self._describe(ev, tz)}
