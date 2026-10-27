"""Check the browser side: launch, navigate, recycle the tab, close."""

import shutil
import tempfile

from vch.browser import BrowserSide

COLLECTIONS_URL = (
    "https://www.nexusmods.com/games/skyrimspecialedition/collections"
)


def main() -> None:
    profile = tempfile.mkdtemp(prefix="vch-smoke-")
    print("profile:", profile)
    try:
        with BrowserSide(profile, "msedge", print) as browser:
            print("starting browser (visible window)...")
            print("pages:", len(browser.ctx.pages))
            browser.page.goto(COLLECTIONS_URL, wait_until="domcontentloaded")
            title = browser.page.title() or ""
            print("title:", title[:70])
            assert title, "page title is empty - navigation did not work"
            browser.recycle()
            print("recycled, pages:", len(browser.ctx.pages))
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    print("closed cleanly")


if __name__ == "__main__":
    main()
