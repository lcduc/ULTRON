import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ULTRON_API_KEY", "k")

import common  # noqa: E402


class FakeWebui:
    """Records API calls; answers like Open WebUI for the paths common.py uses."""

    def __init__(self, chats=None):
        self.calls, self.chats = [], chats or {}

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/api/v1/folders/" and method == "GET":
            return [{"id": "f1", "name": "Papers"}]
        if path == "/api/v1/chats/new":
            return {"id": "c1"}
        if method == "GET" and path.startswith("/api/v1/chats/c"):
            return self.chats[path.rsplit("/", 1)[1]]
        if "/folder/f1/list" in path:
            return self.chats.get("rows", [])
        return None


class CommonTests(unittest.TestCase):
    def setUp(self):
        common._folders.clear()

    def test_create_chat_with_system_prompt(self):
        api = FakeWebui()
        with mock.patch.object(common, "webui_api", api):
            cid = common.create_chat("T", "hello", "body", system="SYS")
        self.assertEqual(cid, "c1")
        post = next(b for m, p, b in api.calls if p == "/api/v1/chats/new")
        self.assertEqual(post["folder_id"], "f1")
        chat = post["chat"]
        self.assertEqual(chat["params"], {"system": "SYS"})
        self.assertEqual([m["role"] for m in chat["messages"]], ["user", "assistant"])
        self.assertEqual(chat["history"]["currentId"], chat["messages"][1]["id"])

    def test_create_chat_without_system_has_no_params(self):
        api = FakeWebui()
        with mock.patch.object(common, "webui_api", api):
            common.create_chat("T", "u", "b")
        post = next(b for m, p, b in api.calls if p == "/api/v1/chats/new")
        self.assertNotIn("params", post["chat"])

    def test_chat_messages_follow_current_branch(self):
        rec = {"chat": {"history": {"currentId": "b", "messages": {
            "a": {"id": "a", "parentId": None, "role": "user", "content": "q"},
            "b": {"id": "b", "parentId": "a", "role": "assistant", "content": "x"}}}}}
        with mock.patch.object(common, "webui_api", FakeWebui({"c9": rec})):
            msgs = common.chat_messages("c9")
        self.assertEqual([(m["id"], m["role"]) for m in msgs], [("a", "user"), ("b", "assistant")])

    def test_list_folder_chats_filters_by_time(self):
        rows = [{"id": "x", "updated_at": 200}, {"id": "y", "updated_at": 50}]
        with mock.patch.object(common, "webui_api", FakeWebui({"rows": rows})):
            self.assertEqual([r["id"] for r in common.list_folder_chats("Papers", 100)], ["x"])

    def test_append_assistant_note(self):
        rec = {"chat": {"history": {"currentId": "a", "messages": {
            "a": {"id": "a", "parentId": None, "role": "user", "content": "q", "childrenIds": []}}}}}
        api = FakeWebui({"c9": rec})
        with mock.patch.object(common, "webui_api", api):
            common.append_assistant_note("c9", "note")
        _, path, body = api.calls[-1]
        self.assertEqual(path, "/api/v1/chats/c9")
        hist = body["chat"]["history"]
        self.assertEqual(hist["messages"][hist["currentId"]]["content"], "note")
        self.assertIn(hist["currentId"], hist["messages"]["a"]["childrenIds"])

    def test_urls(self):
        with mock.patch.dict(os.environ, {"ULTRON_PUBLIC_URL": "https://x.ts.net/"}):
            self.assertEqual(common.chat_url("abc"), "https://x.ts.net/c/abc")
        with mock.patch.dict(os.environ, {"ULTRON_PUBLIC_URL": ""}):
            self.assertEqual(common.chat_url("abc"), "")
        self.assertEqual(common.chat_path("abc"), "/c/abc")


if __name__ == "__main__":
    unittest.main()
