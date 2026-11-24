import sys
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from history import History  # noqa: E402


def scored(pid, level="brief", total=6.0, number=None, title=None):
    return {"id": pid, "title": title or f"Title {pid}", "one_liner": f"line {pid}", "level": level,
            "total": total, "number": number, "scores": {"career_fit": 1}, "track": "genai", "why": "w",
            "abstract": "abs", "sources": ["arxiv"]}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = History(Path(self.tmp.name) / "h.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_seen_get_digest_paper(self):
        self.assertFalse(self.h.seen("a"))
        self.h.add(scored("a", number=3), date(2026, 11, 24))
        self.assertTrue(self.h.seen("a"))
        self.assertEqual(self.h.get("a")["title"], "Title a")
        self.assertIsNone(self.h.get("zzz"))
        self.assertEqual(self.h.digest_paper(date(2026, 11, 24), 3), "a")
        self.assertEqual(self.h.digest_paper("2026-11-24", 3), "a")
        self.assertIsNone(self.h.digest_paper("2026-11-24", 4))

    def test_feedback_examples_latest_per_paper(self):
        self.h.add(scored("a"), "2026-11-24")
        self.h.add(scored("b"), "2026-11-24")
        self.h.feedback_add("a", "skip", "reply")
        self.h.feedback_add("b", "deep", "reply")
        self.h.feedback_add("a", "overview", "reply")
        ex = self.h.feedback_examples(10)
        self.assertEqual([(e["title"], e["level"]) for e in ex], [("Title a", "overview"), ("Title b", "deep")])
        self.assertEqual(len(self.h.feedback_examples(1)), 1)

    def test_concepts_unique(self):
        self.h.concepts_add(["Diffusion", " Action chunking ", ""], "a")
        self.h.concepts_add(["Diffusion"], "b")
        self.assertEqual(sorted(self.h.concepts()), ["Action chunking", "Diffusion"])

    def test_drive_and_reports(self):
        self.assertIsNone(self.h.drive_folder("a"))
        self.h.set_drive_folder("a", "F1", "http://x")
        self.assertEqual(self.h.drive_folder("a"), "F1")
        self.assertIsNone(self.h.report("a"))
        self.h.set_report("a", "# R", "chat1")
        self.h.set_report("a", "# R2", "chat1")
        self.assertEqual(self.h.report("a"), {"markdown": "# R2", "chat_id": "chat1"})

    def test_paper_numbers_per_month(self):
        self.assertEqual([self.h.next_paper_number(2026, 11) for _ in range(3)], [1, 2, 3])
        self.assertEqual(self.h.next_paper_number(2026, 12), 1)

    def test_queue(self):
        self.assertIsNone(self.h.queue_next())
        q1 = self.h.queue_add("https://arxiv.org/abs/2611.00001", "chat")
        self.h.queue_add("https://example.com/p.pdf", "http")
        n = self.h.queue_next()
        self.assertEqual((n["id"], n["url"]), (q1, "https://arxiv.org/abs/2611.00001"))
        self.assertEqual(self.h.queue_next()["url"], "https://example.com/p.pdf")
        self.assertIsNone(self.h.queue_next())
        self.h.queue_done(q1, False, "no full text")

    def test_runners_up(self):
        today = date.today()
        self.h.add(scored("r1", level="runner_up", total=10), today)
        self.h.add(scored("r2", level="runner_up", total=12), today)
        self.h.add(scored("old", level="runner_up", total=15), date(2020, 1, 1))
        self.h.add(scored("shown", level="brief"), today)
        ru = self.h.runners_up(7)
        self.assertEqual([p["id"] for p in ru], ["r2", "r1"])
        self.assertNotIn("scores", ru[0])
        self.assertNotIn("level", ru[0])
        self.assertEqual(ru[0]["abstract"], "abs")

    def test_threads(self):
        errs = []

        def work(k):
            try:
                for i in range(20):
                    self.h.add(scored(f"{k}-{i}"), "2026-11-24")
                    self.h.seen(f"{k}-{i}")
            except Exception as e:  # pragma: no cover
                errs.append(e)
        ts = [threading.Thread(target=work, args=(k,)) for k in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])
        self.assertTrue(self.h.seen("3-19"))


if __name__ == "__main__":
    unittest.main()
