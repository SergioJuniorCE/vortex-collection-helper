"""Playwright side: one reusable tab on a persistent Edge profile."""

import os
import time
from enum import Enum
from threading import Event
from typing import Callable, Optional

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from .models import DownloadStatus
from .util import Stopped, wait_until

LOGIN_URL = "https://www.nexusmods.com/users/myaccount"
LOGIN_SETTLE_TIMEOUT = 20
LOGIN_POLL_INTERVAL = 0.5
LOGIN_RECHECK_INTERVAL = 3
DEFAULT_PAGE_TIMEOUT = 30000


class NavResult(Enum):
    OK = "ok"
    ABORTED = "aborted"
    FAILED = "failed"


def _rate_limited(text: str) -> bool:
    lowered = text.lower()
    return "download limit" in lowered or "try again in" in lowered


class BrowserSide:
    """Owns one tab, reused and recycled.

    Use as a context manager so the Playwright driver and the browser are
    closed even when startup or a long run fails.
    """

    def __init__(
        self,
        profile: str,
        channel: str,
        log: Callable[[str], None],
        stop: Optional[Event] = None,
        confirm: Optional[Callable[[str], bool]] = None,
    ):
        self.profile = profile
        self.channel = channel
        self.log = log
        self.stop = stop
        self.confirm = confirm
        self._pw = None
        self.ctx = None
        self.page = None

    def _should_stop(self) -> bool:
        return self.stop is not None and self.stop.is_set()

    def __enter__(self) -> "BrowserSide":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False

    def start(self) -> None:
        self._pw = sync_playwright().start()
        os.makedirs(self.profile, exist_ok=True)
        try:
            self.ctx = self._pw.chromium.launch_persistent_context(
                self.profile,
                channel=self.channel,
                headless=False,
                no_viewport=True,
                # Playwright appends --no-sandbox unless you ask for the
                # sandbox, which makes Edge show a warning bar.
                chromium_sandbox=True,
                args=[
                    # Keeps navigator.webdriver false; without it the browser
                    # announces itself and Nexus's login captcha fails.
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-features=Translate",
                ],
            )
        except Exception as exc:
            message = str(exc)
            self.close()
            if "existing browser session" in message or "already in use" in message:
                raise RuntimeError(
                    "the browser profile\n    %s\nis already open - another run "
                    "or browser window is using it.\nClose it and start again."
                    % self.profile
                )
            raise
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.set_default_timeout(DEFAULT_PAGE_TIMEOUT)

    def recycle(self) -> None:
        """Swap in a fresh tab (memory hygiene).

        The replacement is opened first: closing the only tab of a persistent
        context can take the whole browser down with it.
        """
        try:
            fresh = self.ctx.new_page()
        except Exception:
            self._revive()
            return
        old = self.page
        self.page = fresh
        self.page.set_default_timeout(DEFAULT_PAGE_TIMEOUT)
        try:
            old.close()
        except Exception:
            pass

    def _revive(self) -> None:
        """Make sure there is a usable tab; rebuild the browser if needed."""
        if self.page is not None:
            try:
                if not self.page.is_closed():
                    return
            except Exception:
                pass
        try:
            pages = [page for page in self.ctx.pages if not page.is_closed()]
            if pages:
                self.page = pages[-1]
                self.page.set_default_timeout(DEFAULT_PAGE_TIMEOUT)
                self.log("browser: reattached to an open tab")
                return
            self.page = self.ctx.new_page()
            self.page.set_default_timeout(DEFAULT_PAGE_TIMEOUT)
            self.log("browser: opened a fresh tab")
            return
        except Exception:
            pass
        self.log("browser: window/tab was lost - restarting the browser")
        self.close()
        time.sleep(2)
        self.start()
        self.log("browser: restarted")

    def _login_state(self) -> Optional[bool]:
        """True = signed in, False = signed out, None = undecided.

        Nexus leaves a signed-out visitor on /users/myaccount instead of
        always redirecting, so the URL proves nothing. The header does:
        signed out shows a "Log in" link, signed in shows an avatar.
        """
        try:
            if self.page.locator('input[type="password"]').count():
                return False
            if self.page.locator('a[href*="sign_in"]').count():
                return False
            body = self.page.inner_text("body")
            if not body.strip():
                return None
            if "Log in" in body:
                return False
            return True
        except Exception:
            return None

    def _open_login_page(self) -> None:
        self._revive()
        try:
            self.page.goto(LOGIN_URL, wait_until="domcontentloaded")
        except Exception:
            pass

    def ensure_login(self) -> None:
        if self._should_stop():
            raise Stopped()
        self._open_login_page()

        def settled():
            state = self._login_state()
            return (state,) if state is not None else None

        decision = wait_until(
            settled,
            timeout=LOGIN_SETTLE_TIMEOUT,
            interval=LOGIN_POLL_INTERVAL,
            should_stop=self._should_stop,
        )
        state = decision[0] if decision else None

        if state is False:
            self.log("")
            self.log("  *** Log in to Nexus Mods in the browser window that just opened. ***")
            self.log("  You only have to do this once per profile; solve any captcha normally.")
            self.log("  The script carries on by itself the moment you are in.")
            wait_until(
                self._signed_in,
                timeout=None,
                interval=LOGIN_RECHECK_INTERVAL,
                should_stop=self._should_stop,
            )
        elif state is None:
            self.log("  could not tell whether you are logged in - check the browser window")
            message = (
                "Could not tell whether you are logged in. Check the browser "
                "window, then choose OK."
            )
            if self.confirm is not None:
                if not self.confirm(message):
                    raise Stopped()
            else:
                self.log("  Press Enter here when you can see your account page.")
                input()
        self.log("browser: logged in")

    def _signed_in(self) -> bool:
        if self.page is None:
            self._reopen_login_page()
            return False
        try:
            if self.page.is_closed():
                self._reopen_login_page()
                return False
        except Exception:
            self._reopen_login_page()
            return False
        return self._login_state() is True

    def _reopen_login_page(self) -> None:
        self.log("  the browser window went away - reopening it")
        self._open_login_page()

    def _page_text(self) -> str:
        try:
            return self.page.inner_text("body")[:4000]
        except Exception:
            return ""

    def _goto(self, url: str) -> NavResult:
        """Navigate to a mod page. Never raises: one hiccup must not kill a run.

        ERR_ABORTED is expected here - Chromium reports it when the page hands
        off to an external protocol or starts a download instead of rendering.
        """
        for attempt in (1, 2):
            try:
                self.page.goto(url, wait_until="domcontentloaded")
                return NavResult.OK
            except Exception as exc:
                first_line = str(exc).splitlines()[0]
                if "ERR_ABORTED" in first_line:
                    self.log("  navigation cancelled by the browser (handoff/download)")
                    return NavResult.ABORTED
                if attempt == 1:
                    self.log("  navigation failed (%s) - retrying once" % first_line[:70])
                    time.sleep(3)
                    continue
                self.log("  navigation failed twice (%s)" % first_line[:70])
                return NavResult.FAILED
        return NavResult.FAILED

    def do_download(self, url: str) -> DownloadStatus:
        """Open the mod page and click the free-tier 'Slow download' button."""
        self._revive()
        nav = self._goto(url)
        if nav is NavResult.FAILED:
            return DownloadStatus.NAV_FAILED
        time.sleep(2.5)

        if "sign_in" in self.page.url:
            return DownloadStatus.LOGIN

        title = self.page.title() or ""
        if "Just a moment" in title or "Attention Required" in title:
            return DownloadStatus.CHALLENGE

        try:
            button = self.page.locator('button:has-text("Slow download")').first
            button.wait_for(
                state="visible", timeout=25000 if nav is NavResult.OK else 9000
            )
        except PWTimeout:
            if nav is NavResult.ABORTED:
                # Chromium cancels a navigation both when the page hands the mod
                # to the nxm:// handler AND when the page never rendered. The
                # caller checks Vortex's log to find out which.
                self.log("  page cancelled the navigation - checking whether Vortex got it")
                return DownloadStatus.UNCERTAIN
            text = self._page_text()
            if _rate_limited(text):
                return DownloadStatus.RATE_LIMITED
            if "Just a moment" in (self.page.title() or ""):
                return DownloadStatus.CHALLENGE
            return DownloadStatus.NO_BUTTON

        button.click()  # real, trusted click - required for the nxm:// launch
        time.sleep(2)

        if _rate_limited(self._page_text()):
            return DownloadStatus.RATE_LIMITED
        return DownloadStatus.OK

    def close(self) -> None:
        had_browser = self.ctx is not None
        try:
            if self.ctx is not None:
                self.ctx.close()
        except Exception:
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        self.ctx = None
        self._pw = None
        self.page = None
        if had_browser:
            self.log("browser closed")
