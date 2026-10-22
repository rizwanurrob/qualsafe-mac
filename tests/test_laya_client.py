"""engines/laya_client.py -- against a fake process, never a real subprocess.

No real Laya install and no real subprocess anywhere in this suite: `LayaClient`
takes `process_factory`, and every test here injects a fake one that behaves
like a `subprocess.Popen` (readable .stdout, writable .stdin, .poll()) without
running any external program -- the same reason engines/ollama_client.py's tests
patch `requests` rather than hitting a real server.
"""

from __future__ import annotations

import io
import json

import pytest

from engines.laya_client import LayaClient, LayaNotAvailable, LayaTimeout, LayaWorkerError


class FakeStream(io.StringIO):
    """A stdout-like stream whose readline() can be scripted per call."""

    def __init__(self, lines):
        super().__init__()
        self._lines = list(lines)

    def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return ""   # EOF


class FakeProcess:
    """Enough of `subprocess.Popen`'s surface for LayaClient to drive."""

    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.stdin = io.StringIO()
        self._sent = []
        self.stdout = FakeStream(["""{"ok": true, "ready": true}\n"""])
        self.stderr = io.StringIO("")
        self._returncode = None
        self._response_queue = []

    # Record every line written so tests can assert on what was sent.
    def write_to_stdin(self, text):
        self._sent.append(text)

    def poll(self):
        return self._returncode

    def wait(self, timeout=None):
        self._returncode = 0
        return 0

    def kill(self):
        self._returncode = -9


def _factory_with_responses(*response_lines):
    """Build a process_factory whose worker answers `predict()` calls in order,
    after the initial ready handshake."""
    proc_holder = {}

    def factory(cmd, **kwargs):
        proc = FakeProcess(cmd, **kwargs)
        lines = ['{"ok": true, "ready": true}\n'] + list(response_lines)
        proc.stdout = FakeStream(lines)
        # Capture writes to stdin so we can assert on the request shape.
        original_write = proc.stdin.write

        def spying_write(text):
            proc._sent.append(text)
            return original_write(text)

        proc.stdin.write = spying_write
        proc_holder["proc"] = proc
        return proc

    return factory, proc_holder


def test_start_reads_the_ready_handshake():
    factory, _ = _factory_with_responses()
    client = LayaClient("fake-python", process_factory=factory)
    client.start()
    assert client.is_running()


def test_start_is_idempotent():
    factory, holder = _factory_with_responses()
    client = LayaClient("fake-python", process_factory=factory)
    client.start()
    first_proc = holder["proc"]
    client.start()   # must not spawn a second process
    assert holder["proc"] is first_proc


def test_start_raises_when_the_worker_reports_failure():
    def factory(cmd, **kwargs):
        proc = FakeProcess(cmd, **kwargs)
        proc.stdout = FakeStream(['{"ok": false, "error": "laya is not installed"}\n'])
        return proc
    client = LayaClient("fake-python", process_factory=factory)
    with pytest.raises(LayaNotAvailable, match="laya is not installed"):
        client.start()


def test_start_raises_on_no_response():
    def factory(cmd, **kwargs):
        proc = FakeProcess(cmd, **kwargs)
        proc.stdout = FakeStream([])   # immediate EOF, no handshake line
        return proc
    client = LayaClient("fake-python", process_factory=factory)
    with pytest.raises(LayaNotAvailable):
        client.start(timeout=1)


def test_predict_before_start_raises():
    client = LayaClient("fake-python")
    with pytest.raises(LayaNotAvailable):
        client.predict({"text": "x"}, {"c1": {"type": "noul", "instructions": "?"}})


def test_predict_sends_state_and_questions_and_returns_answers():
    response = json.dumps({"ok": True, "answers": {"c1": {"noul": 0.8, "confidence": 0.7}}}) + "\n"
    factory, holder = _factory_with_responses(response)
    client = LayaClient("fake-python", process_factory=factory)
    client.start()

    answers = client.predict({"text": "hello"}, {"c1": {"type": "noul", "instructions": "?"}})

    assert answers == {"c1": {"noul": 0.8, "confidence": 0.7}}
    sent = json.loads(holder["proc"]._sent[0])
    assert sent["state"] == {"text": "hello"}
    assert sent["questions"] == {"c1": {"type": "noul", "instructions": "?"}}


def test_predict_raises_laya_worker_error_on_a_per_item_failure():
    response = json.dumps({"ok": False, "error": "bad input"}) + "\n"
    factory, _ = _factory_with_responses(response)
    client = LayaClient("fake-python", process_factory=factory)
    client.start()
    with pytest.raises(LayaWorkerError, match="bad input"):
        client.predict({"text": "x"}, {"c1": {"type": "noul", "instructions": "?"}})


def test_predict_times_out_when_no_response_arrives():
    factory, _ = _factory_with_responses()   # no queued response after the handshake
    client = LayaClient("fake-python", process_factory=factory)
    client.start()
    with pytest.raises(LayaTimeout):
        client.predict({"text": "x"}, {"c1": {"type": "noul", "instructions": "?"}}, timeout=0.2)


def test_stop_sends_shutdown_and_clears_the_process():
    factory, holder = _factory_with_responses()
    client = LayaClient("fake-python", process_factory=factory)
    client.start()
    client.stop()
    assert not client.is_running()
    assert holder["proc"]._sent[-1] == "__SHUTDOWN__\n"


def test_stop_when_never_started_is_a_no_op():
    client = LayaClient("fake-python")
    client.stop()   # must not raise
    assert not client.is_running()


def test_context_manager_starts_and_stops():
    factory, holder = _factory_with_responses()
    with LayaClient("fake-python", process_factory=factory) as client:
        assert client.is_running()
    assert not client.is_running()


def test_subfolder_is_passed_to_the_worker_command():
    factory, holder = _factory_with_responses()
    client = LayaClient("fake-python", subfolder="multilingual", process_factory=factory)
    client.start()
    assert "--subfolder" in holder["proc"].cmd
    assert "multilingual" in holder["proc"].cmd
