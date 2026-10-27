"""Tkinter front end for the collection helper.

All widgets live on the main thread. The session runs on one worker thread and
talks back through a single queue: log lines, progress snapshots, confirmation
requests, and the final result. Confirmation dialogs are shown on the main
thread while the worker waits on an Event.
"""

import os
import queue
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Optional

from .runner import Progress, RunOptions
from .session import SessionOptions, run_session
from .util import make_logger

WINDOW_TITLE = "Vortex Collection Helper"
POLL_MS = 100
LOG_NAME = "vortex_collection_helper.log"


def default_profile(here: str) -> str:
    return os.path.join(
        os.environ.get("LOCALAPPDATA", here),
        "vortex-collection-helper",
        "profile",
    )


class App:
    def __init__(self, root: tk.Tk, here: str):
        self.root = root
        self.here = here
        self.events = queue.Queue()
        self.log_path = os.path.join(here, LOG_NAME)
        self.file_log = make_logger(self.log_path, echo=False)
        self.stop_event = threading.Event()
        self.worker: Optional[threading.Thread] = None
        self.closing = False
        self.option_widgets = []
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(POLL_MS, self._drain)

    # ---- layout ---------------------------------------------------------

    def _build(self) -> None:
        self.root.title(WINDOW_TITLE)
        self.root.geometry("940x700")
        self.root.minsize(780, 600)

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        connection = ttk.LabelFrame(outer, text="Connection", padding=8)
        connection.pack(fill="x")
        connection.columnconfigure(1, weight=1)

        self.port_var = tk.StringVar(value="9222")
        self.vortex_var = tk.StringVar()
        self.profile_var = tk.StringVar(value=default_profile(self.here))
        self.channel_var = tk.StringVar(value="msedge")
        self.recycle_var = tk.StringVar(value="3")
        self.idle_var = tk.StringVar(value="180")
        self.timeout_var = tk.StringVar(value="1800")
        self.failure_var = tk.StringVar(value="pause")
        self.once_var = tk.BooleanVar(value=False)
        self.restart_var = tk.BooleanVar(value=False)

        ttk.Label(connection, text="Debug port").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=3
        )
        port = ttk.Entry(connection, textvariable=self.port_var, width=10)
        port.grid(row=0, column=1, sticky="w", pady=3)
        self.option_widgets.append((port, "normal"))

        ttk.Label(connection, text="Vortex.exe").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=3
        )
        vortex = ttk.Entry(connection, textvariable=self.vortex_var)
        vortex.grid(row=1, column=1, sticky="ew", pady=3)
        self.option_widgets.append((vortex, "normal"))
        browse_exe = ttk.Button(connection, text="Browse...", command=self._browse_exe)
        browse_exe.grid(row=1, column=2, padx=(6, 0), pady=3)
        self.option_widgets.append((browse_exe, "normal"))

        ttk.Label(connection, text="Profile").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=3
        )
        profile = ttk.Entry(connection, textvariable=self.profile_var)
        profile.grid(row=2, column=1, sticky="ew", pady=3)
        self.option_widgets.append((profile, "normal"))
        browse_profile = ttk.Button(
            connection, text="Browse...", command=self._browse_profile
        )
        browse_profile.grid(row=2, column=2, padx=(6, 0), pady=3)
        self.option_widgets.append((browse_profile, "normal"))

        ttk.Label(connection, text="Channel").grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=3
        )
        channel = ttk.Combobox(
            connection,
            textvariable=self.channel_var,
            values=["msedge", "chromium"],
            state="readonly",
            width=12,
        )
        channel.grid(row=3, column=1, sticky="w", pady=3)
        self.option_widgets.append((channel, "readonly"))

        run_frame = ttk.LabelFrame(outer, text="Run", padding=8)
        run_frame.pack(fill="x", pady=(8, 0))
        run_frame.columnconfigure(1, weight=1)
        run_frame.columnconfigure(3, weight=1)
        run_frame.columnconfigure(5, weight=1)

        ttk.Label(run_frame, text="Recycle every").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        recycle = ttk.Entry(run_frame, textvariable=self.recycle_var, width=8)
        recycle.grid(row=0, column=1, sticky="w", padx=(0, 16))
        self.option_widgets.append((recycle, "normal"))

        ttk.Label(run_frame, text="Idle exit (s)").grid(
            row=0, column=2, sticky="w", padx=(0, 6)
        )
        idle = ttk.Entry(run_frame, textvariable=self.idle_var, width=8)
        idle.grid(row=0, column=3, sticky="w", padx=(0, 16))
        self.option_widgets.append((idle, "normal"))

        ttk.Label(run_frame, text="Download timeout (s)").grid(
            row=0, column=4, sticky="w", padx=(0, 6)
        )
        timeout = ttk.Entry(run_frame, textvariable=self.timeout_var, width=8)
        timeout.grid(row=0, column=5, sticky="w")
        self.option_widgets.append((timeout, "normal"))

        ttk.Label(run_frame, text="On failure").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        failure = ttk.Combobox(
            run_frame,
            textvariable=self.failure_var,
            values=["pause", "skip"],
            state="readonly",
            width=10,
        )
        failure.grid(row=1, column=1, sticky="w", pady=(6, 0))
        self.option_widgets.append((failure, "readonly"))

        once = ttk.Checkbutton(
            run_frame, text="Single mod (--once)", variable=self.once_var
        )
        once.grid(row=1, column=2, columnspan=2, sticky="w", pady=(6, 0))
        self.option_widgets.append((once, "normal"))

        restart = ttk.Checkbutton(
            run_frame,
            text="Force-close Vortex (--restart-vortex)",
            variable=self.restart_var,
        )
        restart.grid(row=1, column=4, columnspan=2, sticky="w", pady=(6, 0))
        self.option_widgets.append((restart, "normal"))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(10, 6))
        self.start_button = ttk.Button(buttons, text="Start", command=self._start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            buttons, text="Stop", command=self._stop, state="disabled"
        )
        self.stop_button.pack(side="left", padx=6)
        ttk.Button(buttons, text="Open log", command=self._open_log).pack(side="right")

        status = ttk.Frame(outer)
        status.pack(fill="x")
        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        self.progress = ttk.Progressbar(status, mode="determinate", maximum=100)
        self.progress.pack(side="right", fill="x", expand=True, padx=(12, 0))

        log_frame = ttk.LabelFrame(outer, text="Log", padding=6)
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = ScrolledText(
            log_frame,
            height=18,
            state="disabled",
            wrap="word",
            font=("Consolas", 9),
        )
        self.log_text.pack(fill="both", expand=True)

    # ---- actions --------------------------------------------------------

    def _browse_exe(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Vortex.exe",
            filetypes=[
                ("Vortex", "Vortex.exe"),
                ("Executables", "*.exe"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.vortex_var.set(path)

    def _browse_profile(self) -> None:
        path = filedialog.askdirectory(title="Select the browser profile directory")
        if path:
            self.profile_var.set(path)

    def _open_log(self) -> None:
        try:
            os.startfile(self.log_path)
        except AttributeError:
            messagebox.showinfo(WINDOW_TITLE, self.log_path)
        except OSError as exc:
            messagebox.showerror(WINDOW_TITLE, "Could not open the log:\n%s" % exc)

    def _read_options(self) -> SessionOptions:
        try:
            port = int(self.port_var.get().strip())
            recycle = int(self.recycle_var.get().strip())
            idle = int(self.idle_var.get().strip())
            timeout = int(self.timeout_var.get().strip())
        except ValueError:
            raise ValueError("Port and timing fields must be whole numbers.")
        if not 1 <= port <= 65535:
            raise ValueError("Debug port must be between 1 and 65535.")
        if recycle < 1:
            raise ValueError("Recycle every must be at least 1.")
        if idle < 0:
            raise ValueError("Idle exit cannot be negative.")
        if timeout < 1:
            raise ValueError("Download timeout must be at least 1 second.")
        profile = self.profile_var.get().strip()
        if not profile:
            raise ValueError("Choose a browser profile directory.")
        return SessionOptions(
            port=port,
            profile=profile,
            channel=self.channel_var.get(),
            vortex_exe=self.vortex_var.get().strip() or None,
            restart_vortex=self.restart_var.get(),
            run=RunOptions(
                idle_exit=idle,
                download_timeout=timeout,
                on_failure=self.failure_var.get(),
                once=self.once_var.get(),
                recycle_every=recycle,
            ),
        )

    def _start(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        try:
            options = self._read_options()
        except ValueError as exc:
            messagebox.showerror(WINDOW_TITLE, str(exc))
            return

        self.stop_event = threading.Event()
        self._set_running(True)
        self.status_var.set("Starting...")
        self.progress.configure(value=0, maximum=100)
        self._append_log("")
        self._append_log("=" * 68)
        self._append_log("starting run")
        self.worker = threading.Thread(
            target=self._run_worker, args=(options,), daemon=True
        )
        self.worker.start()

    def _stop(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.stop_event.set()
            self.stop_button.configure(state="disabled")
            self.status_var.set("Stopping...")

    # ---- worker -> UI ---------------------------------------------------

    def _run_worker(self, options: SessionOptions) -> None:
        try:
            ok = run_session(
                options,
                self._worker_log,
                stop=self.stop_event,
                confirm=self._confirm,
                on_progress=self._progress,
            )
        except Exception:
            self._worker_log("unexpected error:")
            for line in traceback.format_exc().splitlines():
                self._worker_log("  " + line)
            ok = False
        self.events.put(("finished", ok))

    def _worker_log(self, message: str) -> None:
        self.file_log(message)
        self.events.put(("log", message))

    def _progress(self, value: Progress) -> None:
        self.events.put(("progress", value))

    def _confirm(self, message: str) -> bool:
        done = threading.Event()
        answer = {"ok": False}
        self.events.put(("confirm", message, done, answer))
        while not done.wait(0.1):
            if self.stop_event.is_set():
                return False
        return bool(answer["ok"])

    # ---- UI thread ------------------------------------------------------

    def _drain(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._append_log(event[1])
                elif kind == "progress":
                    self._apply_progress(event[1])
                elif kind == "confirm":
                    _, message, done, answer = event
                    answer["ok"] = messagebox.askokcancel(WINDOW_TITLE, message)
                    done.set()
                elif kind == "finished":
                    self._finish_run(bool(event[1]))
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(POLL_MS, self._drain)

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _apply_progress(self, value: Progress) -> None:
        parts = []
        if value.index is not None and value.total:
            parts.append("Mod %s/%s" % (value.index, value.total))
        elif value.name:
            parts.append(value.name)
        parts.append("%d completed" % value.completed)
        if value.failed:
            parts.append("%d failed" % value.failed)
        if value.skipped:
            parts.append("%d skipped" % value.skipped)
        self.status_var.set(" | ".join(parts))
        if value.total:
            self.progress.configure(maximum=value.total, value=value.index or 0)

    def _finish_run(self, ok: bool) -> None:
        self._set_running(False)
        if ok:
            self.status_var.set("Finished - see the log for details")
        else:
            self.status_var.set("Stopped or failed - see the log")

    def _set_running(self, running: bool) -> None:
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")
        for widget, normal_state in self.option_widgets:
            widget.configure(state="disabled" if running else normal_state)

    def _on_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            if not messagebox.askokcancel(
                WINDOW_TITLE, "A run is in progress. Stop it and close?"
            ):
                return
            self.stop_event.set()
            self.closing = True
            self.status_var.set("Stopping...")
            self.root.after(200, self._close_when_done)
        else:
            self.closing = True
            self.root.destroy()

    def _close_when_done(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.root.after(200, self._close_when_done)
        else:
            self.root.destroy()


def run_ui(here: Optional[str] = None) -> int:
    here = here or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = tk.Tk()
    App(root, here)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_ui())
