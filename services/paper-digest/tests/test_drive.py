import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import drive  # noqa: E402


class Resp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code, self._body, self.text = status, body if body is not None else {}, text
        self.content = b"x"

    def json(self):
        return self._body


class FakeSession:
    def token(self, err=None):
        return "tok"


class FakeHistory:
    def __init__(self, folder=None):
        self.folder, self.set_calls = folder, []

    def drive_folder(self, pid):
        return self.folder

    def next_paper_number(self, y, m):
        return 3

    def set_drive_folder(self, pid, fid, url):
        self.set_calls.append((pid, fid, url))


class DriveTests(unittest.TestCase):
    def setUp(self):
        drive._enabled_cache = None
        drive._root_cache.clear()
        p = mock.patch.object(drive, "_session", return_value=FakeSession())
        p.start()
        self.addCleanup(p.stop)
        c = mock.patch.object(drive.engine, "cfg", return_value={"drive_root": "Phase 9 — Ongoing"})
        c.start()
        self.addCleanup(c.stop)

    def test_short_name(self):
        n = drive.short_name({"title": 'Pi0: A Vision/Language "Action" Flow Model? for General Robot Control|x'})
        self.assertLessEqual(len(n), 40)
        self.assertFalse(set(n) & set('/\:*?"<>|'))
        self.assertEqual(drive.short_name({"title": "???"}), "Paper")

    def test_escape(self):
        bs = chr(92)
        self.assertEqual(drive._esc("it's a" + bs + "b"), "it" + bs + "'s a" + bs + bs + "b")

    def test_enabled_missing_scope_false_and_cached(self):
        r = Resp(403, text='{"error":{"message":"Request had insufficient authentication scopes."}}')
        with mock.patch.object(drive.requests, "request", return_value=r) as rq, \
                self.assertLogs("paper-digest", "WARNING") as logs:
            self.assertFalse(drive.enabled())
            self.assertFalse(drive.enabled())
        self.assertEqual(rq.call_count, 1)
        self.assertIn("missing scope", logs.output[0])

    def test_enabled_missing_credentials(self):
        with mock.patch.object(drive, "_session") as s, self.assertLogs("paper-digest", "WARNING"):
            s.return_value.token.side_effect = drive.DriveError("not connected")
            self.assertFalse(drive.enabled())

    def test_enabled_ok(self):
        with mock.patch.object(drive.requests, "request", return_value=Resp(200, {"files": []})):
            self.assertTrue(drive.enabled())

    def test_401_retries_with_new_token(self):
        s = FakeSession()
        s._token = "old"
        with mock.patch.object(drive, "_session", return_value=s), \
                mock.patch.object(drive.requests, "request", side_effect=[Resp(401), Resp(200, {"files": []})]) as rq:
            drive._call("GET", "u")
        self.assertEqual(rq.call_count, 2)

    def test_paper_folder_creates_path_and_stores(self):
        calls = []

        def fake(method, url, params=None, json=None, data=None, headers=None, timeout=None):
            calls.append((method, params, json))
            if method == "GET":
                return Resp(200, {"files": []})
            return Resp(200, {"id": "id_" + json["name"]})

        h = FakeHistory()
        with mock.patch.object(drive.requests, "request", side_effect=fake):
            fid, url = drive.paper_folder(h, {"id": "arxiv:1", "title": "Big Paper"}, "2026-11-24")
        created = [c[2]["name"] for c in calls if c[0] == "POST"]
        self.assertEqual(created, ["Phase 9 — Ongoing", "2026", "11 - November", "3 - Big Paper"])
        self.assertEqual(fid, "id_3 - Big Paper")
        self.assertEqual(h.set_calls, [("arxiv:1", fid, url)])
        # root is looked up without a parent filter, children by parent
        gets = [c[1]["q"] for c in calls if c[0] == "GET"]
        self.assertNotIn("in parents", gets[0])
        self.assertIn("'id_Phase 9 — Ongoing' in parents", gets[1])

    def test_paper_folder_known(self):
        with mock.patch.object(drive.requests, "request") as rq:
            fid, url = drive.paper_folder(FakeHistory("abc"), {"id": "x"}, "2026-11-24")
        self.assertEqual((fid, url), ("abc", drive.folder_url("abc")))
        rq.assert_not_called()

    def test_upload_pdf_skips_existing(self):
        with mock.patch.object(drive.requests, "request", return_value=Resp(200, {"files": [{"id": "old"}]})) as rq:
            self.assertEqual(drive.upload_pdf("f", "a.pdf", b"%PDF"), "old")
        self.assertEqual(rq.call_count, 1)

    def test_upload_pdf_new_is_multipart(self):
        seen = []

        def fake(method, url, params=None, json=None, data=None, headers=None, timeout=None):
            seen.append((method, url, params, data, headers))
            return Resp(200, {"files": []}) if method == "GET" else Resp(200, {"id": "new"})

        with mock.patch.object(drive.requests, "request", side_effect=fake):
            self.assertEqual(drive.upload_pdf("f", "a.pdf", b"%PDF-1"), "new")
        m, url, params, data, headers = seen[1]
        self.assertEqual(params["uploadType"], "multipart")
        self.assertTrue(headers["Content-Type"].startswith("multipart/related; boundary="))
        self.assertIn(b'"parents": ["f"]', data)
        self.assertIn(b"%PDF-1", data)

    def test_upsert_doc_create_converts(self):
        seen = []

        def fake(method, url, params=None, json=None, data=None, headers=None, timeout=None):
            seen.append((method, url, data))
            if method == "GET":
                return Resp(200, {"files": []})
            return Resp(200, {"id": "d1", "webViewLink": "https://docs.google.com/document/d/d1/edit"})

        with mock.patch.object(drive.requests, "request", side_effect=fake):
            link = drive.upsert_doc("f", "T", b"DOCX")
        self.assertEqual(link, "https://docs.google.com/document/d/d1/edit")
        self.assertEqual(seen[1][0], "POST")
        self.assertIn(b"application/vnd.google-apps.document", seen[1][2])

    def test_upsert_doc_update_keeps_link(self):
        seen = []

        def fake(method, url, params=None, json=None, data=None, headers=None, timeout=None):
            seen.append((method, url, params, headers))
            if method == "GET":
                return Resp(200, {"files": [{"id": "d1"}]})
            return Resp(200, {"id": "d1", "webViewLink": "L"})

        with mock.patch.object(drive.requests, "request", side_effect=fake):
            self.assertEqual(drive.upsert_doc("f", "T", b"DOCX"), "L")
        self.assertEqual(seen[1][0], "PATCH")
        self.assertTrue(seen[1][1].endswith("/files/d1"))
        self.assertEqual(seen[1][3]["Content-Type"], drive.DOCX)


if __name__ == "__main__":
    unittest.main()
