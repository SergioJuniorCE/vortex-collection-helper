"""The mod loop: one prompt in, one outcome out.

All failure policy lives here. The loop itself only tallies outcomes and
decides whether the run is over, so there is exactly one place where a mod is
counted, skipped, retried, or allowed to stop the run.
"""

import time
import traceback
from dataclasses import dataclass
from threading import Event
from typing import Callable, Dict, Optional, Set, Tuple, Union

from .handoff import LogMark, VortexLog
from .models import (
    ClickResult,
    DownloadStatus,
    ModKey,
    Outcome,
    Prompt,
    Result,
)
from .util import Stopped, wait_until

PROMPT_SETTLE_SECONDS = 20
PROMPT_GONE_SECONDS = 20
ASSUME_LANDED_SECONDS = 120
INSTALL_POLL_SECONDS = 3
INSTALL_NUDGE_FIRST = 45
INSTALL_NUDGE_FOUND = 5
INSTALL_NUDGE_IDLE = 20
REPORT_EVERY = 60
URL_CAPTURE_TRIES = 15
SAME_MOD_ATTEMPTS = 5
DUP_SKIP_ATTEMPTS = 3
RATE_LIMIT_WAIT = 300
HANDOFF_GRACE = 30

_IDLE = object()
_Identity = Union[ModKey, Tuple[str, Optional[int]]]


@dataclass(frozen=True)
class RunOptions:
    idle_exit: int = 180
    download_timeout: int = 1800
    on_failure: str = "pause"
    once: bool = False
    recycle_every: int = 3


@dataclass(frozen=True)
class Progress:
    """A snapshot for a UI; the CLI ignores it."""

    completed: int = 0
    failed: int = 0
    skipped: int = 0
    index: Optional[int] = None
    total: Optional[int] = None
    name: Optional[str] = None


def _console_confirm(message: str) -> bool:
    try:
        answer = input("%s [Enter=yes, q=stop] " % message).strip().lower()
    except EOFError:
        return False
    return answer not in ("q", "quit", "exit", "n", "no")


class Runner:
    def __init__(
        self,
        bridge,
        browser,
        log: Callable[[str], None],
        options: RunOptions,
        vortex_log: Optional[VortexLog] = None,
        stop: Optional[Event] = None,
        confirm: Optional[Callable[[str], bool]] = None,
        on_progress: Optional[Callable[[Progress], None]] = None,
    ):
        self.bridge = bridge
        self.browser = browser
        self.log = log
        self.options = options
        self.vortex_log = vortex_log or VortexLog()
        self.stop = stop or Event()
        self.confirm = confirm or _console_confirm
        self.on_progress = on_progress or (lambda _progress: None)
        self.completed = 0
        self.failed = 0
        self.skipped = 0
        self._done_keys: Set[ModKey] = set()
        self._duplicate_tries: Dict[ModKey, int] = {}
        self._attempts: Dict[_Identity, int] = {}
        self._since_recycle = 0

    def run(self) -> None:
        started = time.monotonic()
        try:
            self.browser.ensure_login()
            while True:
                prompt = self._wait_for_prompt()
                if prompt is None:
                    self.log(
                        "no prompt for %ds - run looks finished"
                        % self.options.idle_exit
                    )
                    break
                self._emit_progress(prompt)

                try:
                    result = self._process(prompt)
                except Stopped:
                    raise
                except Exception:
                    # One bad mod must not end a long unattended run, but a bug
                    # must still be diagnosable - log the whole traceback.
                    self.log("  unexpected error while handling this mod:")
                    for line in traceback.format_exc().splitlines():
                        self.log("    " + line)
                    result = self._failure(prompt, None)
                self._tally(result.outcome)
                self._emit_progress()
                if result.stop:
                    break
                if self.options.once:
                    self.log("--once: stopping after one mod")
                    break
                if result.outcome is Outcome.INSTALLED:
                    self._since_recycle += 1
                    if self._since_recycle >= self.options.recycle_every:
                        self.log(
                            "  refreshing browser tab (every %d mods)"
                            % self.options.recycle_every
                        )
                        self.browser.recycle()
                        self._since_recycle = 0
        finally:
            self._summary(started)

    def _summary(self, started: float) -> None:
        minutes = (time.monotonic() - started) / 60.0
        self.log("-" * 68)
        self.log(
            "finished: %d completed, %d failed, %d skipped, %.1f min"
            % (self.completed, self.failed, self.skipped, minutes)
        )
        self._emit_progress()

    def _emit_progress(self, prompt: Optional[Prompt] = None) -> None:
        self.on_progress(
            Progress(
                completed=self.completed,
                failed=self.failed,
                skipped=self.skipped,
                index=prompt.index if prompt is not None else None,
                total=prompt.total if prompt is not None else None,
                name=prompt.mod_name if prompt is not None else None,
            )
        )

    def _pause(self, seconds: float) -> None:
        if self.stop.wait(seconds):
            raise Stopped()

    def _tally(self, outcome: Outcome) -> None:
        if outcome is Outcome.INSTALLED:
            self.completed += 1
        elif outcome is Outcome.SKIPPED:
            self.skipped += 1
        else:
            self.failed += 1

    def _wait_for_prompt(self) -> Optional[Prompt]:
        announced = False
        settle_started = None
        last_prompt_at = time.monotonic()

        def probe():
            nonlocal announced, settle_started, last_prompt_at

            try:
                prompt = self.bridge.prompt()
            except Stopped:
                raise
            except Exception as exc:
                self.log("vortex: reconnecting (%s)" % str(exc)[:80])
                prompt = Prompt()

            if prompt.has_prompt:
                last_prompt_at = time.monotonic()
                if prompt.index is not None:
                    return prompt
                settle_started = settle_started or time.monotonic()
                if time.monotonic() - settle_started >= PROMPT_SETTLE_SECONDS:
                    self.log("  prompt never filled in - using it as-is")
                    return prompt
                return None

            settle_started = None
            if not announced:
                self.log("waiting for Vortex's download prompt...")
                announced = True
            if (
                self.options.idle_exit > 0
                and time.monotonic() - last_prompt_at >= self.options.idle_exit
            ):
                return _IDLE
            return None

        result = wait_until(
            probe, timeout=None, interval=2, should_stop=self.stop.is_set
        )
        return None if result is _IDLE else result

    def _process(self, prompt: Prompt) -> Result:
        name = prompt.mod_name or "(unknown mod)"
        self.log("mod %s/%s: %s" % (prompt.index, prompt.total, name))
        if prompt.index is None:
            self.log("  prompt has no counter - completion relies on the log handoff")

        if not self.bridge.hook().usable:
            self.log("  Vortex's renderer API is no longer available - cannot continue")
            return Result(Outcome.FAILED, stop=True)

        self.bridge.take_urls()
        if not self.bridge.click_download_manually().clicked:
            self.log("  could not click 'Download manually' - retrying next cycle")
            self._pause(3)
            return self._failure(prompt, None)

        url = self._capture_url()
        if url is None:
            self.log("  Vortex gave no URL for this mod")
            return self._failure(prompt, None)

        key = ModKey.from_url(url)
        if key is None:
            self.log("  warning: Vortex's URL carries no file id")
            self.log("  completion for this mod can only use the 120s counter rule")
        elif key in self._done_keys:
            duplicate = self._handle_duplicate(key)
            if duplicate is not None:
                return duplicate

        mark = self.vortex_log.mark()
        started = time.monotonic()
        status = self._download(url, key, mark)
        if status is not DownloadStatus.OK:
            self.log("  browser failed for this mod (%s)" % status.value)
            self.log("  url: %s" % url)
            return self._failure(prompt, key)

        if not _InstallWatch(
            self.bridge,
            self.vortex_log,
            self.log,
            prompt,
            key,
            mark,
            self.options.download_timeout,
            self.stop,
        ).run():
            self.log(
                "  timed out waiting for Vortex after %ds"
                % self.options.download_timeout
            )
            # Five half-hour timeouts would strand the run for hours; a mod
            # that Vortex never finishes is skipped on the first timeout.
            return self._failure(prompt, key, final=True)

        if key is not None:
            self._done_keys.add(key)
        self.log(
            "  done in %ds (completed: %d)"
            % (int(time.monotonic() - started), self.completed + 1)
        )
        return Result(Outcome.INSTALLED)

    def _capture_url(self) -> Optional[str]:
        urls = []
        for _ in range(URL_CAPTURE_TRIES):
            urls = self.bridge.take_urls()
            if urls:
                break
            self._pause(1)
        if not urls:
            return None
        keyed = [url for url in urls if ModKey.from_url(url) is not None]
        return keyed[-1] if keyed else urls[-1]

    def _download(
        self, url: str, key: Optional[ModKey], mark: LogMark
    ) -> DownloadStatus:
        status = self.browser.do_download(url)

        if status is DownloadStatus.UNCERTAIN:
            # The page cancelled the navigation. Vortex's own log is the
            # authority on whether the handoff actually happened.
            status = (
                DownloadStatus.OK
                if self.vortex_log.wait_handoff(mark, key, HANDOFF_GRACE, self.log)
                else DownloadStatus.NO_BUTTON
            )

        if status is DownloadStatus.LOGIN:
            self.log("  session expired - log in again in the browser window")
            self.browser.ensure_login()
            status = self.browser.do_download(url)

        if status in (DownloadStatus.CHALLENGE, DownloadStatus.RATE_LIMITED):
            self.log(
                "  %s - waiting %ds before retrying"
                % (status.value, RATE_LIMIT_WAIT)
            )
            self._pause(RATE_LIMIT_WAIT)
            status = self.browser.do_download(url)

        return status

    def _handle_duplicate(self, key: ModKey) -> Optional[Result]:
        count = self._duplicate_tries.get(key, 0) + 1
        self._duplicate_tries[key] = count
        if count <= DUP_SKIP_ATTEMPTS:
            self.log("  already handled %s - not downloading it twice" % key)
            clicked = self._try_skip()
            if clicked is not None and clicked.clicked:
                self.log("  pressed 'Skip mod'")
                return Result(Outcome.SKIPPED)
            self._pause(2)
            return Result(Outcome.FAILED)
        self.log("  cannot get Vortex past %s - taking it again" % key)
        return None

    def _failure(
        self, prompt: Prompt, key: Optional[ModKey], final: bool = False
    ) -> Result:
        identity: _Identity = key if key is not None else ("index", prompt.index)
        count = self._attempts.get(identity, 0) + 1
        self._attempts[identity] = count
        label = str(key) if key is not None else "mod index %s" % prompt.index

        if final or count >= SAME_MOD_ATTEMPTS:
            if final:
                if not self._keep_going(
                    "Skip this timed-out mod and continue? "
                    "Choose Cancel to stop the run."
                ):
                    return Result(Outcome.FAILED, stop=True)
                self.log("  this mod did not finish - skipping it")
            else:
                self.log("  %d attempts on %s - pressing 'Skip mod'" % (count, label))
            self._attempts.pop(identity, None)
            clicked = self._try_skip()
            if clicked is not None and clicked.clicked:
                return Result(Outcome.SKIPPED)
            self.log("  could not press 'Skip mod' - stopping")
            return Result(Outcome.FAILED, stop=True)

        if not self._keep_going(
            "Retry this mod? Choose Cancel to stop the run."
        ):
            return Result(Outcome.FAILED, stop=True)
        return Result(Outcome.FAILED)

    def _try_skip(self) -> Optional[ClickResult]:
        try:
            return self.bridge.click_skip_mod()
        except Exception as exc:
            self.log("  could not press 'Skip mod' (%s)" % str(exc)[:80])
            return None

    def _keep_going(self, message: str) -> bool:
        if self.options.on_failure == "skip":
            self.log("  --on-failure skip: continuing")
            return True
        self.log("  Vortex's own 'Skip mod' button also works")
        return self.confirm(message)


class _InstallWatch:
    """Waits for Vortex to finish one mod, nudging FOMOD dialogs meanwhile."""

    def __init__(
        self,
        bridge,
        vortex_log: VortexLog,
        log: Callable[[str], None],
        prompt: Prompt,
        key: Optional[ModKey],
        mark: LogMark,
        timeout: float,
        stop: Event,
    ):
        self.bridge = bridge
        self.vortex_log = vortex_log
        self.log = log
        self.prompt = prompt
        self.key = key
        self.mark = mark
        self.timeout = timeout
        self.stop = stop
        self.moved_since = None
        self.absent_since = None
        self.next_nudge = INSTALL_NUDGE_FIRST
        self.next_report = REPORT_EVERY
        self.note = ""

    def run(self) -> bool:
        return bool(
            wait_until(
                self._probe,
                timeout=self.timeout,
                interval=INSTALL_POLL_SECONDS,
                on_tick=self._tick,
                should_stop=self.stop.is_set,
            )
        )

    def _probe(self) -> bool:
        try:
            prompt = self.bridge.prompt()
        except Stopped:
            raise
        except Exception:
            return False

        if not prompt.has_prompt:
            self.moved_since = None
            self.note = ""
            self.absent_since = self.absent_since or time.monotonic()
            return time.monotonic() - self.absent_since >= PROMPT_GONE_SECONDS

        self.absent_since = None
        if prompt.index is None:
            # A reloading dialog is unknown, not "moved on".
            self.moved_since = None
            self.note = ""
            return False
        if prompt.index == self.prompt.index:
            self.moved_since = None
            self.note = ""
            return False

        if self.key is not None and self.vortex_log.saw_handoff(self.mark, self.key):
            self.log("  Vortex received the download")
            return True

        self.moved_since = self.moved_since or time.monotonic()
        if time.monotonic() - self.moved_since >= ASSUME_LANDED_SECONDS:
            self.log(
                "  Vortex moved on but its log never showed the handoff"
                " - assuming it landed"
            )
            return True
        self.note = " (vortex moved on, no handoff in log yet)"
        return False

    def _tick(self, elapsed: float) -> None:
        if elapsed >= self.next_nudge:
            clicked: ClickResult = self.bridge.click_installer()
            if clicked.clicked:
                self.log("  mod installer dialog: %s" % clicked.label)
                self.next_nudge = elapsed + INSTALL_NUDGE_FOUND
            else:
                self.next_nudge = elapsed + INSTALL_NUDGE_IDLE
        if elapsed >= self.next_report:
            self.log("  still downloading/installing (%ds)%s" % (elapsed, self.note))
            self.next_report += REPORT_EVERY
