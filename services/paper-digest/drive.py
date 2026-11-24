"""Google Drive for the paper digest (drive.file scope, plain REST over `requests`).

Uses the shared GoogleSession from mcp/google-calendar/google_auth.py (mounted at /mcp in the
container, PYTHONPATH=/mcp). With drive.file the app sees only the files and folders it created,
so the root folder is found by name among those, wherever the user has moved it.

Layout: <drive_root>/<YYYY>/<MM - Month>/<N - Short name>/
"""

import calendar
import json
import logging
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

try:
    from google_auth import GoogleSession, is_missing_scope
except ImportError:  # running on the host: use the repo copy
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mcp" / "google-calendar"))
    from google_auth import GoogleSession, is_missing_scope

import engine

log = logging.getLogger("paper-digest")

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
FOLDER = "application/vnd.google-apps.folder"
GDOC = "application/vnd.google-apps.document"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ENABLED_TTL = 600  # seconds

_sess = None
_enabled_cache = None  # (monotonic time, bool)
_root_cache: dict = {}


class DriveError(Exception):
    pass


class MissingScope(DriveError):
    pass


def _session():
    global _sess
    if _sess is None:
        _sess = GoogleSession(DriveError, "Google Drive")
    return _sess


def _call(method: str, url: str, *, params=None, json_body=None, data=None, headers=None):
    """One authorised request; retries once on 401. Returns the response, raises DriveError."""
    s = _session()
    for attempt in range(2):
        h = {"Authorization": f"Bearer {s.token(DriveError)}", **(headers or {})}
        r = requests.request(method, url, params=params, json=json_body, data=data, headers=h, timeout=60)
        if r.status_code == 401 and attempt == 0:
            s._token = None
            continue
        break
    if r.status_code >= 400:
        if is_missing_scope(r):
            raise MissingScope("Drive permission (drive.file) is not granted")
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text[:200]
        raise DriveError(f"Drive error {r.status_code}: {msg}")
    return r


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _list(q: str, fields: str = "files(id,name,webViewLink)") -> list:
    r = _call("GET", f"{API}/files", params={"q": q, "pageSize": 10, "fields": fields,
                                              "orderBy": "createdTime", "spaces": "drive"})
    return r.json().get("files", [])


def enabled() -> bool:
    """True when Drive is usable. Cheap call, cached for 10 minutes."""
    global _enabled_cache
    now = time.monotonic()
    if _enabled_cache and now - _enabled_cache[0] < ENABLED_TTL:
        return _enabled_cache[1]
    root = engine.cfg().get("drive_root", "Phase 9 — Ongoing")
    ok, cache = False, True
    try:
        r = _call("GET", f"{API}/files", params={
            "q": f"mimeType='{FOLDER}' and name='{_esc(root)}' and trashed=false",
            "pageSize": 1, "fields": "files(id)"})
        ok = r.status_code == 200
    except MissingScope:
        log.warning("Drive is off: the saved Google sign-in has no Drive permission (missing scope drive.file). "
                    "Run `python scripts/google-auth.py <client.json>` once and restart.")
    except DriveError as e:
        log.warning("Drive is off: %s", str(e)[:200])
        cache = "error 5" not in str(e)  # keep retrying after a server error
    except requests.RequestException as e:
        log.warning("Drive is off: network problem (%s)", str(e)[:120])
        cache = False
    if cache:
        _enabled_cache = (now, ok)
    return ok


def short_name(paper: dict, limit: int = 40) -> str:
    """Folder-safe short title: no / \\ : * ? " < > |, at most `limit` characters."""
    t = paper.get("short_title") or paper.get("title") or "Paper"
    t = re.sub(r'[\\/:*?"<>|]', " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .-")
    if len(t) > limit:
        cut = t[:limit]
        if " " in cut[limit // 2:]:
            cut = cut[:cut.rstrip().rfind(" ")]
        t = cut.strip(" .-,;")
    return t or "Paper"


def _find_folder(name: str, parent):
    q = f"mimeType='{FOLDER}' and name='{_esc(name)}' and trashed=false"
    if parent:
        q += f" and '{_esc(parent)}' in parents"
    files = _list(q, "files(id)")
    return files[0]["id"] if files else None


def _ensure_folder(name: str, parent) -> str:
    found = _find_folder(name, parent)
    if found:
        return found
    body = {"name": name, "mimeType": FOLDER}
    if parent:
        body["parents"] = [parent]
    r = _call("POST", f"{API}/files", params={"fields": "id"}, json_body=body)
    return r.json()["id"]


def root_folder() -> str:
    name = engine.cfg().get("drive_root", "Phase 9 — Ongoing")
    if name not in _root_cache:
        # No parent filter: the user may have moved it; drive.file still finds app-created folders.
        _root_cache[name] = _ensure_folder(name, None)
    return _root_cache[name]


def folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


def _as_date(d) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def paper_folder(history, paper: dict, day):
    """(folder_id, url) of the paper's folder; the same paper always gets the same folder."""
    known = history.drive_folder(paper["id"])
    if known:
        return known, folder_url(known)
    d = _as_date(day)
    parent = root_folder()
    parent = _ensure_folder(str(d.year), parent)
    parent = _ensure_folder(f"{d.month:02d} - {calendar.month_name[d.month]}", parent)
    n = history.next_paper_number(d.year, d.month)
    fid = _ensure_folder(f"{n} - {short_name(paper)}", parent)
    url = folder_url(fid)
    history.set_drive_folder(paper["id"], fid, url)
    return fid, url


def _multipart(meta: dict, media: bytes, media_type: str):
    boundary = "pd" + format(int(time.time() * 1000), "x")
    head = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(meta)}\r\n--{boundary}\r\nContent-Type: {media_type}\r\n\r\n").encode()
    return head + media + f"\r\n--{boundary}--".encode(), f"multipart/related; boundary={boundary}"


def _in_folder(name: str, folder_id: str, mime=None):
    q = f"name='{_esc(name)}' and '{_esc(folder_id)}' in parents and trashed=false"
    q += f" and mimeType='{mime}'" if mime else f" and mimeType!='{FOLDER}'"
    files = _list(q)
    return files[0] if files else None


def upload_pdf(folder_id: str, name: str, data: bytes) -> str:
    """Upload a PDF unless a file with that name is already there. Returns the file id."""
    existing = _in_folder(name, folder_id)
    if existing:
        return existing["id"]
    body, ctype = _multipart({"name": name, "parents": [folder_id]}, data, "application/pdf")
    r = _call("POST", f"{UPLOAD}/files", params={"uploadType": "multipart", "fields": "id"},
              data=body, headers={"Content-Type": ctype})
    return r.json()["id"]


def upsert_doc(folder_id: str, title: str, docx_bytes: bytes) -> str:
    """Create (converted to a Google Doc) or update the Doc called `title`; returns its link."""
    existing = _in_folder(title, folder_id, GDOC)
    if existing:
        r = _call("PATCH", f"{UPLOAD}/files/{existing['id']}",
                  params={"uploadType": "media", "fields": "id,webViewLink"},
                  data=docx_bytes, headers={"Content-Type": DOCX})
    else:
        body, ctype = _multipart({"name": title, "parents": [folder_id], "mimeType": GDOC}, docx_bytes, DOCX)
        r = _call("POST", f"{UPLOAD}/files", params={"uploadType": "multipart", "fields": "id,webViewLink"},
                  data=body, headers={"Content-Type": ctype})
    j = r.json()
    return j.get("webViewLink") or f"https://docs.google.com/document/d/{j['id']}/edit"
