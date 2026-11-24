import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import collect  # noqa: E402
from history import History  # noqa: E402

FX = HERE / "fixtures"
ARXIV_XML = (FX / "collect_arxiv.xml").read_text(encoding="utf-8")
HF = json.loads((FX / "collect_hf.json").read_text(encoding="utf-8"))
S2 = json.loads((FX / "collect_s2.json").read_text(encoding="utf-8"))
EMPTY_FEED = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'

CFG = {
    "arxiv_categories": ["cs.RO", "cs.LG"], "arxiv_max_results": 400, "hf_daily_papers": True,
    "semantic_scholar": True, "labs": ["Physical Intelligence", "NVIDIA", "Meta"], "venues": ["CoRL", "ICRA"],
    "topics": {"genai": {"keywords": ["language model", "RAG", "rerank", "tool use"]},
               "robotics": {"keywords": ["robot", "diffusion policy", "manipulation"]}},
}


class Resp:
    def __init__(self, text="", js=None, status=200):
        self.text, self._js, self.status_code = text, js, status

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise collect.requests.HTTPError(f"HTTP {self.status_code}")


class FakeRun:
    def __init__(self):
        self.steps = []

    def record(self, step, **kw):
        self.steps.append((step, kw))


def fake_get(arxiv_text=ARXIV_XML, hf=HF, arxiv_status=200, hf_status=200):
    def get(url, params=None, **kw):
        if url == collect.ARXIV_API:
            return Resp(text=arxiv_text, status=arxiv_status)
        if url == collect.HF_API:
            return Resp(js=hf, status=hf_status)
        raise AssertionError(url)
    return get


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hist = History(Path(self.tmp.name) / "h.db")
        for p in (mock.patch.object(collect, "ARXIV_GAP", 0), mock.patch.object(collect.time, "sleep", lambda s: None)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_collect(self, get=None, post=None, cfg=None):
        get = get or fake_get()
        post = post or (lambda *a, **k: Resp(js=S2))
        with mock.patch.object(collect.requests, "get", get), mock.patch.object(collect.requests, "post", post):
            return collect.collect(FakeRun(), cfg or CFG, self.hist, date(2026, 11, 24))

    def test_parse_feed(self):
        p = collect.parse_arxiv_feed(ARXIV_XML)[0]
        self.assertEqual(p["id"], "arxiv:2611.00001")
        self.assertEqual(p["title"], "Diffusion Policy for Humanoid Manipulation")
        self.assertEqual(p["categories"], ["cs.RO", "cs.LG"])
        self.assertEqual(p["authors"], ["Ada Lovelace", "Alan Turing"])
        self.assertEqual(p["published"], "2026-11-23")
        self.assertEqual(p["pdf_url"], "https://arxiv.org/pdf/2611.00001v2")
        self.assertEqual(p["html_url"], "https://arxiv.org/html/2611.00001")
        self.assertEqual(p["comment"], "Accepted to CoRL 2026")

    def test_window_merge_prefilter_and_labs(self):
        papers, notes = self.run_collect()
        ids = {p["id"]: p for p in papers}
        self.assertEqual(notes, [])
        self.assertNotIn("arxiv:2611.00004", ids)            # outside the window
        self.assertNotIn("arxiv:2611.00002", ids)            # meta-learning on graphs: no keyword
        self.assertIn("arxiv:2611.00005", ids)               # HF papers always pass
        self.assertEqual(ids["arxiv:2611.00003"]["sources"], ["arxiv", "hf"])
        self.assertEqual(ids["arxiv:2611.00003"]["hf_upvotes"], 41)
        self.assertEqual(ids["arxiv:2611.00003"]["labs"], ["NVIDIA"])   # via the HF organisation
        self.assertEqual(ids["arxiv:2611.00001"]["labs"], ["Physical Intelligence"])
        self.assertEqual(ids["arxiv:2611.00001"]["topics"], ["robotics"])
        self.assertEqual(ids["arxiv:2611.00003"]["topics"], ["genai"])
        self.assertEqual(ids["arxiv:2611.00001"]["s2"]["max_author_hindex"], 55)
        self.assertEqual([r["title"] for r in ids["arxiv:2611.00001"]["s2"]["references"]], ["Diffusion Policy", "ACT"])
        self.assertNotIn("_org", ids["arxiv:2611.00003"])

    def test_seen_dropped(self):
        self.hist.add({"id": "arxiv:2611.00001", "title": "x", "level": "skip"}, "2026-11-23")
        papers, _ = self.run_collect()
        self.assertNotIn("arxiv:2611.00001", {p["id"] for p in papers})

    def test_arxiv_failure_is_a_note(self):
        papers, notes = self.run_collect(get=fake_get(arxiv_status=500))
        self.assertIn("arXiv unavailable", notes)
        self.assertEqual({p["id"] for p in papers}, {"arxiv:2611.00003", "arxiv:2611.00005"})

    def test_hf_failure_is_a_note(self):
        papers, notes = self.run_collect(get=fake_get(hf_status=503))
        self.assertIn("Hugging Face Daily Papers unavailable", notes)
        self.assertEqual({p["id"] for p in papers}, {"arxiv:2611.00001", "arxiv:2611.00003"})

    def test_s2_429_skipped(self):
        papers, notes = self.run_collect(post=lambda *a, **k: Resp(status=429))
        self.assertTrue(papers)
        self.assertTrue(all(p["s2"] is None for p in papers))
        self.assertTrue(any("Semantic Scholar" in n for n in notes))

    def test_s2_all_unknown_is_not_an_error(self):
        papers, notes = self.run_collect(
            post=lambda *a, **k: Resp(text='{"error":"No valid paper ids given"}', status=400))
        self.assertTrue(papers)
        self.assertEqual(notes, [])

    def test_s2_exception_skipped(self):
        def boom(*a, **k):
            raise collect.requests.ConnectionError("down")
        papers, notes = self.run_collect(post=boom)
        self.assertTrue(papers)
        self.assertTrue(any("Semantic Scholar" in n for n in notes))

    def test_weekend_adds_runners_up(self):
        self.hist.add({"id": "arxiv:2611.00009", "arxiv_id": "2611.00009", "title": "Runner", "abstract": "robot",
                       "level": "runner_up", "total": 11, "sources": ["arxiv"], "authors": [], "categories": []},
                      date.today())
        papers, notes = self.run_collect(get=fake_get(arxiv_text=EMPTY_FEED, hf=[]))
        got = [p for p in papers if p["id"] == "arxiv:2611.00009"]
        self.assertEqual(len(got), 1)
        self.assertTrue(any("runner-up" in n for n in notes))
        self.assertNotIn("level", got[0])
        self.assertNotIn("_ru", got[0])

    def test_keyword_matching_is_wordish(self):
        m = collect.topic_matchers(CFG)

        def hit(t):
            return collect.topic_hits({"title": t, "abstract": ""}, m)
        self.assertEqual(hit("ROBOTS that learn"), ["robotics"])
        self.assertEqual(hit("Tool-use agents"), ["genai"])
        self.assertEqual(hit("tool   use"), ["genai"])
        self.assertEqual(hit("A language-model approach"), ["genai"])
        self.assertEqual(hit("Robotics survey"), [])          # 'robot' must not match inside a longer word
        self.assertEqual(hit("pottery"), [])

    def test_labs_case_sensitive_and_model_names(self):
        labs = ["Meta", "Qwen", "Stanford"]

        def f(text):
            return collect.match_labs({"abstract": text, "comment": "", "authors": []}, labs)
        self.assertEqual(f("meta-learning is neat"), [])
        self.assertEqual(f("We fine-tune Qwen3-VL"), [])
        self.assertEqual(f("From Stanford and Meta AI"), ["Meta", "Stanford"])

    def test_paper_from_url_arxiv(self):
        one = ARXIV_XML.replace("2611.00002", "2611.00001")
        with mock.patch.object(collect.requests, "get", fake_get(arxiv_text=one)), \
                mock.patch.object(collect.requests, "post", lambda *a, **k: Resp(js=S2[:1])):
            p = collect.paper_from_url("https://arxiv.org/pdf/2611.00001v3.pdf", CFG)
        self.assertEqual(p["id"], "arxiv:2611.00001")
        self.assertEqual(p["sources"], ["arxiv", "queue"])
        self.assertEqual(p["s2"]["citations"], 12)

    def test_paper_from_url_not_on_arxiv(self):
        with mock.patch.object(collect.requests, "get", fake_get(arxiv_text=EMPTY_FEED)):
            with self.assertRaises(ValueError):
                collect.paper_from_url("https://arxiv.org/abs/2611.77777", CFG)

    def test_paper_from_url_other(self):
        p = collect.paper_from_url("https://example.com/papers/My-Great_Paper.pdf", CFG)
        self.assertTrue(p["id"].startswith("url:") and len(p["id"]) == 4 + 12)
        self.assertEqual(p["pdf_url"], "https://example.com/papers/My-Great_Paper.pdf")
        self.assertEqual(p["sources"], ["queue"])
        self.assertEqual(p["title"], "My Great Paper")
        self.assertIsNone(p["arxiv_id"])

    def test_arxiv_url_regex(self):
        for u, want in [("https://arxiv.org/abs/2611.12345v2", "2611.12345"), ("http://arxiv.org/html/2611.1234", "2611.1234"),
                        ("https://arxiv.org/pdf/cs/0112017", "cs/0112017")]:
            self.assertEqual(collect.ARXIV_URL_RE.search(u).group(1), want)


if __name__ == "__main__":
    unittest.main()
