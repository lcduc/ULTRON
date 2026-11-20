"""Shared Google sign-in and HTTP for the Calendar, Tasks and Gmail code.

One refresh token (from scripts/google-auth.py) is swapped for a one-hour access token,
and all three APIs share it. Nothing here knows about MCP.
"""

import os
import time
from typing import Optional

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"

NOT_GRANTED = (
    "Gmail/Tasks access is not granted yet: run `python scripts/google-auth.py <client.json>` again"
)


def error_message(r) -> str:
    try:
        return r.json()["error"]["message"]
    except Exception:
        return r.text[:300]


def is_missing_scope(r) -> bool:
    """True when Google refused because the saved token lacks a permission (403)."""
    if r.status_code != 403:
        return False
    text = r.text.lower()
    return "insufficient authentication scopes" in text or "access_token_scope_insufficient" in text


class GoogleSession:
    """Holds the credentials and the cached access token, and makes authorised requests.

    One session is shared by Calendar, Tasks and Gmail, so they reuse one access token.
    `error_cls` is the default exception type for problems; each API passes its own
    (CalendarError, TasksError, GmailError) on its requests. `label` names the service in
    the "not connected" message.
    """

    def __init__(self, error_cls=Exception, label: str = "Google"):
        self.client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        self.client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
        self.refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
        self.error_cls = error_cls
        self.label = label
        self._token: Optional[str] = None
        self._token_expiry = 0.0

    def token(self, error_cls=None) -> str:
        err = error_cls or self.error_cls
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        if not (self.client_id and self.client_secret and self.refresh_token):
            raise err(
                f"{self.label} is not connected: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET or "
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
            raise err(
                f"Google sign-in failed ({detail}). The saved permission has probably expired or "
                "been revoked. Tell the user to run scripts/google-auth.py again."
            )
        data = r.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def request(self, method: str, url: str, params=None, body=None, service: str = "Google", error_cls=None):
        """One API request. Retries once with a fresh token on 401. Returns the response
        for the caller to turn into data; raises error_cls on errors."""
        err = error_cls or self.error_cls
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {self.token(err)}"}
            r = requests.request(method, url, params=params, json=body, headers=headers, timeout=20)
            if r.status_code == 401 and attempt == 0:
                self._token = None
                continue
            break
        if r.status_code >= 400:
            if is_missing_scope(r):
                raise err(NOT_GRANTED)
            raise err(f"{service} error {r.status_code}: {error_message(r)}")
        return r
