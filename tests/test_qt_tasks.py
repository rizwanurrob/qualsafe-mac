"""
The worker-thread wrapper.

Everything slow in QualSafe -- `run_pipeline`, model loading, embedding, Ollama
calls -- has to run off the GUI thread, and the failure modes are nasty: an
exception on a `QThreadPool` thread kills the process without a usable
traceback, and a `sqlite3` connection touched from the wrong thread raises at a
distance. These tests pin the contract before anything expensive depends on it.
"""

from __future__ import annotations

import os
import threading

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qualsafe_qt.services.tasks import Task, run_task  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wait(pool: QThreadPool, app, timeout_ms: int = 10_000) -> None:
    """Drain the pool while pumping the event loop, so queued signals deliver."""
    deadline = timeout_ms
    while not pool.waitForDone(50) and deadline > 0:
        app.processEvents()
        deadline -= 50
    for _ in range(20):
        app.processEvents()


def test_a_task_runs_off_the_gui_thread_and_reports_its_result(qapp):
    pool = QThreadPool()
    gui_thread = threading.get_ident()
    results, worker_threads = [], []

    def work(value):
        worker_threads.append(threading.get_ident())
        return value * 2

    run_task(work, 21, on_finished=results.append, pool=pool)
    _wait(pool, qapp)

    assert results == [42]
    assert worker_threads and worker_threads[0] != gui_thread, \
        "the callable must not run on the GUI thread"


def test_an_exception_becomes_a_failed_signal_not_a_dead_process(qapp):
    pool = QThreadPool()
    failures, finished = [], []

    def boom():
        raise ValueError("the model is not in your local cache")

    run_task(boom, on_finished=finished.append,
             on_failed=lambda msg, tb: failures.append((msg, tb)), pool=pool)
    _wait(pool, qapp)

    assert not finished
    assert len(failures) == 1
    message, formatted = failures[0]
    assert "not in your local cache" in message
    assert "ValueError" in formatted, "the traceback should survive for diagnosis"


def test_done_fires_for_both_success_and_failure(qapp):
    """UI re-enables itself on `done`, so it must fire either way."""
    pool = QThreadPool()
    done = []

    run_task(lambda: 1, on_done=lambda: done.append("ok"), pool=pool)
    _wait(pool, qapp)
    run_task(_raise, on_done=lambda: done.append("failed"), on_failed=lambda *a: None,
             pool=pool)
    _wait(pool, qapp)

    assert done == ["ok", "failed"]


def _raise():
    raise RuntimeError("nope")


def test_progress_callback_matches_the_pipelines_existing_shape(qapp):
    """`run_pipeline` already takes `progress_callback(fraction, message)`.

    Wiring it to a progress bar later must need no adapter, so the task hands
    the callable exactly that signature.
    """
    pool = QThreadPool()
    seen = []

    def staged(progress_callback):
        progress_callback(0.0, "starting")
        progress_callback(0.5, "embedding")
        progress_callback(1.0, "done")
        return "finished"

    run_task(staged, wants_progress=True,
             on_progress=lambda f, m: seen.append((f, m)), pool=pool)
    _wait(pool, qapp)

    assert seen == [(0.0, "starting"), (0.5, "embedding"), (1.0, "done")]


def test_a_task_without_wants_progress_gets_no_extra_argument(qapp):
    """Most callables take no `progress_callback`; passing one would TypeError."""
    pool = QThreadPool()
    results = []

    run_task(lambda a, b: a + b, 2, 3, on_finished=results.append, pool=pool)
    _wait(pool, qapp)

    assert results == [5]


def test_reads_store_is_recorded_so_callers_know_to_reopen(qapp):
    """A worker that opens its own `Project` needs the service to reconnect
    afterwards — the GUI's sqlite connection cannot see another thread's writes
    through a stale handle."""
    task = Task(lambda: None, reads_store=True)
    assert task.reads_store is True
    assert Task(lambda: None).reads_store is False


def test_callbacks_attach_before_the_task_can_finish(qapp):
    """A task fast enough to finish during `start()` must not lose its result."""
    pool = QThreadPool()
    results = []
    for _ in range(25):
        run_task(lambda: "x", on_finished=results.append, pool=pool)
    _wait(pool, qapp)
    assert len(results) == 25


def test_a_task_whose_return_value_is_discarded_still_delivers(qapp):
    """The regression this cost an hour to find.

    `run_task` returns the Task, but callers routinely ignore it (the codebook's
    similarity check does). Without a live reference held elsewhere, the Task —
    and with it the TaskSignals QObject carrying every connection — was
    garbage-collected as soon as `run_task` returned. QThreadPool still ran the
    callable, so the work happened and the result went nowhere, intermittently,
    depending on when the collector ran.
    """
    import gc

    pool = QThreadPool()
    results, ran = [], []

    def work():
        ran.append(1)
        return "delivered"

    run_task(work, on_finished=results.append, pool=pool)   # return value dropped
    gc.collect()                                            # be hostile about it
    _wait(pool, qapp)

    assert ran == [1], "the callable should have run"
    assert results == ["delivered"], "and its result must reach the callback"


def test_the_keeper_releases_tasks_when_they_finish(qapp):
    """Holding a reference must not become a leak: every task is released."""
    from qualsafe_qt.services.tasks import _task_keeper

    pool = QThreadPool()
    for _ in range(10):
        run_task(lambda: None, pool=pool)
    _wait(pool, qapp)

    assert _task_keeper().count() == 0, "finished tasks should not be retained"
