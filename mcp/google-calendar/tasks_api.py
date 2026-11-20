"""Google Tasks logic: lists, add, update, with the same safety rules as the calendar code.

Plain Python, no MCP. Dates are dates only (the Tasks API ignores times); timed reminders
belong in the calendar.
"""

import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import requests

from google_auth import GoogleSession

API = "https://tasks.googleapis.com/tasks/v1"


class TasksError(Exception):
    """A problem the model should read and react to."""


def _norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


class Tasks:
    def __init__(self, session: Optional[GoogleSession] = None):
        self.session = session or GoogleSession(TasksError, "Google Tasks")
        self.timezone = os.environ.get("CALENDAR_TIMEZONE", "")

    # ------------------------------------------------------------------ HTTP and lists

    def _call(self, method: str, path: str, params=None, body=None) -> dict:
        r = self.session.request(method, f"{API}{path}", params=params, body=body, service="Google Tasks", error_cls=TasksError)
        if r.status_code == 204 or not r.content:
            return {}
        return r.json()

    def _items(self, path: str, params: dict) -> list:
        items, token = [], None
        for _ in range(10):
            p = dict(params, maxResults=100)
            if token:
                p["pageToken"] = token
            data = self._call("GET", path, params=p)
            items += data.get("items", [])
            token = data.get("nextPageToken")
            if not token:
                break
        return items

    def _find_list(self, name: str, create: bool) -> Optional[dict]:
        name = (name or "").strip() or "To-do"
        for item in self._items("/users/@me/lists", {}):
            if _norm(item.get("title", "")) == _norm(name):
                return item
        # "To-do" means the account's default list ("My Tasks" in the Google Tasks app),
        # so everyday to-dos land where the phone app shows them first.
        if _norm(name) in {_norm(n) for n in ("To-do", "Todo", "To do", "My Tasks", "Tasks")}:
            return self._call("GET", "/users/@me/lists/@default")
        if not create:
            return None
        return self._call("POST", "/users/@me/lists", body={"title": name})

    @staticmethod
    def _out(t: dict) -> dict:
        due = t.get("due")
        return {
            "id": t["id"],
            "title": t.get("title", ""),
            "notes": t.get("notes", ""),
            "due_date": due[:10] if due else None,
            "done": t.get("status") == "completed",
        }

    def _today(self) -> date:
        if self.timezone:
            return datetime.now(ZoneInfo(self.timezone)).date()
        # Unknown zone: allow one day of slack so "today" is never refused.
        return datetime.now(timezone.utc).date() - timedelta(days=1)

    @staticmethod
    def _parse_date(text: str) -> date:
        try:
            return date.fromisoformat((text or "").strip())
        except ValueError:
            raise TasksError(f"Could not read the due date '{text}'. Use YYYY-MM-DD, e.g. '2026-11-22'.")

    # ------------------------------------------------------------------ operations

    def list_tasks(self, list_name: str = "To-do", include_done: bool = False) -> dict:
        name = (list_name or "").strip() or "To-do"
        lst = self._find_list(name, create=False)
        if not lst:
            return {"list": name, "tasks": [], "note": "No list with that name yet; it is created on the first add."}
        params = {"showCompleted": "true", "showHidden": "true"} if include_done else {"showCompleted": "false"}
        tasks = [self._out(t) for t in self._items(f"/lists/{lst['id']}/tasks", params)]
        if not include_done:
            tasks = [t for t in tasks if not t["done"]]
        return {"list": lst["title"], "tasks": tasks}

    def add_task(self, list_name: str, title: str, notes: str = "", due_date: Optional[str] = None,
                 confirm_past: bool = False) -> dict:
        title = " ".join((title or "").split())
        if not title:
            raise TasksError("A task title is required.")
        due = None
        if due_date:
            due = self._parse_date(due_date)
            if due < self._today() and not confirm_past:
                raise TasksError(
                    f"The due date {due.isoformat()} is in the past. If that is a mistake, call "
                    "calendar_today and use the right date; if the user really means it, call again "
                    "with confirm_past=true."
                )
        lst = self._find_list(list_name, create=True)
        for t in self._items(f"/lists/{lst['id']}/tasks", {"showCompleted": "false"}):
            if t.get("status") != "completed" and _norm(t.get("title", "")) == _norm(title):
                return {"list": lst["title"], "task": self._out(t),
                        "note": "An open task with this title already exists, so nothing was added."}
        body = {"title": title}
        if notes:
            body["notes"] = notes
        if due:
            body["due"] = f"{due.isoformat()}T00:00:00.000Z"
        created = self._call("POST", f"/lists/{lst['id']}/tasks", body=body)
        return {"list": lst["title"], "task": self._out(created), "note": "Added."}

    def update_task(self, task_id: str, list_name: str, done: Optional[bool] = None, title: Optional[str] = None,
                    due_date: Optional[str] = None, delete: bool = False) -> dict:
        lst = self._find_list(list_name, create=False)
        if not lst:
            raise TasksError(f"There is no task list called '{list_name}'. Call tasks_list to see the tasks.")
        if not task_id:
            raise TasksError("A task id is required (from tasks_list).")
        path = f"/lists/{lst['id']}/tasks/{requests.utils.quote(task_id, safe='')}"
        if delete:
            self._call("DELETE", path)
            return {"list": lst["title"], "deleted": task_id}
        patch = {}
        if done is not None:
            patch["status"] = "completed" if done else "needsAction"
            if not done:
                patch["completed"] = None
        if title is not None:
            if not title.strip():
                raise TasksError("The new title is empty.")
            patch["title"] = " ".join(title.split())
        if due_date is not None:
            patch["due"] = f"{self._parse_date(due_date).isoformat()}T00:00:00.000Z" if due_date.strip() else None
        if not patch:
            raise TasksError("Nothing to change: pass done, title, due_date or delete.")
        updated = self._call("PATCH", path, body=patch)
        return {"list": lst["title"], "task": self._out(updated)}
