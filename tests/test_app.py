"""Tests for the kill helper used by the iGPU process-kill key handling."""

import signal

from amdtop import app


def test_kill_success(monkeypatch):
    sent = []
    monkeypatch.setattr(app.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    assert app._kill(1234) == "killed 1234"
    assert sent == [(1234, signal.SIGKILL)]


def test_kill_permission_denied(monkeypatch):
    def boom(pid, sig):
        raise PermissionError

    monkeypatch.setattr(app.os, "kill", boom)
    assert app._kill(1234) == "kill 1234: permission denied"


def test_kill_no_such_process(monkeypatch):
    def boom(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(app.os, "kill", boom)
    assert app._kill(1234) == "kill 1234: no such process"
