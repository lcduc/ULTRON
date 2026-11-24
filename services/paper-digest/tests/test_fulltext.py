import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fulltext  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
HTML = (FIX / "ft_paper.html").read_text(encoding="utf-8")


class Resp:
    def __init__(self, status=200, text="", content=b""):
        self.status_code, self.text, self.content = status, text, content


def make_pdf(lines: list[str]) -> bytes:
    """A tiny one-page PDF with the lines as text (enough for pypdf)."""
    stream = "BT /F1 10 Tf 12 TL 40 760 Td " + " ".join(
        f"({ln.replace('(', '[').replace(')', ']')}) Tj T*" for ln in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()
    return out


class ParseHtml(unittest.TestCase):
    def setUp(self):
        self.secs = fulltext.parse_html(HTML)
        self.by = {s["title"]: s["text"] for s in self.secs}

    def test_titles_and_order(self):
        titles = [s["title"] for s in self.secs]
        self.assertEqual(titles[0], "Abstract")
        self.assertIn("1 Introduction", titles)
        self.assertIn("4 Experiments", titles)
        self.assertNotIn("References", titles)

    def test_math_alttext_kept(self):
        txt = self.by["3 Method"]
        self.assertIn("$x_{t-1}=x_t-\\epsilon$", txt)
        self.assertIn("$L=\\|\\epsilon-\\epsilon_\\theta\\|^2$", txt)
        self.assertIn("(3)", txt)
        self.assertNotIn("application/x-tex", txt)

    def test_subsection_title_kept(self):
        self.assertIn("3.1 Denoising", self.by["3 Method"])

    def test_table_and_caption(self):
        txt = self.by["4 Experiments"]
        self.assertIn("Table 2: Success rate on the benchmark.", txt)
        self.assertIn("Ours | 46.9", txt)
        self.assertIn("Baseline | 31.2", txt)

    def test_bibliography_removed(self):
        self.assertNotIn("Smith 2020", " ".join(self.by.values()))

    def test_appendix_titles_only(self):
        key = [t for t in self.by if "Hyperparameters" in t][0]
        self.assertIn("A.1 Seeds", self.by[key])
        self.assertNotIn("learning rate", self.by[key])


class Fetch(unittest.TestCase):
    def setUp(self):
        self.p = {"id": "arxiv:2501.00001", "arxiv_id": "2501.00001", "pdf_url": "https://arxiv.org/pdf/2501.00001",
                  "html_url": "https://arxiv.org/html/2501.00001"}
        patcher = mock.patch.object(fulltext, "MIN_WORDS", 20)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _get(self, html_status=200, pdf=b"%PDF-1.4 x"):
        def get(url, headers=None, timeout=None):
            if "/html/" in url:
                return Resp(html_status, HTML)
            return Resp(200, "", pdf)
        return get

    def test_html_and_pdf_bytes(self):
        with mock.patch.object(fulltext.requests, "get", self._get()):
            ft = fulltext.fetch(self.p)
        self.assertEqual(ft["source"], "html")
        self.assertTrue(ft["pdf_bytes"].startswith(b"%PDF"))
        self.assertIn("## 4 Experiments", ft["text"])

    def test_html_404_falls_back_to_pdf(self):
        lines = (["Abstract", "We study things."] + ["1 Introduction", "Robots need policies."]
                 + ["Some words here to fill the page for the length check."] * 3
                 + ["4 Experiments", "Success was 40 percent on all tasks in the test set."]
                 + ["References", "[1] Smith 2020."])
        pdf = make_pdf(lines)
        with mock.patch.object(fulltext.requests, "get", self._get(404, pdf)):
            ft = fulltext.fetch(self.p)
        self.assertEqual(ft["source"], "pdf")
        titles = [s["title"] for s in ft["sections"]]
        self.assertIn("4 Experiments", titles)
        self.assertNotIn("Smith", ft["text"])

    def test_too_short_raises(self):
        with mock.patch.object(fulltext, "MIN_WORDS", 5000), \
                mock.patch.object(fulltext.requests, "get", self._get(200, b"junk")):
            with self.assertRaises(fulltext.FulltextError) as cm:
                fulltext.fetch(self.p)
        self.assertIn("words", str(cm.exception))

    def test_nothing_available(self):
        with mock.patch.object(fulltext.requests, "get", lambda *a, **k: Resp(404)):
            with self.assertRaises(fulltext.FulltextError) as cm:
                fulltext.fetch(self.p)
        self.assertIn("not available", str(cm.exception))

    def test_missing_experiments_section(self):
        html = HTML.replace("Experiments", "Discussion")
        with mock.patch.object(fulltext.requests, "get",
                               lambda url, **k: Resp(200, html) if "/html/" in url else Resp(404)):
            with self.assertRaises(fulltext.FulltextError) as cm:
                fulltext.fetch(self.p)
        self.assertIn("experiments", str(cm.exception))


class Chunks(unittest.TestCase):
    def test_split_on_sections(self):
        ft = {"sections": [{"title": f"S{i}", "text": "word " * 400} for i in range(6)]}
        out = fulltext.chunks(ft, 1000)  # ~3500 chars
        self.assertGreater(len(out), 1)
        self.assertTrue(all(len(c) <= 3500 + 50 for c in out))
        self.assertTrue(out[0].startswith("## S0"))
        self.assertIn("## S5", out[-1])

    def test_long_section_split_on_lines(self):
        ft = {"sections": [{"title": "Big", "text": "\n".join(f"line {i} " + "x" * 60 for i in range(200))}]}
        out = fulltext.chunks(ft, 500)
        self.assertGreater(len(out), 3)
        self.assertTrue(all(len(c) <= 500 * 3.5 + 80 for c in out))
        joined = "\n".join(out)
        self.assertIn("line 199", joined)
        self.assertIn("line 0 ", joined)


if __name__ == "__main__":
    unittest.main()
