import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import doc  # noqa: E402
import engine  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
REPORT = (FIX / "doc_report.md").read_text(encoding="utf-8")
PAPER = {"id": "arxiv:2511.0001", "arxiv_id": "2511.0001", "title": "Fast Decoding with Drafts",
         "authors": ["A One", "B Two", "C Three", "D Four"], "labs": ["NVIDIA"], "published": "2025-11-02",
         "url": "https://arxiv.org/abs/2511.0001", "digest_date": "2026-11-24"}
SAVING = "Saving the updated report to Drive; you'll get a push."


def chat(msgs):
    """Open WebUI shape: a history chain."""
    hist, prev = {}, None
    for i, (role, text) in enumerate(msgs):
        hist[f"m{i}"] = {"id": f"m{i}", "role": role, "content": text, "parentId": prev}
        prev = f"m{i}"
    return {"chat": {"history": {"messages": hist, "currentId": prev}}}


def docker_ok():
    try:
        return subprocess.run(["docker", "image", "inspect", "pandoc/core:3.5"], capture_output=True).returncode == 0
    except OSError:
        return False


class SplitTests(unittest.TestCase):
    def test_sections_in_order_and_parts_separate(self):
        ch = doc.split_report(REPORT)
        keys = [c["key"] for c in ch]
        self.assertEqual(keys, [None, "A", "B", "C", "D", "E", "F", "G", None, "I"])
        self.assertIn("```", [c for c in ch if c["key"] == "D"][0]["text"])
        self.assertEqual("\n".join(c["text"] for c in ch).count("Part 2"), 1)
        # a lettered line inside a code fence is not a section
        self.assertEqual([c["key"] for c in doc.split_report("A. **x**\n```\nB. y\n```\n")], ["A"])

    def test_follow_ups_skip_doc_noise(self):
        msgs = doc.chat_messages(chat([
            ("user", "Read it"), ("assistant", REPORT),
            ("user", "/eli5 acceptance"), ("assistant", "Like a coin flip."),
            ("user", "/doc"), ("assistant", SAVING),
            ("user", "why q over p?"), ("assistant", "Because of rejection sampling."),
            ("user", "/doc"), ("assistant", SAVING)]))
        self.assertEqual(doc.follow_ups(msgs), [("/eli5 acceptance", "Like a coin flip."),
                                                ("why q over p?", "Because of rejection sampling.")])

    def test_chat_flat_list_fallback(self):
        c = {"chat": {"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]}}
        self.assertEqual(len(doc.chat_messages(c)), 2)


class ImageTests(unittest.TestCase):
    def test_images_inserted_and_bad_equation_skipped(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib not installed")
        with tempfile.TemporaryDirectory() as t:
            out = doc.add_images(doc.split_report(REPORT), Path(t))
            text = "\n".join(c["text"] for c in out)
            self.assertIn("![Equation 1](eq_1.png)", text)
            self.assertIn("![Diagram 1](diagram_1.png)", text)
            self.assertIn("prompt -> draft model", text)  # the text diagram stays
            self.assertTrue((Path(t) / "eq_1.png").stat().st_size > 500)
            self.assertTrue((Path(t) / "diagram_1.png").stat().st_size > 500)
            bad = "\\begin{aligned} a &= b \\\\ c &= d \\end{aligned}"
            self.assertIsNone(doc.render_equation(bad, Path(t) / "x.png"))


class PandocTests(unittest.TestCase):
    def test_equation_is_native_omml(self):
        # Local pandoc when installed, else the pandoc/core:3.5 image through docker.
        if shutil.which("pandoc"):
            env = {}
        elif docker_ok():
            env = {"PANDOC_CMD": "docker run --rm -i pandoc/core:3.5"}
        else:
            self.skipTest("neither pandoc nor the docker image pandoc/core:3.5 is available")
        with mock.patch.dict(os.environ, env), tempfile.TemporaryDirectory() as t:
            data = doc.to_docx("# T\n\n$$ a^2 + b^2 = c^2 $$\n", Path(t))
        xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")
        self.assertIn("m:oMath", xml)

    def test_missing_pandoc_message(self):
        with mock.patch.dict(os.environ, {"PANDOC_CMD": "no-such-pandoc-xyz"}), tempfile.TemporaryDirectory() as t:
            with self.assertRaises(doc.DocError):
                doc.to_docx("x", Path(t))


class FakeHistory:
    def __init__(self, pid="arxiv:2511.0001"):
        self.pid = pid

    def paper_for_chat(self, chat_id):
        return self.pid

    def report(self, pid):
        return {"markdown": REPORT, "chat_id": "c1"}

    def get(self, pid):
        return dict(PAPER)


QAS = [("/eli5 acceptance", "A token is kept when the big model likes it at least as much as the draft."),
       ("why q over p?", "Not sure."),
       ("what is 99x?", "A made-up 99x speedup.")]
MAPPING = [{"qa": 1, "section": "E", "resolved": True, "open_question": ""},
           {"qa": 2, "section": "D", "resolved": False, "open_question": "Why is it q over p?"},
           {"qa": 3, "section": "G", "resolved": True, "open_question": ""}]


class MakeDocTests(unittest.TestCase):
    def run_make(self, mapping, rewrite, drive_on=True, history=None):
        run = engine.Run("doc-test")
        calls = []

        def fake_llm(run_, step, system, user, schema, **kw):
            calls.append(step)
            if step == "doc_map":
                return {"items": mapping}
            return rewrite(step, kw["check"])

        msgs = [("user", "go"), ("assistant", REPORT)] + [m for q, a in QAS for m in (("user", q), ("assistant", a))]
        ft = {"text": "The speedup is 2.5x on Table 1.", "sections": []}
        with mock.patch.object(doc.drive, "enabled", return_value=drive_on), \
                mock.patch.object(doc.common, "get_chat", return_value=chat(msgs)), \
                mock.patch.object(doc.fulltext, "fetch", return_value=ft), \
                mock.patch.object(doc.engine, "llm_json", side_effect=fake_llm), \
                mock.patch.object(doc, "to_docx", return_value=b"DOCX") as to_docx, \
                mock.patch.object(doc, "add_images", side_effect=lambda ch, d: ch), \
                mock.patch.object(doc.drive, "paper_folder", return_value=("fid", "furl")) as pf, \
                mock.patch.object(doc.drive, "upsert_doc", return_value="https://doc") as up:
            url = doc.make_doc(run, {"writer_model": "w", "timezone": "Asia/Ho_Chi_Minh"},
                               history or FakeHistory(), "c1")
        return url, calls, to_docx, pf, up

    def test_flow_rewrites_only_affected_and_keeps_original_on_bad_number(self):
        def rewrite(step, check):
            if step == "doc_rewrite_E":
                new = {"markdown": "E. **Key equation**\n\n$$ p $$\n\nClearer: kept when the big model agrees."}
                check(new)
                return new
            new = {"markdown": "G. **What the evidence shows** — 99x speedup."}
            with self.assertRaises(ValueError):  # 99x is not in the source
                check(new)
            raise engine.StepFailed("bad numbers")

        url, calls, to_docx, pf, up = self.run_make(MAPPING, rewrite)
        self.assertEqual(url, "https://doc")
        self.assertEqual(calls, ["doc_map", "doc_rewrite_E", "doc_rewrite_G"])
        md = to_docx.call_args[0][0]
        self.assertTrue(md.startswith("# Fast Decoding with Drafts"))
        self.assertIn("A One, B Two, C Three et al.", md)
        self.assertIn("Clearer: kept when", md)
        self.assertIn("2.5x speedup on summarisation (Table 1)", md)  # G kept as it was
        self.assertIn("- Why is it q over p?", md)
        self.assertIn("what is 99x? (answered in the chat, not merged", md)
        self.assertNotIn("A made-up 99x", md)
        self.assertEqual(up.call_args[0][1], "2025 - Fast Decoding with Drafts - Report")
        self.assertEqual(pf.call_args[0][2], "2026-11-24")

    def test_heading_check(self):
        def rewrite(step, check):
            with self.assertRaises(ValueError):
                check({"markdown": "Some text without the heading"})
            raise engine.StepFailed("x")

        self.run_make([{"qa": 1, "section": "E", "resolved": True, "open_question": ""}], rewrite)

    def test_drive_not_connected(self):
        with self.assertRaises(doc.DriveNotConnected):
            self.run_make([], None, drive_on=False)

    def test_not_a_deep_read_chat(self):
        with self.assertRaises(doc.DocError):
            self.run_make([], None, history=FakeHistory(pid=None))


if __name__ == "__main__":
    unittest.main()
