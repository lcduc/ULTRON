"""Run: python3 skills/planner/tests/test_plan.py   (stdlib unittest)"""
import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plan  # noqa: E402


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        plan.ROOT = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def run_cmd(self, *argv):
        buf = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buf):
            try:
                plan.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, buf.getvalue()

    def new(self):
        return self.run_cmd('new', 'My Task', '--goal', 'g', '--step', 'a || A ok', '--step', 'b || B ok', '--step', 'c')

    def test_new_and_files(self):
        code, out = self.new()
        self.assertEqual(code, 0)
        self.assertIn('Next: step 1', out)
        d = os.path.join(self.tmp.name, 'my-task')
        self.assertTrue(os.path.exists(os.path.join(d, 'plan.json')))
        with open(os.path.join(d, 'PLAN.md'), encoding='utf-8') as f:
            self.assertIn('done when: A ok', f.read())

    def test_too_many_steps(self):
        args = ['new', 'x', '--goal', 'g']
        for i in range(7):
            args += ['--step', str(i)]
        code, out = self.run_cmd(*args)
        self.assertEqual(code, 1)
        self.assertIn('at most 6', out)

    def test_default_pointer_and_done(self):
        self.new()
        self.run_cmd('start', '1')
        code, out = self.run_cmd('done', '1', '--note', 'file x')
        self.assertIn('[x] 1.', out)
        self.assertIn('Next: step 2', out)
        self.assertIn('-> file x', self.run_cmd('show')[1])

    def test_fail_limit_then_replan(self):
        self.new()
        self.assertNotIn('LIMIT', self.run_cmd('fail', '1', '--error', 'e1')[1])
        self.assertNotIn('LIMIT', self.run_cmd('fail', '1', '--error', 'e2')[1])
        self.assertIn('LIMIT: replan or stop', self.run_cmd('fail', '1', '--error', 'e3')[1])

    def test_replan_keeps_done_and_caps(self):
        self.new()
        self.run_cmd('done', '1')
        out = self.run_cmd('replan', '--reason', 'r1', '--step', 'd || D ok')[1]
        self.assertIn('[x] 1.', out)
        self.assertIn('Replan 1: r1', out)
        self.assertNotIn('2. b', out)
        self.assertIn('2. d', out)
        self.run_cmd('replan', '--reason', 'r2', '--step', 'e')
        out = self.run_cmd('replan', '--reason', 'r3', '--step', 'f')[1]
        self.assertIn('LIMIT: stop and report', out)

    def test_fail_after_replans_exhausted(self):
        self.new()
        self.run_cmd('replan', '--reason', 'r1', '--step', 'x')
        self.run_cmd('replan', '--reason', 'r2', '--step', 'y')
        out = ''
        for _ in range(3):
            out = self.run_cmd('fail', '1', '--error', 'e')[1]
        self.assertIn('LIMIT: stop and report', out)

    def test_report(self):
        self.new()
        self.run_cmd('done', '1', '--note', 'ok')
        self.run_cmd('fail', '2', '--error', 'boom')
        out = self.run_cmd('report')[1]
        self.assertIn('1 of 3 steps done', out)
        self.assertIn('last error: boom', out)

    def test_bad_step_and_no_plan(self):
        self.assertEqual(self.run_cmd('show')[0], 1)
        self.new()
        self.assertEqual(self.run_cmd('done', '9')[0], 1)

    def test_overwrite_protection(self):
        self.new()
        self.assertEqual(self.new()[0], 1)

    def test_task_flag(self):
        self.new()
        self.run_cmd('new', 'other', '--goal', 'h', '--step', 'z')
        self.assertIn('PLAN my-task', self.run_cmd('--task', 'my-task', 'show')[1])


if __name__ == '__main__':
    unittest.main()
