import unittest

from vch.util import Stopped, wait_until


class WaitUntilTests(unittest.TestCase):
    def test_returns_truthy_value(self):
        self.assertEqual(wait_until(lambda: "ok", timeout=1), "ok")

    def test_timeout_returns_none(self):
        self.assertIsNone(wait_until(lambda: None, timeout=0.05, interval=0.01))

    def test_tick_runs_after_failed_probes(self):
        ticks = []
        wait_until(lambda: None, timeout=0.05, interval=0.01, on_tick=ticks.append)
        self.assertTrue(ticks)
        self.assertIsInstance(ticks[0], float)

    def test_stop_raises_immediately(self):
        with self.assertRaises(Stopped):
            wait_until(
                lambda: None,
                timeout=None,
                interval=0.01,
                should_stop=lambda: True,
            )


if __name__ == "__main__":
    unittest.main()
