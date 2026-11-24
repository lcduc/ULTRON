"""Tonight's spoken briefing, saved to the state volume and served to the phone over the tailnet.

GET /voice/evening.mp3 with "Authorization: Bearer <VOICE_KEY>" returns the clip, but only if it covers
today or tomorrow (the evening clip covers the next day, so it stays valid after midnight). GET /voice/health returns "ok" without auth. Everything else is 404.
"""

import hmac
import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("briefing")

VOICE_DIR = Path(os.environ.get("VOICE_DIR", "/app/state/voice"))
PORT = 8090


def save(day, mp3, script_text, directory=None):
    """Atomically writes evening.mp3 and evening.json (day = the day the briefing covers)."""
    d = Path(directory or VOICE_DIR)
    d.mkdir(parents=True, exist_ok=True)
    meta = {"date": day.isoformat(), "made": int(time.time()), "script": script_text}
    for name, data in (("evening.mp3", mp3), ("evening.json", json.dumps(meta, ensure_ascii=False).encode("utf-8"))):
        tmp = d / (name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, d / name)


def todays_clip(tz, directory=None):
    """Path of the clip if the day it covers is today or tomorrow (in tz), else None."""
    d = Path(directory or VOICE_DIR)
    try:
        covers = date.fromisoformat(json.loads((d / "evening.json").read_text(encoding="utf-8"))["date"])
        today = datetime.now(tz).date()
        if covers not in (today, today + timedelta(days=1)):
            return None
        p = d / "evening.mp3"
        return p if p.is_file() else None
    except Exception:
        return None


def make_handler(key, tz_name_fn, directory=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "voice"
        sys_version = ""

        def log_message(self, *args):  # no access log lines
            pass

        def _reply(self, code, body=b"", ctype="text/plain", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/voice/health":
                return self._reply(200, b"ok")
            if path != "/voice/evening.mp3":
                return self._reply(404, b"not found")
            auth = self.headers.get("Authorization", "")
            if not hmac.compare_digest(auth.encode(), ("Bearer " + key).encode()):
                return self._reply(401, b"unauthorized")
            clip = todays_clip(ZoneInfo(tz_name_fn()), directory)
            if clip is None:
                return self._reply(404, b"not ready")
            self._reply(200, clip.read_bytes(), "audio/mpeg")

        do_HEAD = do_GET

    return Handler


def start(tz_name_fn):
    """Starts the server as a daemon thread; does nothing (with a warning) without VOICE_KEY."""
    key = os.environ.get("VOICE_KEY", "")
    if not key:
        log.warning("VOICE_KEY not set; voice server not started")
        return None
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(key, tz_name_fn))
    threading.Thread(target=srv.serve_forever, daemon=True, name="voice").start()
    log.info("voice server listening on :%d", PORT)
    return srv
