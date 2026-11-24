import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import engine  # noqa: E402
import score  # noqa: E402

PAPERS = json.loads((HERE / "fixtures" / "score_papers.json").read_text(encoding="utf-8"))
CFG = {
    "profile": "AI engineer moving to robotics.", "score_batch": 2,
    "weights": {"career_fit": 2.0, "expert_expectation": 1.5, "foundational": 1.5, "impact": 1.0,
                "evidence": 0.75, "applicability": 0.75},
    "deep_gate": {"foundational": 3, "career_fit": 2}, "max_deep_per_night": 2,
    "min_total_overview": 9.0, "min_total_brief": 5.0, "capped_tracks": ["other_ai", "mechatronics"],
    "capped_tracks_overview_total": 13.0, "track_balance": ["genai", "robotics"], "balance_margin": 1.0,
    "budget_minutes": 90, "minutes_per_level": {"deep": 25, "overview": 5, "brief": 0.5}, "max_briefs": 25,
    "venues": ["CoRL"],
}


class FakeRun:
    def __init__(self):
        self.steps = []

    def record(self, step, **kw):
        self.steps.append((step, kw))


class FakeHistory:
    def feedback_examples(self, n):
        return [{"title": "Old paper", "one_liner": "did a thing", "level": "skip"}]


def row(i, cf=2, ee=2, fo=1, im=1, ev=1, ap=1, track="genai"):
    return {"index": i, "track": track, "one_liner": f"line {i}", "why": f"why {i}", "career_fit": cf,
            "expert_expectation": ee, "foundational": fo, "impact": im, "evidence": ev, "applicability": ap}


def sc(pid, track, cf, ee, fo, im=1, ev=1, ap=1, c=CFG):
    s = dict(career_fit=cf, expert_expectation=ee, foundational=fo, impact=im, evidence=ev, applicability=ap)
    return {"id": pid, "title": pid, "abstract": "a", "scores": s, "track": track, "one_liner": "o", "why": "w",
            "total": score.weighted_total(s, c["weights"])}


class ScoreTests(unittest.TestCase):
    def test_check(self):
        chk = score._make_check(2)
        chk({"papers": [row(1), row(2)]})
        with self.assertRaises(ValueError):
            chk({"papers": [row(1)]})
        with self.assertRaises(ValueError):
            chk({"papers": [row(1), row(1)]})
        with self.assertRaises(ValueError):
            chk({"papers": [row(1), row(2, cf=4)]})
        bad = row(2)
        bad["one_liner"] = "x" * 300
        with self.assertRaises(ValueError):
            chk({"papers": [row(1), bad]})
        with self.assertRaises(ValueError):
            chk({"papers": [row(1), row(2, track="cooking")]})

    def test_score_batches_and_message(self):
        calls = []

        def fake(run, step, system, user, schema, **kw):
            calls.append((step, user, kw))
            kw["check"]({"papers": [row(1), row(2)]})
            return {"papers": [row(1, fo=3), row(2)]}
        with mock.patch.object(engine, "llm_json", fake), mock.patch.object(engine, "prompt", lambda n: "RUBRIC"):
            out = score.score(FakeRun(), CFG, PAPERS, FakeHistory())
        self.assertEqual(len(calls), 1)
        user = calls[0][1]
        self.assertIn("<untrusted>", user)
        self.assertIn("AI engineer moving to robotics.", user)
        self.assertIn("Old paper", user)
        self.assertIn("venue: CoRL", user)              # from the comment
        self.assertIn("hf_upvotes: 10", user)
        self.assertEqual(out[0]["scores"]["foundational"], 3)
        self.assertEqual(out[0]["total"], 2 * 2 + 1.5 * 2 + 1.5 * 3 + 1 + 0.75 + 0.75)
        self.assertEqual(out[1]["id"], "arxiv:2611.00003")

    def test_failed_batch_becomes_briefs(self):
        def fake(run, step, *a, **k):
            raise engine.StepFailed("bad twice")
        with mock.patch.object(engine, "llm_json", fake), mock.patch.object(engine, "prompt", lambda n: "R"):
            out = score.score(FakeRun(), CFG, PAPERS, FakeHistory())
        self.assertEqual(len(out), 2)
        self.assertTrue(all(p["level"] == "brief" and p["fallback"] for p in out))
        self.assertEqual(out[0]["one_liner"], "We train a diffusion policy.")
        self.assertEqual(out[0]["track"], "robotics")

    def test_long_lines_trimmed(self):
        r = row(1)
        r["one_liner"] = ("word " * 40).strip()

        def fake(run, step, *a, **k):
            return {"papers": [r, row(2)]}
        with mock.patch.object(engine, "llm_json", fake), mock.patch.object(engine, "prompt", lambda n: "R"):
            out = score.score(FakeRun(), CFG, PAPERS, FakeHistory())
        self.assertLessEqual(len(out[0]["one_liner"]), 160)

    def test_first_sentence(self):
        self.assertEqual(score.first_sentence("We do X. Then Y."), "We do X.")
        self.assertEqual(score.first_sentence("No full stop here"), "No full stop here")
        self.assertLessEqual(len(score.first_sentence("a " * 300)), 160)


class SelectTests(unittest.TestCase):
    def test_deep_gate_and_levels(self):
        papers = [
            sc("deep1", "robotics", 3, 3, 3),            # passes the gate
            sc("high_not_foundational", "genai", 3, 3, 2, 3, 3, 3),   # high total but foundational 2 -> overview
            sc("foundational_low_career", "genai", 1, 2, 3, 2, 2, 2),  # career_fit 1: no deep
            sc("brief1", "genai", 1, 1, 1),
            sc("skip1", "genai", 0, 0, 0),
        ]
        out = {p["id"]: p for p in score.select(CFG, papers)}
        self.assertEqual(out["deep1"]["level"], "deep")
        self.assertEqual(out["high_not_foundational"]["level"], "overview")
        self.assertNotEqual(out["foundational_low_career"]["level"], "deep")
        self.assertEqual(out["brief1"]["level"], "brief")
        self.assertEqual(out["skip1"]["level"], "skip")
        self.assertNotIn("number", out["skip1"])

    def test_numbering_order(self):
        papers = [sc("b", "genai", 1, 1, 1), sc("o", "genai", 3, 3, 2, 3, 3, 3), sc("d", "robotics", 3, 3, 3),
                  sc("s", "genai", 0, 0, 0)]
        out = score.select(CFG, papers)
        shown = [p for p in out if "number" in p]
        self.assertEqual([(p["number"], p["id"], p["level"]) for p in shown],
                         [(1, "d", "deep"), (2, "o", "overview"), (3, "b", "brief")])
        self.assertEqual(out[-1]["id"], "s")

    def test_max_deep_and_budget(self):
        deeps = [sc(f"d{i}", "genai" if i % 2 else "robotics", 3, 3, 3, 3, 3, 3) for i in range(4)]
        out = score.select({**CFG, "max_deep_per_night": 2}, deeps)
        lv = [p["level"] for p in out]
        self.assertEqual(lv.count("deep"), 2)
        self.assertEqual(lv.count("overview"), 2)          # the other two become overviews
        out = score.select({**CFG, "max_deep_per_night": 4, "budget_minutes": 60}, deeps)
        self.assertEqual([p["level"] for p in out].count("deep"), 2)   # 60 min fits two 25-min deep reads

    def test_budget_losers_runner_up(self):
        cfg = {**CFG, "budget_minutes": 10, "max_briefs": 1}
        papers = [sc(f"o{i}", "genai", 3, 3, 2, 3, 3, 3) for i in range(5)]
        out = score.select(cfg, papers)
        lv = [p["level"] for p in out]
        self.assertEqual(lv.count("overview"), 2)           # 10 min = two overviews
        self.assertEqual(lv.count("brief"), 0)              # no minutes left for briefs
        self.assertEqual(lv.count("runner_up"), 3)
        self.assertTrue(all(p.get("runner_up") for p in out if p["level"] == "runner_up"))

    def test_capped_tracks(self):
        papers = [sc("odd", "other_ai", 2, 2, 1, 1, 1, 1), sc("mech_top", "mechatronics", 3, 3, 3, 3, 3, 3)]
        self.assertGreaterEqual(papers[0]["total"], 9.0)
        self.assertLess(papers[0]["total"], 13.0)
        out = {p["id"]: p["level"] for p in score.select(CFG, papers)}
        self.assertEqual(out["odd"], "brief")
        self.assertEqual(out["mech_top"], "deep")           # total 22.5 >= 13 and passes the gate

    def test_balance(self):
        papers = [sc("g1", "genai", 3, 3, 2, 3, 3, 3), sc("g2", "genai", 3, 3, 2, 3, 3, 2),
                  sc("r1", "robotics", 3, 3, 2, 3, 3, 1), sc("r2", "robotics", 3, 3, 2, 3, 2, 1)]
        order = [p["id"] for p in score.select(CFG, papers)]
        self.assertEqual(order, ["g1", "r1", "g2", "r2"])    # r1 is within the margin of g2, so it goes second
        far = [sc("g1", "genai", 3, 3, 2, 3, 3, 3), sc("g2", "genai", 2, 2, 2, 2, 2, 2), sc("r1", "robotics", 2, 1, 2, 1, 1, 1)]
        self.assertLess(far[2]["total"], far[1]["total"] - 1.0)
        self.assertEqual([p["id"] for p in score.select(CFG, far)], ["g1", "g2", "r1"])   # too far apart: totals win

    def test_fallback_papers_kept_as_briefs(self):
        fb = score._fallback({"id": "f", "title": "t", "abstract": "One. Two."}, CFG)
        out = score.select(CFG, [fb, sc("o", "genai", 3, 3, 2, 3, 3, 3)])
        self.assertEqual([(p["id"], p["level"]) for p in out], [("o", "overview"), ("f", "brief")])
        self.assertEqual(out[1]["number"], 2)

    def test_input_not_mutated(self):
        p = sc("x", "genai", 3, 3, 3)
        score.select(CFG, [p])
        self.assertNotIn("level", p)


if __name__ == "__main__":
    unittest.main()
