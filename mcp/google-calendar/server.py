"""Google Calendar MCP server for Ultron.

Three layers, top to bottom:

  1. Tools      - Python functions marked with @mcp.tool(). The SDK reads each function's
                  name, docstring and typed parameters and publishes them as an MCP tool with
                  a JSON schema. The model sees exactly that: name, description, parameters.
  2. Transport  - Streamable HTTP: the client POSTs JSON-RPC messages ("tools/list",
                  "tools/call", ...) to http://calendar-mcp:8000/mcp and gets JSON back.
  3. Auth       - A small check in front of /mcp that wants "Authorization: Bearer <MCP_API_KEY>".

The calendar work itself lives in calendar_api.py and knows nothing about MCP.
"""

import hmac
import os
from typing import Annotated, Callable

import requests
import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from calendar_api import Calendar, CalendarError

cal = Calendar()

# The server object. `instructions` is sent to the client when it connects; clients may
# show it to the model as general guidance for this server.
mcp = MCPServer(
    name="google-calendar",
    version="1.0.0",
    instructions=(
        "Read and change the user's Google Calendar. Before using a day named in words "
        "(today, tomorrow, this Sunday), call calendar_today to get the exact date."
    ),
)


def run(fn: Callable, **kwargs) -> dict:
    """Call a Calendar method and turn expected failures into MCP tool errors.

    A ToolError reaches the model as a normal tool result flagged is_error, with our
    message, so it can tell the user or fix its arguments. Any other exception would
    show up only as "Error executing tool".
    """
    try:
        return fn(**kwargs)
    except CalendarError as e:
        raise ToolError(str(e)) from e
    except requests.RequestException as e:
        raise ToolError(f"Could not reach Google: {e}") from e


# ---------------------------------------------------------------------- 1. tools
#
# The docstring becomes the tool description and each Field(description=...) becomes the
# parameter's description in the JSON schema. That text is all the model has to go on,
# so the usage rules live here.

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)


@mcp.tool(annotations=READ_ONLY)
def calendar_today() -> dict:
    """Get the current date and time in the user's time zone, plus the dates of the next 14 days with weekday names.
    Call this first whenever the user names a day in words, such as "today", "tomorrow", "this Sunday" or "next Friday", to turn it into an exact date."""
    return run(cal.today)


@mcp.tool(annotations=READ_ONLY)
def list_events(
    start_date: Annotated[str, Field(description="First day to list, YYYY-MM-DD. Empty means today.")] = "",
    days: Annotated[int, Field(description="Number of days to list, 1 to 60.", ge=1, le=60)] = 7,
    search: Annotated[str, Field(description="Optional text to look for in event titles and notes.")] = "",
) -> dict:
    """List events in the user's Google Calendar, to answer questions like "what do I have this week" or to find an event's id before changing it."""
    return run(cal.list_events, start_date=start_date, days=days, search=search)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=False, open_world_hint=True))
def add_event(
    title: Annotated[str, Field(description='Short event title, e.g. "Haircut".')],
    start: Annotated[str, Field(description='Start as "YYYY-MM-DD HH:MM" in 24-hour local time, e.g. "2026-11-22 13:00" for 1pm. With all_day=true, just "YYYY-MM-DD".')],
    end: Annotated[str, Field(description="End, same format, only if the user said when it ends. Otherwise leave empty and use duration_minutes.")] = "",
    duration_minutes: Annotated[int, Field(description="Expected length in minutes when the user gave no end time (see rule 3).")] = 0,
    all_day: Annotated[bool, Field(description="True only for all-day events such as birthdays, holidays or trips.")] = False,
    remind_minutes_before: Annotated[str, Field(description='Minutes before the event to notify the phone, comma separated, e.g. "30" or "60,1440" (1440 = one day). Empty means the default (30).')] = "",
    location: Annotated[str, Field(description="Optional place.")] = "",
    notes: Annotated[str, Field(description="Details the user actually gave that do not fit in the title, time or location, such as a booking number or what to bring. Usually empty. Never write your own guesses, interpretations or remarks about the request here.")] = "",
    confirm_past: Annotated[bool, Field(description='Set true when the event is in the past on purpose: the user says it already happened ("I had...", "yesterday", "forgot to log") or confirmed the past date.')] = False,
    allow_overlap: Annotated[bool, Field(description="Set true only after the user agreed to add it despite a clash.")] = False,
) -> dict:
    """Add an event to the user's Google Calendar with phone reminders. Use it when the user mentions an appointment or plan, or asks to be reminded of something.
    Rules, in this order:
    1. Day. If the user names the day in words ("this Sunday", "tomorrow", "next Friday"), call calendar_today first to get the exact date. If the user gave no day at all, ask which day. Never assume today and never guess.
    2. Time. If the user gave no time, ask what time before calling this tool. Exception: things that last all day (birthday, holiday, trip, deadline) need no time; set all_day=true. Vague times ("morning", "after work", "around lunch"): ask for the exact time. A time without am/pm: pick the hour that fits the activity (a haircut "at 1" is 13:00); ask only if both are realistic.
    3. End. Never ask for the end time. If the user gave none, set duration_minutes to a typical length for that kind of event, for example: haircut 45, coffee 60, lunch or dinner 90, doctor or dentist 60, gym 90, movie 150, meeting 60, call 30.
    4. Reminder. If the user does not say when to be reminded, leave remind_minutes_before empty (default: 30 minutes before; for all-day events 9:00 the day before). For events that need travel or preparation, also remind a day before, e.g. a flight: "180,1440".
    5. Title. Short and clear, in the user's language, e.g. "Haircut".
    If the result says the time clashes with another event, tell the user which one and ask whether to add it anyway; only then call again with allow_overlap=true. If the result says the event already exists, do not add it again.
    After adding, confirm in one short sentence: what, weekday, date, time, and when the reminder comes."""
    return run(
        cal.add_event, title=title, start=start, end=end, duration_minutes=duration_minutes, all_day=all_day,
        remind_minutes_before=remind_minutes_before, location=location, notes=notes,
        confirm_past=confirm_past, allow_overlap=allow_overlap,
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=False, open_world_hint=True))
def update_event(
    event_id: Annotated[str, Field(description="The id from list_events.")],
    title: Annotated[str, Field(description="New title, or empty to keep.")] = "",
    start: Annotated[str, Field(description='New start "YYYY-MM-DD HH:MM", or empty to keep. If only start is given, the event keeps its length.')] = "",
    end: Annotated[str, Field(description='New end "YYYY-MM-DD HH:MM", or empty.')] = "",
    remind_minutes_before: Annotated[str, Field(description="New reminders in minutes before, comma separated, or empty to keep.")] = "",
    location: Annotated[str, Field(description="New place, or empty to keep.")] = "",
    notes: Annotated[str, Field(description="New details the user actually gave, or empty to keep. Never your own guesses or remarks.")] = "",
) -> dict:
    """Change an existing event: move it, rename it, or change its reminders. Get the event_id from list_events first. Only fields you pass are changed."""
    return run(
        cal.update_event, event_id=event_id, title=title, start=start, end=end,
        remind_minutes_before=remind_minutes_before, location=location, notes=notes,
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True, open_world_hint=True))
def delete_event(event_id: Annotated[str, Field(description="The id from list_events.")]) -> dict:
    """Delete an event from the user's Google Calendar. Only do this when the user clearly asks to cancel or remove it. Get the event_id from list_events first."""
    return run(cal.delete_event, event_id=event_id)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Plain HTTP check for Docker's healthcheck. Not an MCP endpoint and needs no key."""
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------- 3. auth

class RequireApiKey:
    """ASGI middleware: every request except /health must carry the shared key."""

    def __init__(self, app, key: str):
        self.app, self.expected = app, f"Bearer {key}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] != "/health":
            got = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(got, self.expected):
                await JSONResponse({"error": "missing or wrong API key"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------- 2. transport

def main():
    key = os.environ.get("MCP_API_KEY", "")
    if len(key) < 16:
        raise SystemExit("Set MCP_API_KEY (16+ characters) before starting the server.")

    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        # Stateless + JSON: each POST is answered on its own with a plain JSON body. No
        # session to lose when the container restarts, and easy to read with curl.
        stateless_http=True,
        json_response=True,
        # Only accept requests addressed to the names this server is known by. This blocks
        # DNS-rebinding tricks from a web page in a browser on this PC.
        transport_security=TransportSecuritySettings(
            allowed_hosts=["calendar-mcp:8000", "127.0.0.1:*", "localhost:*"],
            allowed_origins=[],
        ),
    )
    uvicorn.run(RequireApiKey(app, key), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
