"""engine.llm_json: a failing cloud model falls back to the local model at once."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine  # noqa: E402

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}


class FallbackTests(unittest.TestCase):
    def test_cloud_failure_uses_local(self):
        calls = []

        def post(model, *a, **k):
            calls.append(model)
            if model == "cloud-gemini":
                raise RuntimeError("401 no key")
            return '{"x": 1}'

        run = engine.Run("t")
        with mock.patch.object(engine, "cfg", return_value={"model": "ultron"}), \
                mock.patch.object(engine, "_post", side_effect=post), mock.patch.object(engine.time, "sleep"):
            out = engine.llm_json(run, "s", "sys", "user", SCHEMA, model="cloud-gemini")
        self.assertEqual(out, {"x": 1})
        self.assertEqual(calls, ["cloud-gemini", "ultron"])
        self.assertTrue(any(s["step"] == "s.fallback" for s in run.steps))

    def test_local_failure_waits_and_retries(self):
        answers = [RuntimeError("busy"), '{"x": 2}']

        def post(model, *a, **k):
            v = answers.pop(0)
            if isinstance(v, Exception):
                raise v
            return v

        run = engine.Run("t")
        with mock.patch.object(engine, "cfg", return_value={"model": "ultron"}), \
                mock.patch.object(engine, "_post", side_effect=post), mock.patch.object(engine.time, "sleep") as sl:
            out = engine.llm_json(run, "s", "sys", "user", SCHEMA)
        self.assertEqual(out, {"x": 2})
        sl.assert_called_once_with(60)


if __name__ == "__main__":
    unittest.main()
