import json
import os
import sys
import tempfile
import threading
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from urllib import request as urlreq
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
TMP = tempfile.mkdtemp()
os.environ.update(PAPER_STATE=TMP, ULTRON_API_KEY="k", NTFY_TOPIC="t", NTFY_TOKEN="tk", PAPER_QUEUE_KEY="secret")

import common  # noqa: E402
import digest  # noqa: E402
import engine  # noqa: E402

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
CFG = {"timezone": "Asia/Ho_Chi_Minh", "run_at": "02:00", "hard_stop": "05:45", "push_at": "06:10",
       "quiet_start": "05:45", "quiet_end": "06:15", "show_scores": True, "chat_folder": "Papers",
       "digest_title": "Papers · {date:%a %d %b}", "deep_title": "Paper · {short_title}", "model": "ultron",
       "drive_save_levels": ["deep", "overview"], "hf_daily_papers": True, "semantic_scholar": True}
SC = {"career_fit": 3, "expert_expectation": 2, "foundational": 3, "impact": 2, "evidence": 2, "applicability": 1}


def paper(i, level, track="genai", **kw):
    p = {"id": f"arxiv:2511.{i:05d}", "title": f"Paper {i}: a subtitle", "url": f"https://arxiv.org/abs/2511.{i:05d}",
         "abstract": "abs", "sources": ["arxiv", "hf"], "s2": {"citations": 1}, "scores": dict(SC), "total": 14.5,
         "track": track, "one_liner": f"does thing {i}", "why": f"matters {i}", "level": level, "number": i}
    p.update(kw)
    return p


REPORT = "### Part 1\nA. **TL;DR** — The problem.\nThe idea. The result.\nB. **The problem** — text\n"


class FakeHistory:
    log: list = []
    papers: dict = {}

    def __init__(self):
        pass

    def add(self, p, day): FakeHistory.log.append(("add", p["id"], p["level"]))
    def set_report(self, pid, md, chat): FakeHistory.log.append(("report", pid, chat))
    def concepts_add(self, items, pid): FakeHistory.log.append(("concepts", pid, items))
    def get(self, pid): return FakeHistory.papers.get(pid)
    def digest_paper(self, day, n): return {1: "arxiv:2511.00001", 2: "arxiv:2511.00002"}.get(n)
    def feedback_add(self, pid, level, src): FakeHistory.log.append(("fb", pid, level))
    def queue_add(self, url, src): FakeHistory.log.append(("queue_add", url))
    def queue_next(self): return None
    def queue_done(self, qid, ok, note): FakeHistory.log.append(("done", qid, ok, note))


def install_fakes(selected, deep_fail=(), over_fail=()):
    FakeHistory.log, FakeHistory.papers = [], {}
    collect = types.SimpleNamespace(collect=lambda run, c, h, today: list(selected),
                                    paper_from_url=lambda url: paper(9, "deep", url=url))
    score = types.SimpleNamespace(score=lambda run, c, p, h: p, select=lambda c, s: [dict(x) for x in s])

    def deep_read(run, c, p, h):
        if p["id"] in deep_fail:
            raise RuntimeError("no full text")
        return {"markdown": REPORT, "short_title": f"Short{p['number']}", "concepts": ["c1"],
                "fulltext": {"text": "FULL TEXT " * 10, "pdf_bytes": b"%PDF-x"}}

    def overview(run, c, p):
        if p["id"] in over_fail:
            raise RuntimeError("bad")
        return {"markdown": f"OVERVIEW OF {p['number']}", "fulltext": None}

    reports = types.SimpleNamespace(deep_read=deep_read, overview=overview)
    drive = mock.Mock()
    drive.enabled.return_value = True
    drive.paper_folder.return_value = ("fid", "http://drive/f")
    fakes = {"history": types.SimpleNamespace(History=FakeHistory), "collect": collect, "score": score,
             "reports": reports, "drive": drive}
    return fakes, drive


class ComposeTests(unittest.TestCase):
    def test_tldr(self):
        self.assertEqual(digest.tldr(REPORT), "The problem.\nThe idea. The result.")
        self.assertEqual(digest.tldr("no marker here"), "no marker here")

    def test_parse_commands(self):
        text = "deep 3\n3 skip\nDeep 12\n`7 Overview`\nhello there\n4 maybe\nbrief 2 please"
        self.assertEqual(digest.parse_commands(text),
                         [("deep", 3), ("skip", 3), ("deep", 12), ("overview", 7)])

    def test_scores_line(self):
        self.assertEqual(digest.scores_line(paper(1, "deep")),
                         "scores: fit 3 · expert 2 · found 3 · impact 2 · evid 2 · apply 1 = 14.5")

    def test_compose_sections(self):
        items = [paper(1, "deep"), paper(2, "overview"), paper(3, "brief"), paper(4, "brief", track="robotics")]
        md = digest.compose_digest(CFG, items,
                                   {items[0]["id"]: {"markdown": REPORT}, items[1]["id"]: {"markdown": "OV2"}},
                                   {items[0]["id"]: "chat9"}, ["arXiv unavailable tonight"])
        self.assertIn("1 deep read, 1 overview, 2 briefs", md)
        self.assertIn("Sources: arXiv unavailable tonight.", md)
        self.assertIn("[Open the deep-read chat](/c/chat9)", md)
        self.assertIn("### 2. Paper 2: a subtitle", md)
        self.assertLess(md.index("**GenAI**"), md.index("**Robotics**"))
        self.assertIn("[Paper 3: a subtitle](https://arxiv.org/abs/2511.00003): does thing 3", md)
        self.assertIn("Why: matters 3", md)
        self.assertIn("`deep 3`", md)
        self.assertIn("/doc", md)

    def test_scores_hidden_when_off(self):
        md = digest.compose_digest({**CFG, "show_scores": False}, [paper(3, "brief")], {}, {}, [])
        self.assertNotIn("scores:", md)

    def test_source_notes(self):
        notes = digest.source_notes(CFG, [paper(1, "brief", sources=["hf"], s2=None)], datetime(2026, 11, 24).date())
        self.assertIn("arXiv unavailable tonight", notes)
        self.assertIn("Semantic Scholar unavailable tonight", notes)
        weekend = digest.source_notes(CFG, [paper(1, "brief", sources=["hf"])], datetime(2026, 11, 22).date())
        self.assertIn("no new arXiv listing today (weekend)", weekend)

    def test_build_system_caps_length(self):
        system, cut = digest.build_system("T" * 1000, "x" * 100000, cap=5000)
        self.assertTrue(cut)
        self.assertLessEqual(len(system), 5000)
        self.assertIn("<untrusted>", system)
        self.assertIn("was cut for length", system)
        system, cut = digest.build_system("T" * 1000, "short", cap=5000)
        self.assertFalse(cut)

    def test_quiet_hours(self):
        self.assertTrue(digest.in_quiet(CFG, datetime(2026, 11, 24, 6, 0, tzinfo=TZ)))
        self.assertFalse(digest.in_quiet(CFG, datetime(2026, 11, 24, 6, 15, tzinfo=TZ)))
        self.assertFalse(digest.in_quiet(CFG, datetime(2026, 11, 24, 3, 0, tzinfo=TZ)))

    def test_schedule_rules(self):
        c = CFG
        self.assertTrue(digest.nightly_pending(c, datetime(2026, 11, 24, 2, 5, tzinfo=TZ), {}))
        self.assertFalse(digest.nightly_pending(c, datetime(2026, 11, 24, 2, 5, tzinfo=TZ), {"last_run": "2026-11-24"}))
        self.assertFalse(digest.nightly_pending(c, datetime(2026, 11, 24, 1, 0, tzinfo=TZ), {}))
        self.assertFalse(digest.nightly_pending(c, datetime(2026, 11, 24, 9, 0, tzinfo=TZ), {}))
        pend = {"pending_push": {"date": "2026-11-24"}}
        self.assertFalse(digest.push_due(c, datetime(2026, 11, 24, 5, 0, tzinfo=TZ), pend))
        self.assertTrue(digest.push_due(c, datetime(2026, 11, 24, 6, 10, tzinfo=TZ), pend))
        self.assertTrue(digest.push_due(c, datetime(2026, 11, 25, 1, 0, tzinfo=TZ), pend))


class NightlyTests(unittest.TestCase):
    def run_it(self, selected, now, opts=None, **kw):
        fakes, drive = install_fakes(selected, **kw)
        created, pushes = [], []

        def create_chat(title, user_line, text, system=None, folder="Papers", model="ultron"):
            created.append({"title": title, "text": text, "system": system})
            return f"chat{len(created)}"

        with mock.patch.dict(sys.modules, fakes), mock.patch.object(engine, "cfg", lambda: dict(CFG)), \
                mock.patch.object(common, "create_chat", create_chat), \
                mock.patch.object(common, "push", lambda *a, **k: pushes.append(a)):
            res = digest.run_night(opts or digest.Opts(), now=now)
        return res, created, drive

    def test_full_run(self):
        sel = [paper(1, "deep"), paper(2, "overview"), paper(3, "brief"), paper(4, "skip")]
        res, created, drive = self.run_it(sel, datetime(2026, 11, 25, 2, 0, tzinfo=TZ))
        self.assertEqual(res["counts"], {"deep": 1, "overview": 1, "brief": 1})
        self.assertEqual([c["title"] for c in created], ["Paper · Short1", "Papers · Wed 25 Nov"])
        self.assertIn("<untrusted>", created[0]["system"])
        self.assertIn("This chat holds tonight's paper digest", created[1]["system"])
        self.assertIn("[Open the deep-read chat](/c/chat1)", created[1]["text"])
        self.assertEqual(res["digest_chat_id"], "chat2")
        self.assertEqual(res["push"]["title"], "Papers ready")
        self.assertTrue(res["push"]["body"].startswith("1 deep read, 1 overview, 1 brief"))
        self.assertIn("Top: Paper 1", res["push"]["body"])
        log = FakeHistory.log
        self.assertIn(("add", "arxiv:2511.00004", "skip"), log)
        self.assertIn(("report", "arxiv:2511.00001", "chat1"), log)
        self.assertIn(("report", "arxiv:2511.00002", "chat2"), log)
        self.assertIn(("concepts", "arxiv:2511.00001", ["c1"]), log)
        self.assertEqual(drive.upload_pdf.call_count, 1)   # the overview has no pdf bytes and no pdf_url

    def test_hard_stop_demotes(self):
        sel = [paper(1, "deep"), paper(2, "overview")]
        real = digest.datetime
        late = datetime(2026, 11, 25, 5, 50, tzinfo=TZ)

        class Clock(real):
            @classmethod
            def now(cls, tz=None):
                return late

        with mock.patch.object(digest, "datetime", Clock):
            res, created, _ = self.run_it(sel, datetime(2026, 11, 25, 2, 0, tzinfo=TZ))
        self.assertEqual(res["counts"], {"deep": 0, "overview": 0, "brief": 2})
        self.assertIn("time ran out", res["markdown"])

    def test_failures_fall_back(self):
        sel = [paper(1, "deep"), paper(2, "overview")]
        res, created, _ = self.run_it(sel, datetime(2026, 11, 25, 2, 0, tzinfo=TZ),
                                      deep_fail={"arxiv:2511.00001"}, over_fail={"arxiv:2511.00002"})
        self.assertEqual(res["counts"], {"deep": 0, "overview": 1, "brief": 1})   # deep 1 became an overview

    def test_no_deep_option(self):
        res, created, _ = self.run_it([paper(1, "deep")], datetime(2026, 11, 25, 2, 0, tzinfo=TZ),
                                      opts=digest.Opts(no_deep=True))
        self.assertEqual(res["counts"], {"deep": 0, "overview": 1, "brief": 0})

    def test_dry_run_writes_nothing(self):
        res, created, drive = self.run_it([paper(1, "deep")], datetime(2026, 11, 25, 2, 0, tzinfo=TZ),
                                          opts=digest.Opts(dry_run=True))
        self.assertEqual(created, [])
        self.assertEqual(FakeHistory.log, [])
        drive.upload_pdf.assert_not_called()
        self.assertIsNone(res["digest_chat_id"])

    def test_drive_failure_only_logs(self):
        fakes, drive = install_fakes([paper(1, "deep")])
        drive.upload_pdf.side_effect = RuntimeError("quota")
        with mock.patch.dict(sys.modules, fakes):
            digest.save_to_drive(FakeHistory(), paper(1, "deep"), {"pdf_bytes": b"%PDF"}, datetime(2026, 11, 25).date())


class QueueAndPollTests(unittest.TestCase):
    def test_process_queue_item_success(self):
        fakes, drive = install_fakes([])
        pushes = []
        with mock.patch.dict(sys.modules, fakes), mock.patch.object(engine, "cfg", lambda: dict(CFG)), \
                mock.patch.object(common, "create_chat", lambda *a, **k: "chatq"), \
                mock.patch.object(common, "push", lambda *a, **k: pushes.append(a)):
            ok = digest.process_queue_item({"id": 5, "url": "https://arxiv.org/abs/2511.00009"})
        self.assertTrue(ok)
        self.assertIn(("done", 5, True, ""), FakeHistory.log)
        self.assertIn(("report", "arxiv:2511.00009", "chatq"), FakeHistory.log)
        self.assertEqual(pushes[0][0], "Deep read ready")

    def test_process_queue_item_failure_pushes_reason(self):
        fakes, _ = install_fakes([])
        fakes["collect"].paper_from_url = mock.Mock(side_effect=RuntimeError("could not fetch"))
        pushes = []
        with mock.patch.dict(sys.modules, fakes), mock.patch.object(engine, "cfg", lambda: dict(CFG)), \
                mock.patch.object(common, "push", lambda *a, **k: pushes.append(a)):
            ok = digest.process_queue_item({"id": 6, "url": "https://x.org/a.pdf"})
        self.assertFalse(ok)
        self.assertEqual(pushes[0][0], "Paper not read")
        self.assertIn("could not fetch", pushes[0][1])
        self.assertIn(("done", 6, False, "could not fetch"), FakeHistory.log)

    def test_digest_replies(self):
        fakes, _ = install_fakes([])
        FakeHistory.papers = {"arxiv:2511.00001": {"level": "overview", "url": "https://arxiv.org/abs/2511.00001"},
                              "arxiv:2511.00002": {"level": "deep", "url": "u2"}}
        msgs = [{"id": "m1", "role": "user", "content": "Tonight's papers"},
                {"id": "m2", "role": "user", "content": "deep 1\n2 deep\n1 skip\ndeep 99"},
                {"id": "m3", "role": "assistant", "content": "Noted."}]
        with mock.patch.dict(sys.modules, fakes), mock.patch.object(common, "chat_messages", lambda cid: msgs):
            used = digest.handle_digest_chat({"id": "cd", "created_at": 1795000000}, TZ, {"m1"})
        self.assertEqual(used, ["m2"])
        log = FakeHistory.log
        self.assertEqual(log.count(("queue_add", "https://arxiv.org/abs/2511.00001")), 1)   # paper 2 already deep
        self.assertIn(("fb", "arxiv:2511.00001", "skip"), log)
        self.assertIn(("fb", "arxiv:2511.00002", "deep"), log)

    def doc_row_test(self, msgs, handled, enabled=True):
        fakes, drive = install_fakes([])
        drive.enabled.return_value = enabled
        doc = types.SimpleNamespace(make_doc=mock.Mock(return_value="http://doc"))
        fakes["doc"] = doc
        pushes = []
        with mock.patch.dict(sys.modules, fakes), mock.patch.object(engine, "cfg", lambda: dict(CFG)), \
                mock.patch.object(common, "chat_messages", lambda cid: msgs), \
                mock.patch.object(common, "push", lambda *a, **k: pushes.append(a)):
            mid = digest.handle_doc({"id": "cp", "title": "Paper · X"}, handled)
        return mid, doc, pushes

    def test_doc_command(self):
        msgs = [{"id": "u1", "role": "user", "content": "q"}, {"id": "u2", "role": "user", "content": "/doc"}]
        mid, doc, pushes = self.doc_row_test(msgs, set())
        self.assertEqual(mid, "u2")
        doc.make_doc.assert_called_once()
        self.assertEqual(pushes[0][0], "Report saved to Drive")
        mid, doc, _ = self.doc_row_test(msgs, {"u2"})          # already handled
        self.assertIsNone(mid)
        doc.make_doc.assert_not_called()
        mid, doc, _ = self.doc_row_test(msgs + [{"id": "u3", "role": "user", "content": "why?"}], set())
        self.assertIsNone(mid)                                  # /doc is not the newest message

    def test_doc_without_drive(self):
        msgs = [{"id": "u2", "role": "user", "content": "/doc"}]
        mid, doc, pushes = self.doc_row_test(msgs, set(), enabled=False)
        self.assertEqual(mid, "u2")
        doc.make_doc.assert_not_called()
        self.assertIn("google-auth.py", pushes[0][1])


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.srv = digest.make_server("127.0.0.1", 0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        FakeHistory.log = []
        self.mods = mock.patch.dict(sys.modules, {"history": types.SimpleNamespace(History=FakeHistory)})
        self.mods.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.mods.stop()

    def post(self, body, key="secret"):
        req = urlreq.Request(f"http://127.0.0.1:{self.port}/queue", data=json.dumps(body).encode(), method="POST",
                             headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            return urlreq.urlopen(req, timeout=5).status
        except HTTPError as e:
            return e.code

    def test_queue_endpoint(self):
        self.assertEqual(self.post({"url": "https://arxiv.org/abs/2511.00001"}), 200)
        self.assertIn(("queue_add", "https://arxiv.org/abs/2511.00001"), FakeHistory.log)
        self.assertEqual(self.post({"url": "https://arxiv.org/abs/2511.00001"}, key="wrong"), 401)
        self.assertEqual(self.post({"url": "ftp://nope"}), 400)

    def test_health(self):
        self.assertEqual(urlreq.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=5).status, 200)


if __name__ == "__main__":
    unittest.main()
