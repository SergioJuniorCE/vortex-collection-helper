# Vortex Collection Helper

Automates the **free-tier** Nexus Mods collection download loop in Vortex.

## The problem it solves

With a free Nexus account, Vortex cannot auto-download a collection. For every
single mod it stops and shows:

> Download mod *X* by *author* — 42/N
> [Download manually]   [Auto-download all (Premium)]

You click **Download manually**, a browser opens the mod page, you click
**Slow download**, wait a few seconds, Nexus hands an `nxm://` link to Vortex,
Vortex downloads and installs that one mod, then shows the same panel for the
next one. A collection of a few hundred mods means a few hundred of those
round trips.

This script does the round trips for you.

## How it works

| Half | Mechanism |
|---|---|
| Vortex | Chrome DevTools Protocol on `--remote-debugging-port=9222`. Clicks "Download manually" through the DOM and reads the prompt. |
| URL capture | Hooks `api.shell.openUrl` inside Vortex's renderer. The URL is kept, the call is swallowed - so **your own browser never opens**. |
| Browser | Playwright drives Edge on a persistent profile. The `Slow download` click must be a real input click; a JS `.click()` is not a trusted gesture and Chromium will not launch an external protocol. |
| Handoff | Nexus issues `nxm://...?key=...&expires=...&user_id=...`; Windows hands it to `Vortex.exe -d`. The script just waits. |
| Completion | Vortex's own log must show the handoff (`handling url .../mods/<id>/files/<fid>`), and only then may a prompt-index change count as "done". The counter alone is not trusted - see below. If the URL carries no `file_id`, there is nothing to match; that mod is logged loudly and can only use the 120s counter rule. |
| Identity | A mod is `(mod id, file id)`, never its name. Collections often contain the same mod several times with different files (base, patches, replacers). |
| Memory | One tab, recreated every N downloads (`--recycle-every`, default 3). The replacement is opened *before* the old tab closes - closing the last tab of a persistent context can take the whole browser down. |

## Project layout

| Path | Concern |
|---|---|
| `vortex_collection_helper.py` | thin entry point |
| `vch/cli.py` | argument parsing and wiring |
| `vch/session.py` | startup and wiring shared by the CLI and the UI |
| `vch/runner.py` | the mod loop, retries, and failure policy |
| `vch/ui.py` | Tkinter front end |
| `vch/vortex.py` | DevTools bridge and `openUrl` hook lifecycle |
| `vch/browser.py` | Playwright side |
| `vch/handoff.py` | `vortex.log` marks and handoff proof |
| `vch/models.py` | `ModKey`, `Prompt`, and the shared status types |
| `vch/js.py` | the JavaScript contract with Vortex |
| `vch/discovery.py` | finding and starting Vortex |
| `vch/util.py` | logger and the polling primitive |
| `pyproject.toml`, `uv.lock` | dependencies and the locked environment |
| `tests/` | dependency-free unit tests |

## Requirements

- Vortex. Its path is found automatically from the `nxm://` protocol handler,
  or pass `--vortex-exe`.
- [uv](https://docs.astral.sh/uv/). Run `uv sync` once; it creates `.venv` from
  `pyproject.toml` and the committed `uv.lock`.
- A one-time Nexus login in the browser profile the script uses.
- tkinter for the optional GUI (bundled with the Windows Python installer).

All commands below use `uv run`, so they always run in the project environment.
Activate `.venv\Scripts\activate` if you prefer plain `python`. For a pip-style
file, `uv export --format requirements-txt > requirements.txt` produces one.

## Run

```
uv run python vortex_collection_helper.py --once              # test: one mod, then stop
uv run python vortex_collection_helper.py                    # interactive on failure
uv run python vortex_collection_helper.py --on-failure skip   # fully unattended
uv run python vortex_collection_helper.py --restart-vortex    # force-close Vortex, relaunch with the port
uv run python vortex_collection_helper.py --help
```

`--restart-vortex` uses `taskkill /F`. Only use it when you are not in the
middle of an install; Vortex keeps its own progress, but a forced close is
still a forced close.

Then start the collection install in Vortex. The script waits for the first
prompt, and stops on its own when no prompt appears for `--idle-exit` seconds.

Already signed in somewhere? Point `--profile` at that Edge profile directory
(close that browser first - a profile can only be used by one process):

```
uv run python vortex_collection_helper.py --profile "%LOCALAPPDATA%\ms-playwright-mcp\mcp-msedge-xxxxxxxx"
```

## GUI

```
uv run python -m vch.ui
# or
uv run python vortex_collection_helper.py --ui
```

The window exposes the same options as the CLI, plus a live log, a progress bar
for the collection counter, running totals, and a real Stop button. The one-time
Nexus login still happens in the browser window; prompts that would block the
CLI ("retry this mod?") appear as dialogs instead. The session runs
on a worker thread, so the window stays responsive and closing it stops the run
and closes the browser. It writes the same `vortex_collection_helper.log`.

Use `uv run pythonw vortex_collection_helper.py --ui` if you want no console window.

## While it runs

- **Do not click around in Vortex.** No "Download manually", no "Skip mod", no
  browsing. The script drives those controls; you would fight it.
- `openUrl` stays hooked for the whole run, so Vortex cannot open your browser
  for anything else either. The hook is owned by the bridge and restored on
  every exit path, including Ctrl+C and startup failures.
- Everything is logged to `vortex_collection_helper.log` beside the script.
  That log contains live download keys - **do not commit or share it**.

## Failure modes it handles

Each of these was hit in real runs and is now handled.

### The dialog counter flickers

Vortex's "n/N" label re-renders mid-download, and it can move *before* the
download has reached Vortex. Trusting it caused a mod to be downloaded and
installed twice.

Now a mod only counts as finished when Vortex's log shows the real handoff.
If the prompt moves but no handoff ever appears, the script waits 120s, assumes
the download landed, and moves on - it does not sit there for half an hour.

### Vortex rewrites its own log

`vortex.log` is rewritten in place when it reaches about 5 MB. A byte offset
recorded before that points past end-of-file, so handoff detection would go
blind and the run would stall until the download timeout.

Each mark stores a 64-byte fingerprint of the bytes just before the offset.
The script notices the file shrank, was replaced by a fresh file, or was
rewritten in place with different bytes before the offset, and re-reads from
the start.

### The browser tab dies mid-run

The window can stay visible while the tab Playwright was driving is gone
(`Target page, context or browser has been closed`). Before every page load the
script checks the tab: it reattaches to an open tab, opens a fresh one, or
restarts the browser - then carries on.

### Mods that stop the queue

- **FOMOD installers** block the entire queue until a human presses Finish.
  After 45s idle the script clicks Finish/Install/Next inside
  `.fomod-nav-buttons` (scoped to the installer footer). Options keep their
  author defaults.
- **Duplicate collection entries** - the same `(mod id, file id)` twice - make
  the script press Vortex's own "Skip mod" instead of installing a duplicate.
  The seen-set is per run, never persisted, so a reinstall from scratch still
  downloads everything.
- **A mod that keeps failing** gets five attempts, then "Skip mod" so the run
  moves on instead of looping forever. A download that *times out* is skipped
  on the first occurrence - five half-hour timeouts would stall the run.

## Caveats

- **Free accounts are rate limited.** Long runs will likely hit Nexus's hourly
  download quota. The script waits 5 minutes and retries once, then pauses and
  asks. Starting it again later is safe - Vortex keeps its own progress, and the
  script resumes at whatever prompt is showing.
- Cloudflare challenges can appear; same wait-and-retry, then it pauses.
- The 3 MB/s free-tier throttle is yours to live with. A large collection is an
  overnight job.
- FOMOD defaults are applied without asking. If a mod's options matter to you
  (body type, texture resolution, patch variants), check it afterwards.
- This automates a step Nexus deliberately gates behind a manual click. Fine for
  your own account; expect throttling if you hammer it.
- Vortex's DevTools port (9222 by default) is unauthenticated and local. While
  it is open, any local process can drive Vortex. Close Vortex when the run is
  done if that matters to you.

## Verification

Checked against the live app:

- A complete unattended run over a 500+ mod collection: every prompt handled,
  no mod left undownloaded, clean exit with the `openUrl` hook restored.
- Vortex bridge (connect, hook, prompt, unhook) verified against the running app.
- Browser launch / navigate / recycle / close verified.
- Handoff detection verified against a real `vortex.log`: all URL forms parsed,
  matching key found, unrelated keys rejected, truncation recovery tested.
- Unit tests cover mod identity, file-id prefix rejection, log truncation and
  replacement, the polling primitive, cancellation, confirmation, and progress.
- Tkinter window construction and option parsing smoke-tested.

## dev/

Re-run these after a Vortex update to confirm the moving parts still line up.

```
uv run python -m dev.check_vortex_bridge    # attach, hook, read prompt, restore hook
uv run python -m dev.check_browser          # launch browser, navigate, recycle, close
```

## Tests

The identity, log-detection, outcome, cancellation, confirmation, and progress
rules have no third-party imports:

```
uv run python -m unittest discover -s tests -v
```

## License

MIT - see [LICENSE](LICENSE).
