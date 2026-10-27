import threading
import unittest

from vch.handoff import LogMark
from vch.models import (
    ClickResult,
    DownloadStatus,
    HookState,
    ModKey,
    Outcome,
    Prompt,
)
from vch.runner import RunOptions, Runner
from vch.util import Stopped

URL = "nxm://skyrimspecialedition/mods/1/files/2?key=a"


class FakeBridge:
    def __init__(self, prompts, skip_clicked=True):
        self.prompts = list(prompts)
        self.skip_clicked = skip_clicked
        self.skip_calls = 0
        self._take_calls = 0

    def hook(self):
        return HookState.ALREADY

    def take_urls(self):
        self._take_calls += 1
        if self._take_calls == 1:
            return []  # the runner clears stale URLs before clicking
        return [URL]

    def click_download_manually(self):
        return ClickResult(True)

    def click_skip_mod(self):
        self.skip_calls += 1
        return ClickResult(self.skip_clicked)

    def click_installer(self):
        return ClickResult(False)

    def prompt(self):
        if self.prompts:
            return self.prompts.pop(0)
        return Prompt()


class FakeBrowser:
    def __init__(self, status=DownloadStatus.OK):
        self.status = status
        self.recycled = 0

    def ensure_login(self):
        pass

    def do_download(self, url):
        return self.status

    def recycle(self):
        self.recycled += 1


class FakeVortexLog:
    def __init__(self, handoff=True):
        self.handoff = handoff

    def mark(self):
        return LogMark(0, 0.0)

    def saw_handoff(self, mark, key):
        return self.handoff

    def wait_handoff(self, mark, key, seconds, log):
        return self.handoff


def make_runner(
    prompts,
    status=DownloadStatus.OK,
    once=True,
    skip_clicked=True,
    stop=None,
    confirm=None,
    on_progress=None,
    on_failure="skip",
):
    bridge = FakeBridge(prompts, skip_clicked=skip_clicked)
    browser = FakeBrowser(status)
    runner = Runner(
        bridge,
        browser,
        lambda _: None,
        RunOptions(once=once, on_failure=on_failure),
        vortex_log=FakeVortexLog(),
        stop=stop,
        confirm=confirm,
        on_progress=on_progress,
    )
    return runner, bridge, browser


class RunnerTests(unittest.TestCase):
    def test_once_installs_one_mod(self):
        runner, bridge, _ = make_runner(
            [
                Prompt(True, 1, 3, "First"),
                Prompt(True, 2, 3, "Second"),
                Prompt(True, 3, 3, "Third"),
            ]
        )
        runner.run()
        self.assertEqual(runner.completed, 1)
        self.assertEqual(runner.failed, 0)
        self.assertEqual(runner.skipped, 0)
        # The install watch consumes prompt 2 to see the counter move;
        # prompt 3 must survive because --once stops the run.
        self.assertEqual(len(bridge.prompts), 1, "a second mod was processed")

    def test_once_stops_after_a_failure(self):
        runner, bridge, _ = make_runner(
            [Prompt(True, 1, 3, "First"), Prompt(True, 2, 3, "Second")],
            status=DownloadStatus.NO_BUTTON,
        )
        runner.run()
        self.assertEqual(runner.failed, 1)
        self.assertEqual(runner.completed, 0)
        self.assertEqual(len(bridge.prompts), 1, "--once did not stop the run")

    def test_five_failures_press_skip_mod(self):
        bridge = FakeBridge([], skip_clicked=True)
        runner = Runner(
            bridge,
            FakeBrowser(DownloadStatus.NO_BUTTON),
            lambda _: None,
            RunOptions(on_failure="skip"),
            vortex_log=FakeVortexLog(),
        )
        prompt = Prompt(True, 1, 3, "First")
        results = [runner._failure(prompt, ModKey(1, 2)) for _ in range(5)]
        self.assertEqual(results[-1].outcome, Outcome.SKIPPED)
        self.assertEqual(bridge.skip_calls, 1)

    def test_timeout_skips_on_the_first_occurrence(self):
        bridge = FakeBridge([], skip_clicked=True)
        runner = Runner(
            bridge,
            FakeBrowser(),
            lambda _: None,
            RunOptions(on_failure="skip"),
            vortex_log=FakeVortexLog(),
        )
        result = runner._failure(Prompt(True, 1, 3, "First"), ModKey(1, 2), final=True)
        self.assertEqual(result.outcome, Outcome.SKIPPED)
        self.assertEqual(bridge.skip_calls, 1)

    def test_stop_raises_out_of_run(self):
        stop = threading.Event()
        stop.set()
        runner, _, _ = make_runner([Prompt(True, 1, 3, "First")], stop=stop)
        with self.assertRaises(Stopped):
            runner.run()

    def test_stop_interrupts_a_long_pause(self):
        stop = threading.Event()
        stop.set()
        runner, _, _ = make_runner([], stop=stop)
        with self.assertRaises(Stopped):
            runner._pause(60)

    def test_confirm_false_stops_the_run(self):
        runner, _, _ = make_runner(
            [], once=False, confirm=lambda _: False, on_failure="pause"
        )
        result = runner._failure(Prompt(True, 1, 3, "First"), ModKey(1, 2))
        self.assertTrue(result.stop)
        self.assertEqual(result.outcome, Outcome.FAILED)

    def test_progress_reports_the_completed_mod(self):
        seen = []
        runner, _, _ = make_runner(
            [
                Prompt(True, 1, 3, "First"),
                Prompt(True, 2, 3, "Second"),
            ],
            on_progress=seen.append,
        )
        runner.run()
        self.assertTrue(seen)
        self.assertEqual(seen[0].index, 1)
        self.assertEqual(seen[-1].completed, 1)
        self.assertEqual(seen[-1].failed, 0)

    def test_unclickable_skip_stops_the_run(self):
        bridge = FakeBridge([], skip_clicked=False)
        runner = Runner(
            bridge,
            FakeBrowser(DownloadStatus.NO_BUTTON),
            lambda _: None,
            RunOptions(on_failure="skip"),
            vortex_log=FakeVortexLog(),
        )
        prompt = Prompt(True, 1, 3, "First")
        for _ in range(4):
            runner._failure(prompt, ModKey(1, 2))
        result = runner._failure(prompt, ModKey(1, 2))
        self.assertTrue(result.stop)
        self.assertEqual(result.outcome, Outcome.FAILED)


if __name__ == "__main__":
    unittest.main()
