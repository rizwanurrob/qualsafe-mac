#!/usr/bin/env python
"""
Client for the isolated Laya worker process (Alt Survey Flow).

Mirrors `engines/ollama_client.py`'s shape deliberately (typed errors,
`is_available()`, fully mockable) even though the transport differs: Ollama is
an HTTP server the user installs once; Laya's isolation boundary is a *subprocess
this app launches itself* running `engines/laya_worker.py` under a separate
Python environment (see `engines/laya_setup.py`) — because unlike Ollama, `laya`
is a Python package whose dependencies (transformers 5.x, torch 2.14) would
collide with this app's own pinned engine stack if imported in-process. See
laya_worker.py's docstring for the full reasoning and the stdio protocol.

**"Load once, keep resident, unload when appropriate" (the user's requirement)
maps onto process lifecycle, not a Python object's lifecycle**: `start()` spawns
the worker and blocks until it reports its model is loaded (this is where the
one-time load cost is paid); every `predict()` call after that reuses the same
resident process; `stop()` terminates it. A caller (the Alt Survey Flow view)
calls `start()` when the tab opens and `stop()` when it closes or the app exits
— never per-response, which would reload the model every time.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

WORKER_SCRIPT = Path(__file__).resolve().parent / "laya_worker.py"
DEFAULT_START_TIMEOUT = 600    # model load: 114 s measured on a laptop CPU (2026-10-05); allow slower machines
DEFAULT_PREDICT_TIMEOUT = 120  # one answer: about 3 s measured on a laptop CPU; allow slower machines
                                 # quoted GPU numbers -- see docs/ALT_SURVEY_FLOW_PLAN.md


class LayaError(Exception):
    """Base error for Laya interactions."""


class LayaNotAvailable(LayaError):
    """The worker process is not running, or failed to start."""


class LayaTimeout(LayaError):
    """A request to the worker exceeded its timeout."""


class LayaWorkerError(LayaError):
    """The worker reported a failure for one request (not fatal to the process)."""


class LayaClient:
    """Launches and talks to `laya_worker.py` in an isolated Python environment.

    `python_exe` must be the interpreter of an environment with `laya` installed
    (never this app's own interpreter — see the module docstring). Get it from
    `engines.laya_setup.isolated_python_path()`.

    Fully mockable for tests via `process_factory`, which defaults to
    `subprocess.Popen` but can be swapped for a fake process (see
    tests/test_laya_client.py) so the suite never spawns a real subprocess.
    """

    def __init__(
        self, python_exe: str, *, model: str = "convaiinnovations/laya",
        subfolder: Optional[str] = None, env: Optional[Dict[str, str]] = None,
        process_factory: Callable[..., "subprocess.Popen"] = subprocess.Popen,
    ):
        self.python_exe = python_exe
        #: The worker's environment: what lets it find the Laya package (PYTHONPATH).
        self.env = env
        self.model = model
        self.subfolder = subfolder
        self._process_factory = process_factory
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()   # one in-flight request at a time; the
                                         # worker reads stdin one line at a time

    # ── lifecycle ────────────────────────────────────────────────────────────
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, timeout: float = DEFAULT_START_TIMEOUT) -> None:
        """Launch the worker and wait for it to report the model is loaded.

        Idempotent: calling start() while already running is a no-op, so a view
        that (re)opens can call it unconditionally rather than tracking state
        itself.
        """
        if self.is_running():
            return
        cmd = [self.python_exe, str(WORKER_SCRIPT), "--model", self.model]
        if self.subfolder:
            cmd += ["--subfolder", self.subfolder]
        try:
            self._proc = self._process_factory(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1, env=self.env,
                # no console window flashing up when the app has none
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
            )
        except OSError as exc:
            raise LayaNotAvailable(f"Could not start the Laya worker: {exc}") from exc

        ready_line = self._readline(timeout=timeout)
        if ready_line is None:
            stderr = self._drain_stderr()
            self._proc = None
            raise LayaNotAvailable(
                f"The Laya worker did not respond within {timeout}s. "
                f"{stderr or 'No error output captured.'}")
        try:
            ready = json.loads(ready_line)
        except json.JSONDecodeError as exc:
            stderr = self._drain_stderr()
            self._proc = None
            raise LayaNotAvailable(
                f"The Laya worker sent an unreadable startup message: {ready_line!r}. "
                f"{stderr}") from exc
        if not ready.get("ok"):
            error = ready.get("error", "unknown error")
            self._proc = None
            raise LayaNotAvailable(f"The Laya worker failed to start: {error}")

    def stop(self) -> None:
        """Unload the model by ending the worker process. Safe to call when not
        running. The Alt Survey Flow tab calls this on close (the "unload when
        appropriate" the user asked for) so an idle worker doesn't hold its
        model in memory indefinitely."""
        if self._proc is None:
            return
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.write("__SHUTDOWN__\n")
                self._proc.stdin.flush()
            self._proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 - a graceful shutdown attempt, not a guarantee
            self._proc.kill()
        finally:
            self._proc = None

    def __enter__(self) -> "LayaClient":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    # ── inference ────────────────────────────────────────────────────────────
    def predict(
        self, state: Dict[str, Any], questions: Dict[str, Any],
        *, timeout: float = DEFAULT_PREDICT_TIMEOUT,
    ) -> Dict[str, Any]:
        """One coding decision: `state` (typically `{"text": excerpt_text}`) plus
        the questions dict (see engines/laya_engine.py for how codes become
        questions). Returns the worker's `answers` dict, keyed by question name.

        Raises LayaNotAvailable if the worker isn't running, LayaTimeout if it
        doesn't answer in time, LayaWorkerError if it answered with a failure for
        this one item (the process itself is still usable — a caller should
        record the item as needing manual review, not stop the run).
        """
        if not self.is_running():
            raise LayaNotAvailable("The Laya worker is not running. Call start() first.")

        with self._lock:
            try:
                assert self._proc.stdin is not None
                self._proc.stdin.write(json.dumps({"state": state, "questions": questions}) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._proc = None
                raise LayaNotAvailable(f"The Laya worker process has died: {exc}") from exc

            line = self._readline(timeout=timeout)
        if line is None:
            raise LayaTimeout(f"The Laya worker did not answer within {timeout}s.")
        try:
            result = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LayaWorkerError(f"Unreadable response from Laya worker: {line!r}") from exc
        if not result.get("ok"):
            raise LayaWorkerError(result.get("error", "unknown error"))
        return result.get("answers", {})

    # ── stdio plumbing ───────────────────────────────────────────────────────
    def _readline(self, timeout: float) -> Optional[str]:
        """Read one line from the worker's stdout, or None on timeout/EOF.

        `subprocess.Popen`'s pipes have no built-in per-read timeout, so this
        reads on a daemon thread and joins with one — the standard workaround,
        used because `communicate()` would close the pipes after one exchange
        and this client needs many exchanges over one resident process.
        """
        if self._proc is None or self._proc.stdout is None:
            return None
        result: Dict[str, Optional[str]] = {"line": None}

        def _read():
            result["line"] = self._proc.stdout.readline() or None

        thread = threading.Thread(target=_read, daemon=True)
        thread.start()
        thread.join(timeout=timeout)
        if thread.is_alive():
            return None    # readline is still blocked; the caller treats this as a timeout
        line = result["line"]
        return line.strip() if line else None

    def _drain_stderr(self) -> str:
        if self._proc is None or self._proc.stderr is None:
            return ""
        try:
            return (self._proc.stderr.read() or "").strip()[-1000:]
        except Exception:  # noqa: BLE001
            return ""
