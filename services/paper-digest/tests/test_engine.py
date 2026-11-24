"""engine: cloud priority order, fallback along the chain, and the chat-model pick."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine  # noqa: E402

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
CFG = {"model": "ultron"}


class Base(unittest.TestCase):
    def setUp(self):
        engine._dead.clear()
        engine._chat_pick.clear()


class OrderTests(Base):
    def test_cloud_order_from_env(self):
        with mock.patch.dict(os.environ, {"CLOUD_PRIORITY": "Claude, gpt,claude, nonsense, google"}):
            self.assertEqual(engine.cloud_order(), ["cloud-claude", "cloud-gpt", "cloud-gemini"])

    def test_chain(self):
        with mock.patch.dict(os.environ, {"CLOUD_PRIORITY": "gpt,gemini"}):
            self.assertEqual(engine.model_chain("cloud", "ultron"), ["cloud-gpt", "cloud-gemini", "ultron"])
        self.assertEqual(engine.model_chain("cloud-claude", "ultron"), ["cloud-claude", "ultron"])
        self.assertEqual(engine.model_chain(None, "ultron"), ["ultron"])
        self.assertEqual(engine.model_chain("ultron", "ultron"), ["ultron"])


class FallbackTests(Base):
    def run_step(self, model, failing, env="gemini,claude,gpt"):
        calls = []

        def post(m, *a, **k):
            calls.append(m)
            if m in failing:
                raise RuntimeError("401 no key")
            return '{"x": 1}'

        run = engine.Run("t")
        with mock.patch.object(engine, "cfg", return_value=CFG), mock.patch.dict(os.environ, {"CLOUD_PRIORITY": env}), \
                mock.patch.object(engine, "_post", side_effect=post), mock.patch.object(engine.time, "sleep"):
            out = engine.llm_json(run, "s", "sys", "user", SCHEMA, model=model)
        return out, calls, run

    def test_single_cloud_failure_uses_local(self):
        out, calls, run = self.run_step("cloud-gemini", {"cloud-gemini"})
        self.assertEqual((out, calls), ({"x": 1}, ["cloud-gemini", "ultron"]))
        self.assertTrue(any(s["step"] == "s.fallback" for s in run.steps))

    def test_cloud_walks_priority(self):
        _, calls, _ = self.run_step("cloud", {"cloud-gemini"})
        self.assertEqual(calls, ["cloud-gemini", "cloud-claude"])

    def test_dead_model_skipped_next_time(self):
        self.run_step("cloud", {"cloud-gemini"})
        _, calls, _ = self.run_step("cloud", {"cloud-gemini"})
        self.assertEqual(calls, ["cloud-claude"])

    def test_all_cloud_fail_reaches_local(self):
        _, calls, _ = self.run_step("cloud", {"cloud-gemini", "cloud-claude", "cloud-gpt"})
        self.assertEqual(calls, ["cloud-gemini", "cloud-claude", "cloud-gpt", "ultron"])

    def test_local_failure_waits_and_retries(self):
        answers = [RuntimeError("busy"), '{"x": 2}']

        def post(m, *a, **k):
            v = answers.pop(0)
            if isinstance(v, Exception):
                raise v
            return v

        run = engine.Run("t")
        with mock.patch.object(engine, "cfg", return_value=CFG), \
                mock.patch.object(engine, "_post", side_effect=post), mock.patch.object(engine.time, "sleep") as sl:
            self.assertEqual(engine.llm_json(run, "s", "sys", "user", SCHEMA), {"x": 2})
        sl.assert_called_once_with(60)


class ChatPickTests(Base):
    def test_first_working_cloud(self):
        with mock.patch.object(engine, "cfg", return_value=CFG), \
                mock.patch.dict(os.environ, {"CLOUD_PRIORITY": "gemini,claude"}), \
                mock.patch.object(engine, "_probe", side_effect=lambda m: m == "cloud-claude") as pr:
            self.assertEqual(engine.pick_chat_model("cloud"), "cloud-claude")
            self.assertEqual(engine.pick_chat_model("cloud"), "cloud-claude")  # cached
        self.assertEqual(pr.call_count, 2)

    def test_none_working_gives_local(self):
        with mock.patch.object(engine, "cfg", return_value=CFG), \
                mock.patch.object(engine, "_probe", return_value=False):
            self.assertEqual(engine.pick_chat_model("cloud"), "ultron")


if __name__ == "__main__":
    unittest.main()
