import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import verify  # noqa: E402


class Numbers(unittest.TestCase):
    def test_normalised(self):
        self.assertEqual(verify.numbers_in("1,024 and 45 % and .5 and 12.30"), ["1024", "45%", "0.5", "12.3"])

    def test_units(self):
        self.assertEqual(verify.numbers_in("a 7B model, 3x faster, 2.5M params"), ["7B", "3x", "2.5M"])

    def test_ignored(self):
        text = ("1. First item\n2. Second item\nIn 2023 we saw it (see Section 3.2, Table 4, Fig. 5, Eq. (7)). "
                "Use step 3 with [12] and [3, 4]. The $x_{100}$ term and $$y=45.5$$.")
        self.assertEqual(verify.numbers_in(text), [])

    def test_big_year_like_number_kept(self):
        self.assertEqual(verify.numbers_in("We used 2500 demos and 11 tasks"), ["2500", "11"])

    def test_code_fence_skipped(self):
        self.assertEqual(verify.numbers_in("```\nA[256] -> B[512]\n```\nNo numbers."), [])

    def test_glued_to_letters_ignored(self):
        self.assertEqual(verify.numbers_in("ResNet18 and GPT4 and Qwen2.5-7B"), ["7B"])

    def test_dedupe_order(self):
        self.assertEqual(verify.numbers_in("45% then 45 % then 12"), ["45%", "12"])


class Unsupported(unittest.TestCase):
    SRC = "Success was 46.9% vs 31.2. We use 1,024 samples, a .5 threshold and 7 billion parameters (7B)."

    def test_supported_variants(self):
        self.assertEqual(verify.unsupported_numbers("46.9 % and 1024 and 0.5 and 7B", self.SRC), [])

    def test_unsupported(self):
        self.assertEqual(verify.unsupported_numbers("It got 47.2% and 1,024 and 99", self.SRC), ["47.2%", "99"])

    def test_trailing_zero(self):
        self.assertEqual(verify.unsupported_numbers("31.20 and 46.90%", self.SRC), [])

    def test_number_in_math_of_source(self):
        self.assertEqual(verify.unsupported_numbers("beta is 0.02", "we set $\\beta=0.02$ here"), [])

    def test_different_number_same_prefix(self):
        self.assertEqual(verify.unsupported_numbers("46.95%", self.SRC), ["46.95%"])


class Quotes(unittest.TestCase):
    SRC = ("Our method achieves a success rate of 46.9% on the benchmark, outperforming the strongest baseline "
           "by a wide margin. We attribute this to the multimodal action distribution it can represent.")

    def test_exact(self):
        self.assertTrue(verify.quote_ok("achieves a success rate of 46.9% on the benchmark", self.SRC))

    def test_normalised(self):
        self.assertTrue(verify.quote_ok("Achieves a SUCCESS rate of 46.9 % on the benchmark!", self.SRC))

    def test_fuzzy_missing_word(self):
        self.assertTrue(verify.quote_ok("achieves a success rate of 46.9% on benchmark outperforming the strongest baseline", self.SRC))

    def test_wrong(self):
        self.assertFalse(verify.quote_ok("achieves a success rate of 91.0% on the benchmark across every task", self.SRC))

    def test_out_of_order_fails(self):
        self.assertFalse(verify.quote_ok("action distribution multimodal the represent can it attribute we", self.SRC))

    def test_empty_and_short(self):
        self.assertFalse(verify.quote_ok("", self.SRC))
        self.assertFalse(verify.quote_ok("success wide", self.SRC))
        self.assertTrue(verify.quote_ok("success rate", self.SRC))


class Refs(unittest.TestCase):
    SECS = [
        {"title": "1 Introduction", "text": "We show in Table 1 and Figure 1 that it works."},
        {"title": "3 Method", "text": "3.1 Denoising\nSee Eq. (3).\n3.2 Training\nFigure 2: overview\n(3)"},
        {"title": "4 Experiments", "text": "Table 2: Success rates.\nFig. 4: curves"},
        {"title": "Appendix A Details", "text": "A.1 Seeds"},
    ]

    def test_good_refs(self):
        t = "See §3.2, Section 3, Table 2, Fig. 4, Figure 2, Eq. (3), Eq. 3 and Section 4. Also §A.1 and Table 1."
        self.assertEqual(verify.refs_ok(t, self.SECS), [])

    def test_bad_refs(self):
        t = "See §7, Section 3.5, Table 9, Fig. 12 and Eq. (40)."
        bad = verify.refs_ok(t, self.SECS)
        self.assertEqual(len(bad), 5)
        self.assertIn("Table 9", bad)

    def test_figure_suffix_and_plural(self):
        self.assertEqual(verify.refs_ok("Figure 4a shows it; Figs. 2", self.SECS), [])

    def test_text_as_string(self):
        self.assertEqual(verify.refs_ok("Table 2", "Table 2: results"), [])
        self.assertEqual(verify.refs_ok("Table 3", "Table 2: results"), ["Table 3"])

    def test_fence_ignored(self):
        self.assertEqual(verify.refs_ok("```\nFig. 99\n```", self.SECS), [])


if __name__ == "__main__":
    unittest.main()
