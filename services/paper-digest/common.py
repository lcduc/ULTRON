"""Open WebUI and ntfy helpers (adapted from services/assistant-cron/briefing.py).

Every function here talks to the network and raises on failure; callers decide what a failure means.
Per-chat system prompt: Open WebUI keeps it in `chat["params"]["system"]` (verified against v0.13.3).
"""

import logging
import os
import time
import uuid

import requests

log = logging.getLogger("paper-digest")

PAGE = 10  # Open WebUI lists chats 10 per page
_folders: dict[str, str] = {}  # folder name -> id (in-memory cache)


def webui_api(method, path, body=None):
    base = os.environ.get("OPENWEBUI_URL", "http://open-webui:8080").rstrip("/")
    r = requests.request(
        method, base + path, json=body, timeout=30,
        headers={"Authorization": f"Bearer {os.environ['ULTRON_API_KEY']}"},
    )
    r.raise_for_status()
    return r.json() if r.content else None


def is_404(e) -> bool:
    return getattr(getattr(e, "response", None), "status_code", None) == 404


def folder_id(name):
    """Id of the Open WebUI folder `name` (created if missing), or None for no folder / on failure."""
    name = str(name or "").strip()
    if not name:
        return None
    if _folders.get(name):
        return _folders[name]
    try:
        found = next((f for f in webui_api("GET", "/api/v1/folders/") or [] if f.get("name") == name), None)
        if not found:
            found = webui_api("POST", "/api/v1/folders/", {"name": name})
        _folders[name] = found["id"]
        return found["id"]
    except Exception as e:
        log.warning("chat folder %r unavailable (%s); no folder used", name, str(e)[:120])
        return None


def post_chat(form, folder):
    """POSTs the chat into the folder. A deleted folder (404) is looked up again once; other folder
    trouble falls back to a chat without a folder."""
    for _ in range(2):
        fid = folder_id(folder)
        if not fid:
            break
        try:
            return webui_api("POST", "/api/v1/chats/new", {**form, "folder_id": fid})["id"]
        except Exception as e:
            _folders.pop(str(folder).strip(), None)
            if not is_404(e):
                log.warning("chat not saved in the folder (%s); saving without", str(e)[:120])
                break
    return webui_api("POST", "/api/v1/chats/new", form)["id"]


def create_chat(title, user_line, text, system=None, folder="Papers", model="ultron"):
    """Saves a chat: a user line, then `text` as Ultron's answer. `system` becomes the chat-level
    system prompt (chat.params.system). Returns the chat id."""
    uid, aid, now = str(uuid.uuid4()), str(uuid.uuid4()), int(time.time())
    user = {"id": uid, "parentId": None, "childrenIds": [aid], "role": "user",
            "content": user_line, "timestamp": now, "models": [model]}
    bot = {"id": aid, "parentId": uid, "childrenIds": [], "role": "assistant", "content": text,
           "model": model, "modelName": model, "modelIdx": 0, "timestamp": now, "done": True}
    chat = {"title": title, "models": [model], "messages": [user, bot],
            "history": {"messages": {uid: user, aid: bot}, "currentId": aid}, "timestamp": now * 1000}
    if system:
        chat["params"] = {"system": system}
    return post_chat({"chat": chat}, folder)


def get_chat(chat_id) -> dict:
    """The whole chat record (`["chat"]` holds title, params, history)."""
    return webui_api("GET", f"/api/v1/chats/{chat_id}")


def chat_messages(chat_id) -> list[dict]:
    """Messages of the current branch, oldest first: [{id, role, content}]."""
    hist = (get_chat(chat_id).get("chat") or {}).get("history") or {}
    msgs, cur, out = hist.get("messages") or {}, hist.get("currentId"), []
    while cur and cur in msgs and len(out) <= len(msgs):
        m = msgs[cur]
        out.append({"id": m.get("id", cur), "role": m.get("role"), "content": m.get("content") or ""})
        cur = m.get("parentId")
    return out[::-1]


def list_folder_chats(folder="Papers", updated_since=0) -> list[dict]:
    """Chats in the folder updated after `updated_since` (epoch seconds): [{id, title, updated_at}]."""
    fid = folder_id(folder)
    if not fid:
        return []
    out, page = [], 1
    while page <= 20:
        rows = webui_api("GET", f"/api/v1/chats/folder/{fid}/list?page={page}") or []
        out += [r for r in rows if r.get("updated_at", 0) > updated_since]
        if len(rows) < PAGE or min((r.get("updated_at", 0) for r in rows), default=0) <= updated_since:
            break  # newest first: the rest is older
        page += 1
    return out


def append_assistant_note(chat_id, text):
    """Adds an assistant message at the end of the chat's current branch (read, modify, write back)."""
    rec = get_chat(chat_id)
    chat = rec["chat"]
    hist = chat.setdefault("history", {"messages": {}, "currentId": None})
    msgs, parent = hist.setdefault("messages", {}), hist.get("currentId")
    aid, now = str(uuid.uuid4()), int(time.time())
    note = {"id": aid, "parentId": parent, "childrenIds": [], "role": "assistant", "content": text,
            "model": "ultron", "modelName": "ultron", "modelIdx": 0, "timestamp": now, "done": True}
    if parent and parent in msgs:
        msgs[parent].setdefault("childrenIds", []).append(aid)
    msgs[aid] = note
    hist["currentId"] = aid
    if isinstance(chat.get("messages"), list):
        chat["messages"].append(note)
    webui_api("POST", f"/api/v1/chats/{chat_id}", {"chat": chat})


def delete_chat(chat_id):
    webui_api("DELETE", f"/api/v1/chats/{chat_id}")


def chat_path(chat_id="") -> str:
    """Relative link for use inside a chat message."""
    return f"/c/{chat_id}"


def chat_url(chat_id="", model="ultron") -> str:
    """Absolute link for a push; "" when ULTRON_PUBLIC_URL is not set."""
    base = os.environ.get("ULTRON_PUBLIC_URL", "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/c/{chat_id}" if chat_id else f"{base}/?models={model}"


def push(title, body, click=""):
    url = os.environ.get("NTFY_URL", "http://ntfy:80").rstrip("/")
    payload = {"topic": os.environ["NTFY_TOPIC"], "title": title, "message": body}
    if click:
        payload["click"] = click
    r = requests.post(url, json=payload, headers={"Authorization": f"Bearer {os.environ['NTFY_TOKEN']}"}, timeout=20)
    r.raise_for_status()
