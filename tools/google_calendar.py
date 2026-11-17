"""
title: Google Calendar
description: Read and add events in your Google Calendar, with phone reminders.
version: 1.0.0
license: MIT
"""

# Open WebUI tool. Paste this file into Workspace -> Tools -> "+" (tool id: google_calendar).
#
# Credentials are read from the Open WebUI container's environment, never from valves,
# so they do not appear in the admin UI or the chat database:
#   GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN
# They are set in compose/.env by scripts/google-auth.py.
#
# Reminders are Google Calendar's own notifications: popups on every device signed in to
# the Google Calendar app, and optionally e-mail.

import asyncio
import json
import os
import time
from datetime import date, datetime, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import requests
from pydantic import BaseModel, Field

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
# Private extended property marking events this tool created.
MARK_KEY = "createdBy"
MARK_VALUE = "ultron"


class ToolError(Exception):
    pass


class Tools:
    class Valves(BaseModel):
        CALENDAR_ID: str = Field(
            default="primary",
            description="Calendar to use. 'primary' is your main calendar.",
        )
        TIMEZONE: str = Field(
            default="",
            description="IANA time zone, e.g. Asia/Ho_Chi_Minh. Empty = use the calendar's own time zone.",
        )
        DEFAULT_DURATION_MINUTES: int = Field(
            default=60, description="Event length when the user gives no end time."
        )
        DEFAULT_REMINDER_MINUTES: str = Field(
            default="30",
            description="Phone reminder(s) when the user gives none, minutes before, comma separated.",
        )
        ALLOW_CHANGING_OTHER_EVENTS: bool = Field(
            default=False,
            description="Allow moving or deleting events the bot did not create.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self._token: Optional[str] = None
        self._token_expiry = 0.0
        self._tz_name: Optional[str] = None

    # ------------------------------------------------------------------ helpers

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        creds = {
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            "refresh_token": os.environ.get("GOOGLE_REFRESH_TOKEN", ""),
        }
        if not all(creds.values()):
            raise ToolError(
                "Google Calendar is not connected: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET or "
                "GOOGLE_REFRESH_TOKEN is missing in the Open WebUI container. Tell the user to run "
                "scripts/google-auth.py and restart Open WebUI."
            )
        r = requests.post(TOKEN_URL, data={**creds, "grant_type": "refresh_token"}, timeout=20)
        if r.status_code != 200:
            detail = r.json().get("error", r.text[:200]) if r.content else r.status_code
            raise ToolError(
                f"Google sign-in failed ({detail}). The saved permission has probably expired or "
                "been revoked. Tell the user to run scripts/google-auth.py again."
            )
        data = r.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _call(self, method: str, path: str, params=None, body=None) -> dict:
        url = f"{API}/calendars/{requests.utils.quote(self.valves.CALENDAR_ID, safe='')}{path}"
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
            raise ToolError(f"Google Calendar error {r.status_code}: {msg}")
        return r.json()

    def _tz(self) -> ZoneInfo:
        if self.valves.TIMEZONE:
            return ZoneInfo(self.valves.TIMEZONE)
        if not self._tz_name:
            # events.list returns the calendar's time zone and only needs the events scope.
            data = self._call("GET", "/events", params={"maxResults": 1})
            self._tz_name = data.get("timeZone") or "UTC"
        return ZoneInfo(self._tz_name)

    def _parse_when(self, text: str, tz: ZoneInfo):
        """Return (datetime, is_date_only)."""
        text = (text or "").strip().replace("/", "-")
        if not text:
            raise ToolError("A start date/time is required, e.g. '2026-11-22 13:00'.")
        if len(text) == 10:
            try:
                return date.fromisoformat(text), True
            except ValueError:
                pass
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise ToolError(
                f"Could not read the date/time '{text}'. Use the format YYYY-MM-DD HH:MM, "
                "e.g. '2026-11-22 13:00'. Call calendar_today to get exact dates."
            )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt, False

    def _reminders(self, text: str) -> dict:
        text = str(text if text not in (None, "") else self.valves.DEFAULT_REMINDER_MINUTES)
        minutes = []
        for part in text.replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                m = int(float(part))
            except ValueError:
                raise ToolError(f"Reminder '{part}' is not a number of minutes.")
            if not 0 <= m <= 40320:
                raise ToolError("Reminders must be between 0 and 40320 minutes (4 weeks) before.")
            minutes.append(m)
        minutes = sorted(set(minutes))[:5]
        return {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": m} for m in minutes],
        }

    def _describe(self, ev: dict, tz: ZoneInfo) -> dict:
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
        out = {
            "id": ev.get("id"),
            "title": ev.get("summary", "(no title)"),
            "when": when,
            "reminders": reminders,
        }
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
        if not mine and not self.valves.ALLOW_CHANGING_OTHER_EVENTS:
            raise ToolError(
                "This event was not created by the assistant, and changing such events is turned "
                "off (valve ALLOW_CHANGING_OTHER_EVENTS). Tell the user to change it in Google "
                "Calendar themselves."
            )
        return ev

    async def _run(self, fn, emitter, status: str):
        if emitter:
            await emitter({"type": "status", "data": {"description": status, "done": False}})
        try:
            result = await asyncio.to_thread(fn)
            text = json.dumps(result, ensure_ascii=False)
            done = status
        except ToolError as e:
            text = json.dumps({"error": str(e)}, ensure_ascii=False)
            done = "Calendar: " + str(e)[:80]
        except requests.RequestException as e:
            text = json.dumps({"error": f"Could not reach Google: {e}"}, ensure_ascii=False)
            done = "Calendar: Google not reachable"
        if emitter:
            await emitter({"type": "status", "data": {"description": done, "done": True}})
        return text

    # ------------------------------------------------------------------ tools

    async def calendar_today(self, __event_emitter__: Callable = None) -> str:
        """
        Get the current date and time in the user's time zone, plus the dates of the next 14 days with weekday names.
        Call this first whenever the user names a day in words, such as "today", "tomorrow", "this Sunday" or "next Friday", to turn it into an exact date.
        """

        def work():
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

        return await self._run(work, __event_emitter__, "Checking the date")

    async def list_events(
        self,
        start_date: str = "",
        days: int = 7,
        search: str = "",
        __event_emitter__: Callable = None,
    ) -> str:
        """
        List events in the user's Google Calendar, to answer questions like "what do I have this week" or to find an event's id before changing it.
        :param start_date: First day to list, YYYY-MM-DD. Empty means today.
        :param days: Number of days to list, 1 to 60. Default 7.
        :param search: Optional text to look for in event titles and notes.
        """

        def work():
            tz = self._tz()
            if start_date.strip():
                first, _ = self._parse_when(start_date.strip()[:10], tz)
            else:
                first = datetime.now(tz).date()
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

        return await self._run(work, __event_emitter__, "Reading your calendar")

    async def add_event(
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
        __event_emitter__: Callable = None,
    ) -> str:
        """
        Add an event to the user's Google Calendar with phone reminders. Use it when the user mentions an appointment or plan, or asks to be reminded of something.
        Rules, in this order:
        1. Day. If the user names the day in words ("this Sunday", "tomorrow", "next Friday"), call calendar_today first to get the exact date. If the user gave no day at all, ask which day. Never assume today and never guess.
        2. Time. If the user gave no time, ask what time before calling this tool. Exception: things that last all day (birthday, holiday, trip, deadline) need no time; set all_day=true. Vague times ("morning", "after work", "around lunch"): ask for the exact time. A time without am/pm: pick the hour that fits the activity (a haircut "at 1" is 13:00); ask only if both are realistic.
        3. End. Never ask for the end time. If the user gave none, set duration_minutes to a typical length for that kind of event, for example: haircut 45, coffee 60, lunch or dinner 90, doctor or dentist 60, gym 90, movie 150, meeting 60, call 30.
        4. Reminder. If the user does not say when to be reminded, leave remind_minutes_before empty (default: 30 minutes before; for all-day events 9:00 the day before). For events that need travel or preparation, also remind a day before, e.g. a flight: "180,1440".
        5. Title. Short and clear, in the user's language, e.g. "Haircut".
        If the result says the time clashes with another event, tell the user which one and ask whether to add it anyway; only then call again with allow_overlap=true. If the result says the event already exists, do not add it again.
        After adding, confirm in one short sentence: what, weekday, date, time, and when the reminder comes.
        :param title: Short event title, e.g. "Haircut".
        :param start: Start as "YYYY-MM-DD HH:MM" in 24-hour local time, e.g. "2026-11-22 13:00" for 1pm. With all_day=true, just "YYYY-MM-DD".
        :param end: End, same format, only if the user said when it ends. Otherwise leave empty and use duration_minutes.
        :param duration_minutes: Expected length in minutes when the user gave no end time (see rule 3).
        :param all_day: True only for all-day events such as birthdays, holidays or trips.
        :param remind_minutes_before: Minutes before the event to notify the phone, comma separated, e.g. "30" or "60,1440" (1440 = one day). Empty means the default (30).
        :param location: Optional place.
        :param notes: Optional details.
        :param confirm_past: Set true only if the user confirmed they really want an event in the past.
        :param allow_overlap: Set true only after the user agreed to add it despite a clash.
        """

        def work():
            tz = self._tz()
            s, date_only = self._parse_when(start, tz)
            if all_day and not date_only:
                s, date_only = s.date(), True
            if date_only and not all_day:
                raise ToolError(
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
                        raise ToolError("The end needs a time too, e.g. '2026-11-22 14:00'.")
                else:
                    minutes = int(duration_minutes or 0) or self.valves.DEFAULT_DURATION_MINUTES
                    if not 5 <= minutes <= 24 * 60:
                        raise ToolError("duration_minutes must be between 5 and 1440.")
                    e = s + timedelta(minutes=minutes)
                if e <= s:
                    raise ToolError("The end time must be after the start time.")
                body["start"] = {"dateTime": s.isoformat(), "timeZone": str(tz)}
                body["end"] = {"dateTime": e.isoformat(), "timeZone": str(tz)}
                in_past = s < now
            if in_past and not confirm_past:
                raise ToolError(
                    f"{start} is in the past (now is {now:%a %Y-%m-%d %H:%M}). Nothing was added. "
                    "Check the date with calendar_today, or ask the user to confirm."
                )

            # Look at what is already in that slot: same event (e.g. a repeated tool call) or a clash.
            if date_only:
                t0 = datetime.combine(s, datetime.min.time(), tz)
                t1 = datetime.combine(e + timedelta(days=1), datetime.min.time(), tz)
            else:
                t0, t1 = s, e
            existing = self._call(
                "GET",
                "/events",
                params={"timeMin": t0.isoformat(), "timeMax": t1.isoformat(),
                        "singleEvents": "true", "maxResults": 20},
            ).get("items", [])
            new_start = body["start"].get("date") or s.isoformat()
            clashes = []
            for ev in existing:
                if ev.get("status") == "cancelled":
                    continue
                ev_start = ev.get("start", {})
                same_start = ev_start.get("date") == new_start or (
                    "dateTime" in ev_start and not date_only
                    and datetime.fromisoformat(ev_start["dateTime"]) == s
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
                            "ask whether to add it anyway (then call again with allow_overlap=true) "
                            "or at another time.",
                }

            ev = self._call("POST", "/events", body=body)
            out = {"added": self._describe(ev, tz), "link": ev.get("htmlLink")}
            if clashes:
                out["overlaps"] = clashes
            return out

        return await self._run(work, __event_emitter__, f"Adding '{title}' to your calendar")

    async def update_event(
        self,
        event_id: str,
        title: str = "",
        start: str = "",
        end: str = "",
        remind_minutes_before: str = "",
        location: str = "",
        notes: str = "",
        __event_emitter__: Callable = None,
    ) -> str:
        """
        Change an existing event: move it, rename it, or change its reminders. Get the event_id from list_events first. Only fields you pass are changed.
        :param event_id: The id from list_events.
        :param title: New title, or empty to keep.
        :param start: New start "YYYY-MM-DD HH:MM", or empty to keep. If only start is given, the event keeps its length.
        :param end: New end "YYYY-MM-DD HH:MM", or empty.
        :param remind_minutes_before: New reminders in minutes before, comma separated, or empty to keep.
        :param location: New place, or empty to keep.
        :param notes: New details, or empty to keep.
        """

        def work():
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
                    raise ToolError("Moving all-day events is not supported; change it in Google Calendar.")
                old_s = datetime.fromisoformat(ev["start"]["dateTime"])
                old_e = datetime.fromisoformat(ev["end"]["dateTime"])
                s = self._parse_when(start, tz)[0] if start.strip() else old_s
                e = self._parse_when(end, tz)[0] if end.strip() else s + (old_e - old_s)
                if not isinstance(s, datetime) or not isinstance(e, datetime):
                    raise ToolError("Start and end need a time, e.g. '2026-11-22 13:00'.")
                if e <= s:
                    raise ToolError("The end time must be after the start time.")
                patch["start"] = {"dateTime": s.isoformat(), "timeZone": str(tz)}
                patch["end"] = {"dateTime": e.isoformat(), "timeZone": str(tz)}
            if not patch:
                raise ToolError("Nothing to change was given.")
            new = self._call("PATCH", f"/events/{requests.utils.quote(event_id, safe='')}", body=patch)
            return {"updated": self._describe(new, tz)}

        return await self._run(work, __event_emitter__, "Updating the event")

    async def delete_event(self, event_id: str, __event_emitter__: Callable = None) -> str:
        """
        Delete an event from the user's Google Calendar. Only do this when the user clearly asks to cancel or remove it. Get the event_id from list_events first.
        :param event_id: The id from list_events.
        """

        def work():
            tz = self._tz()
            ev = self._check_may_change(event_id)
            self._call("DELETE", f"/events/{requests.utils.quote(event_id, safe='')}")
            return {"deleted": self._describe(ev, tz)}

        return await self._run(work, __event_emitter__, "Removing the event")
