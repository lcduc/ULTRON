"""Connect Ultron to Google Calendar (one-time, and again if access is revoked).

Usage (on this PC, from the repository root):
    python scripts/google-auth.py path/to/client_secret.json

The JSON is the OAuth client you download from Google Cloud Console (type "Desktop app").
The script opens your browser, you approve calendar, tasks and Gmail access, and it writes
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN into compose/.env.
It never prints those values. Then recreate the chat UI container:
    docker compose up -d open-webui      (in compose/)

Standard library only.
"""

import base64
import hashlib
import http.server
import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

G = "https://www.googleapis.com/auth/"
# Calendar events, Tasks, and Gmail: read, create drafts, and send (send is used only by the
# background briefing job, which can mail only your own address).
SCOPES = [G + "calendar.events", G + "tasks", G + "gmail.readonly", G + "gmail.compose", G + "gmail.send"]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ENV_FILE = Path(__file__).resolve().parent.parent / "compose" / ".env"


def load_client(path: str):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    client = data.get("installed") or data.get("web")
    if not client or "client_id" not in client or "client_secret" not in client:
        sys.exit("That file is not an OAuth client JSON. Download it from Google Cloud Console > "
                 "APIs & Services > Credentials > your Desktop client > Download JSON.")
    if "installed" not in data:
        print("Warning: this is a 'Web application' client. A 'Desktop app' client is expected; "
              "a web client only works if http://127.0.0.1 is listed as a redirect URI.")
    return client["client_id"], client["client_secret"]


def get_code(client_id: str):
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" not in q and "error" not in q:
                self.send_response(404)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in q.items()})
            ok = "code" in q and q.get("state", [""])[0] == state
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Ultron is connected to Google. You can close this tab." if ok else \
                "Something went wrong; check the terminal."
            self.wfile.write(f"<p style='font-family:sans-serif'>{msg}</p>".encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    print("Opening your browser to sign in to Google. If it does not open, visit:\n" + url + "\n")
    webbrowser.open(url)

    deadline = time.time() + 600
    server.timeout = 5
    while "code" not in result and "error" not in result and time.time() < deadline:
        server.handle_request()
    server.server_close()

    if "error" in result:
        sys.exit(f"Google returned an error: {result['error']}")
    if "code" not in result:
        sys.exit("Timed out after 10 minutes waiting for the browser sign-in.")
    if result.get("state") != state:
        sys.exit("State mismatch; aborting.")
    return result["code"], verifier, redirect_uri


def exchange(client_id, client_secret, code, verifier, redirect_uri):
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=30) as r:
            tokens = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Token exchange failed: {e.code} {e.read().decode(errors='replace')[:300]}")
    granted = tokens.get("scope", "").split()
    missing = [x.replace(G, "") for x in SCOPES if x not in granted]
    if missing:
        sys.exit("These permissions were not granted: " + ", ".join(missing) +
                 ". Run again and tick every box on Google's permission screen.")
    if "refresh_token" not in tokens:
        sys.exit("Google did not return a refresh token. Remove 'Ultron' at "
                 "https://myaccount.google.com/permissions and run again.")
    return tokens


def check(access_token):
    req = urllib.request.Request(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events?maxResults=1",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    # Also make one harmless read call per service, so a disabled API shows up now.
    for name, url in (("Google Tasks API", "https://tasks.googleapis.com/tasks/v1/users/@me/lists?maxResults=1"),
                      ("Gmail API", "https://gmail.googleapis.com/gmail/v1/users/me/profile")):
        try:
            urllib.request.urlopen(urllib.request.Request(
                url, headers={"Authorization": f"Bearer {access_token}"}), timeout=30).close()
        except urllib.error.HTTPError as e:
            print(f"Warning: {name} answered {e.code}. Enable it in Google Cloud Console > APIs & Services > Library.")
    return data.get("summary"), data.get("timeZone")


def write_env(values: dict):
    if not ENV_FILE.exists():
        sys.exit(f"{ENV_FILE} not found; run scripts/gen-env.ps1 first.")
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    for key, val in values.items():
        for i, line in enumerate(lines):
            if line.startswith(key + "="):
                lines[i] = f"{key}={val}"
                break
        else:
            lines.append(f"{key}={val}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    client_id, client_secret = load_client(sys.argv[1])
    code, verifier, redirect_uri = get_code(client_id)
    tokens = exchange(client_id, client_secret, code, verifier, redirect_uri)
    calendar, tz = check(tokens["access_token"])
    write_env({
        "GOOGLE_CLIENT_ID": client_id,
        "GOOGLE_CLIENT_SECRET": client_secret,
        "GOOGLE_REFRESH_TOKEN": tokens["refresh_token"],
    })
    print(f"Connected to calendar '{calendar}' (time zone {tz}).")
    print(f"Saved the credentials to {ENV_FILE}.")
    print("Now run, in compose/:  docker compose up -d open-webui")


if __name__ == "__main__":
    main()
