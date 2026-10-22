"""
Running slow work off the GUI thread.

The handoff's rule: **everything slow goes on a worker** -- `run_pipeline`, model
loading, embedding, Ollama calls, document import, framework drafting. A frozen
window during a five-minute pipeline is the thing a desktop app is supposed to
fix relative to Streamlit, not reproduce.

Two constraints shape this module:

1. **`sqlite3` connections belong to the thread that opened them.**
   `core.project.Project` uses the default ``check_same_thread=True``, so a
   worker must **never** touch `ProjectService.project`. A task that needs the
   store opens its **own** `Project` inside `run()`, on its own thread, and the
   service calls `reopen()` afterwards so the GUI sees the writes. `Task.reads_store`
   documents which kind a given task is.

2. **A `QRunnable` is not a `QObject`**, so it cannot own signals. The signals
   live on a separate `TaskSignals` object the runnable holds -- the standard Qt
   arrangement, and the reason `finished`/`failed` are on `task.signals`.

Exceptions never escape a worker: they are caught and re-emitted as `failed`,
because an exception on a `QThreadPool` thread otherwise kills the process
without a traceback the user can act on.
"""

from __future__ import annotations

import traceback
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class TaskSignals(QObject):
    """Signals for one `Task`. Separate object because `QRunnable` is not a `QObject`."""

    #: The callable returned normally. Argument is its return value.
    finished = Signal(object)
    #: The callable raised. Arguments are (message, formatted traceback).
    failed = Signal(str, str)
    #: Optional progress: (fraction 0.0-1.0, message). Wired to
    #: `run_pipeline`'s existing `progress_callback(fraction, message)`.
    progress = Signal(float, str)
    #: Emitted after finished/failed, whichever happened. For re-enabling UI.
    done = Signal()


class Task(QRunnable):
    """Run `fn(*args, **kwargs)` on a worker thread and report back by signal.

    If `fn` accepts a ``progress_callback`` keyword, pass ``wants_progress=True``
    and it will be handed one that emits `signals.progress` -- which is exactly
    the shape `analyze_survey.run_pipeline` already expects, so wiring the
    pipeline to a progress bar later needs no adapter.
    """

    def __init__(
        self,
        fn: Callable[..., Any],
        *args: Any,
        wants_progress: bool = False,
        reads_store: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._wants_progress = wants_progress
        #: True when `fn` opens its own `Project`. The caller must
        #: `ProjectService.reopen()` on completion so the GUI connection sees
        #: the worker's writes -- it cannot share this one.
        self.reads_store = reads_store
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:  # noqa: D102 - Qt override
        try:
            kwargs = dict(self._kwargs)
            if self._wants_progress:
                kwargs["progress_callback"] = self._emit_progress
            result = self._fn(*self._args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - a worker exception must not kill the app
            self.signals.failed.emit(str(exc), traceback.format_exc())
        else:
            self.signals.finished.emit(result)
        finally:
            self.signals.done.emit()

    def _emit_progress(self, fraction: float, message: str = "") -> None:
        self.signals.progress.emit(float(fraction), str(message))


class _TaskKeeper(QObject):
    """Keeps in-flight tasks alive until their signals have been delivered.

    Without this, a `Task` the caller does not store is garbage-collected as
    soon as `run_task` returns. `QThreadPool` still runs the callable — but the
    `TaskSignals` object goes with it, so `finished` never reaches anyone. The
    work happens and the UI silently never hears about it, intermittently,
    depending on when the collector runs. That is a worse failure than a crash.

    The discard is a slot on this object, which lives on the GUI thread, so the
    `done` connection is queued: the reference is dropped from the event loop
    *after* `run()` has returned, never from inside it.
    """

    def __init__(self) -> None:
        super().__init__()
        self._live: "set[Task]" = set()

    def hold(self, task: "Task") -> None:
        self._live.add(task)
        task.signals.done.connect(lambda: self.release(task))

    @Slot()
    def release(self, task: "Task") -> None:
        self._live.discard(task)

    def count(self) -> int:
        """In-flight tasks. For tests and diagnostics."""
        return len(self._live)


#: Created lazily: constructing a QObject before QApplication exists is invalid,
#: and importing this module must not require a running application.
_keeper: Optional[_TaskKeeper] = None


def _task_keeper() -> _TaskKeeper:
    global _keeper
    if _keeper is None:
        _keeper = _TaskKeeper()
    return _keeper


def run_task(
    fn: Callable[..., Any],
    *args: Any,
    on_finished: Optional[Callable[[Any], None]] = None,
    on_failed: Optional[Callable[[str, str], None]] = None,
    on_progress: Optional[Callable[[float, str], None]] = None,
    on_done: Optional[Callable[[], None]] = None,
    wants_progress: bool = False,
    reads_store: bool = False,
    pool: Optional[QThreadPool] = None,
    **kwargs: Any,
) -> Task:
    """Start `fn` on the global thread pool. Returns the `Task` (already started).

    Connect-then-start is deliberate: a very fast task could otherwise finish
    before its callbacks were attached and the result would vanish.
    """
    task = Task(fn, *args, wants_progress=wants_progress,
                reads_store=reads_store, **kwargs)
    # Hold a reference before anything else: a caller that discards the return
    # value must still get its callbacks. See `_TaskKeeper`.
    _task_keeper().hold(task)
    if on_finished is not None:
        task.signals.finished.connect(on_finished)
    if on_failed is not None:
        task.signals.failed.connect(on_failed)
    if on_progress is not None:
        task.signals.progress.connect(on_progress)
    if on_done is not None:
        task.signals.done.connect(on_done)
    (pool or QThreadPool.globalInstance()).start(task)
    return task
