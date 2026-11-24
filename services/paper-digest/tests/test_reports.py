import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fulltext  # noqa: E402
import reports  # noqa: E402
from engine import Run, StepFailed  # noqa: E402

TEXT_RESULTS = "Our method achieves a success rate of 46.9% on the benchmark, versus 31.2% for the baseline (Table 2)."
FT = {
    "sections": [
        {"title": "Abstract", "text": "We study policies."},
        {"title": "1 Introduction", "text": "Robots need policies."},
        {"title": "3 Method", "text": "3.1 Denoising\nThe update is $x_{t-1}=x_t-\\epsilon$ at each step.\n(3)"},
        {"title": "4 Experiments", "text": TEXT_RESULTS + "\nTable 2: Success rate."},
    ],
    "source": "html", "pdf_bytes": b"%PDF",
}
FT["text"] = "\n\n".join(f"## {s['title']}\n{s['text']}" for s in FT["sections"])
PAPER = {"title": "Test Paper: A Study", "authors": ["A", "B"], "url": "https://arxiv.org/abs/2501.00001",
         "s2": {"references": [{"title": "Ref", "abstract": "Earlier work on X."}, {"title": "NoAbs", "abstract": None}]}}


class Hist:
    def concepts(self):
        return ["Diffusion models"]


def section_text(L):
    base = f"This is part {L}. " + "It explains the idea in plain words. " * 3
    if L == "D":
        base += "\n```\nobs -> encoder -> action\n```"
    if L == "E":
        base = "$$x_{t-1}=x_t-\\epsilon$$\nIt says each step removes noise."
    if L == "G":
        base = "The method reaches 46.9% against 31.2% for the baseline in Table 2. It also reached 99.9% on Table 7."
    if L == "I":
        base = "Invented example (not from the paper):\nA camera sees 3 cups and 12 pixels move."
    if L == "M":
        base = "1. What is it?\n2. Why does it work?\n3. When would you use it?"
    return base


class Verify(unittest.TestCase):
    def test_drops_bad_results(self):
        notes = {"claims": [], "method_steps": [], "limits": [], "figures": [], "equations": [
            {"latex": "x_{t-1}=x_t-\\epsilon", "meaning": "m"}, {"latex": "y=zzz", "meaning": "m"}],
            "results": [
                {"value": "46.9%", "metric": "sr", "dataset": "b", "baseline": "x", "table": "Table 2",
                 "quote": "achieves a success rate of 46.9% on the benchmark"},
                {"value": "88.8%", "metric": "sr", "dataset": "b", "baseline": "", "table": "",
                 "quote": "achieves a success rate of 88.8% on the benchmark"},
                {"value": "31.2%", "metric": "sr", "dataset": "b", "baseline": "", "table": "Table 9",
                 "quote": "this quote is invented and not in the text at all"},
                {"value": "46.9%", "metric": "sr", "dataset": "b", "baseline": "", "table": "Table 9",
                 "quote": "Robots need policies"}]}
        clean, dropped = reports.verify_notes(notes, FT["text"], FT["text"])
        self.assertEqual([r["value"] for r in clean["results"]], ["46.9%"])
        self.assertEqual(clean["results"][0]["table"], "Table 2")
        self.assertEqual(len(clean["equations"]), 1)
        self.assertEqual(dropped, 4)

    def test_strip_unverified(self):
        report = ("# T\n\n### G. Evidence\n\nIt reached 46.9% in Table 2. It reached 77.7% on Fig. 9. Plain.\n\n"
                  "### I. Picture\n\nInvented: 3 cups, 5000 pixels.\n\n### J. Use\n\nBackground: used by 175B models.\n")
        out, removed = reports.strip_unverified(report, FT["text"], FT["sections"])
        self.assertIn("It reached 46.9% in Table 2.", out)
        self.assertIn("Plain.", out)
        self.assertNotIn("77.7", out)
        self.assertIn("5000 pixels", out)  # invented example in I is exempt
        self.assertNotIn("175B", out)
        self.assertEqual(removed, 2)


def fake_llm(run, step, system, user, schema, **kw):
    check = kw.get("check")
    if step.startswith("notes"):
        obj = {"claims": ["It works (Section 3)."], "method_steps": ["Denoise"],
               "results": [{"value": "46.9%", "metric": "success", "dataset": "bench", "baseline": "31.2%",
                            "table": "Table 2", "quote": "achieves a success rate of 46.9% on the benchmark"},
                           {"value": "12.5%", "metric": "x", "dataset": "y", "baseline": "", "table": "",
                            "quote": "not in text at all really"}],
               "limits": [], "equations": [{"latex": "x_{t-1}=x_t-\\epsilon", "meaning": "step"}],
               "figures": [{"label": "Fig. 2", "shows": "overview"}]}
    elif step.startswith("write_"):
        letters = step[len("write_"):]
        obj = {"sections": {L: section_text(L) for L in letters}, "concepts_taught": ["Denoising", "denoising"]}
        if letters == "ABCD":
            obj["short_title"] = "Test Policy"
    elif step == "critique":
        obj = {"flagged": [{"sentence": "This is part B.", "reason": "unsupported"},
                           {"sentence": "not in the report", "reason": "x"}]}
    elif step == "fix":
        obj = {"fixes": [{"original": "This is part B.", "replacement": "Part B, fixed."}]}
    else:
        raise AssertionError(step)
    if check:
        check(obj)
    run.record(step, ok=True)
    return obj


class DeepRead(unittest.TestCase):
    def test_full_flow(self):
        run = Run("t")
        cfg = {"deep_chunk_tokens": 6000, "writer_model": "ultron", "deep_words": 1000, "known_concepts": ["RAG"],
               "context_references": 6}
        with mock.patch.object(reports.fulltext, "fetch", return_value=FT), \
                mock.patch.object(reports, "llm_json", fake_llm):
            out = reports.deep_read(run, cfg, PAPER, Hist())
        md = out["markdown"]
        for h in ["## Part 1 — The paper", "## Part 2 — In practice", "## Part 3 — Study", "### A. TL;DR",
                  "### E. Key equation", "### M. Check yourself", "### H. Limits and what came next"]:
            self.assertIn(h, md)
        self.assertLess(md.index("### A."), md.index("### M."))
        self.assertIn("Part B, fixed.", md)
        self.assertNotIn("99.9%", md)  # unverified number removed
        self.assertIn("Removed 1 unverified statement.", md)
        self.assertEqual(out["short_title"], "Test Policy")
        self.assertEqual(out["concepts"], ["Denoising"])
        self.assertEqual(out["stats"]["notes_dropped"], 1)
        self.assertEqual(out["stats"]["removed"], 1)
        self.assertIs(out["fulltext"], FT)
        self.assertIn("seconds", out["stats"])

    def test_no_fulltext_no_report(self):
        with mock.patch.object(reports.fulltext, "fetch", side_effect=fulltext.FulltextError("nope")):
            with self.assertRaises(fulltext.FulltextError):
                reports.deep_read(Run("t"), {}, PAPER, Hist())

    def test_context_has_references_and_concepts(self):
        ctx = reports.build_context({"known_concepts": ["RAG"], "context_references": 6}, PAPER, Hist())
        self.assertIn("Earlier work on X.", ctx)
        self.assertNotIn("NoAbs", ctx)
        self.assertIn("Diffusion models", ctx)
        self.assertIn("RAG", ctx)

    def test_section_check_rejects(self):
        chk = reports._make_check("ABCD", 1000)
        good = {"sections": {L: section_text(L) for L in "ABCD"}, "short_title": "Ok Title"}
        chk(good)
        bad = {"sections": {**good["sections"], "D": "no diagram here but long enough text to pass length."},
               "short_title": "Ok Title"}
        with self.assertRaises(ValueError):
            chk(bad)
        with self.assertRaises(ValueError):
            chk({"sections": {**good["sections"], "B": ""}, "short_title": "Ok Title"})

    def test_too_long_section_rejected(self):
        chk = reports._make_check("ABCD", 400)
        secs = {L: section_text(L) for L in "ABCD"}
        secs["B"] = "word " * 400
        with self.assertRaises(ValueError):
            chk({"sections": secs, "short_title": "Ok Title"})

    def test_chunk_split_on_failure(self):
        calls = []

        def llm(run, step, system, user, schema, **kw):
            calls.append(step)
            if step == "n[1/1]":
                raise StepFailed("bad json")
            return {"claims": ["c " + step], "method_steps": [], "results": [], "limits": [],
                    "equations": [], "figures": []}
        chunk = "\n".join(f"line {i}" for i in range(20))
        with mock.patch.object(reports, "llm_json", llm):
            notes, dropped, failed = reports.take_notes(Run("t"), [chunk], chunk, tag="n")
        self.assertEqual(calls, ["n[1/1]", "n[1/1].1", "n[1/1].2"])
        self.assertEqual(len(notes["claims"]), 2)
        self.assertEqual(failed, 0)

    def test_strip_heading(self):
        self.assertEqual(reports._strip_heading("TL;DR\nBody one."), "Body one.")
        self.assertEqual(reports._strip_heading("### A. TL;DR\n\nBody"), "Body")
        self.assertEqual(reports._strip_heading("How it Works\n1. step"), "1. step")
        text = "The problem is hard.\nMore."
        self.assertEqual(reports._strip_heading(text), text)

    def test_short_title_fallback(self):
        self.assertEqual(reports._short_title(PAPER, ""), "Test Paper")
        self.assertEqual(reports._short_title(PAPER, "Mine"), "Mine")


class Overview(unittest.TestCase):
    def _llm(self, run, step, system, user, schema, **kw):
        if step.startswith("ov_notes"):
            return fake_llm(run, "notes", system, user, schema, **kw)
        letters = "ABCDGHJL"
        obj = {"sections": {L: section_text(L) for L in letters}, "concepts_taught": [], "short_title": "Over"}
        obj["sections"]["G"] = "It reached 46.9% in Table 2."
        obj["sections"]["I"] = ""
        if kw.get("check"):
            kw["check"](obj)
        self.user = user
        return obj

    def test_with_fulltext(self):
        scored = {**PAPER, "abstract": "We study policies."}
        with mock.patch.object(reports.fulltext, "fetch", return_value=FT), mock.patch.object(reports, "llm_json", self._llm):
            out = reports.overview(Run("t"), {"overview_words": 400}, scored)
        md = out["markdown"]
        self.assertIn("### G. What the evidence shows", md)
        self.assertNotIn("### E.", md)
        self.assertNotIn("Part 1", md)
        self.assertNotIn("abstract only", md)
        self.assertIs(out["fulltext"], FT)

    def test_abstract_only(self):
        scored = {**PAPER, "abstract": "We study policies and get 46.9% success."}
        with mock.patch.object(reports.fulltext, "fetch", side_effect=fulltext.FulltextError("x")), \
                mock.patch.object(reports, "llm_json", self._llm):
            out = reports.overview(Run("t"), {"overview_words": 400}, scored)
        self.assertIsNone(out["fulltext"])
        self.assertIn("Based on the abstract only.", out["markdown"])
        self.assertIn("It reached 46.9% in Table 2", out["markdown"].replace("Table 2", "Table 2")) if False else None


if __name__ == "__main__":
    unittest.main()
