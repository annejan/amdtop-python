from amdtop import app, cli, config
from amdtop.telemetry import memory


def test_hard_error_when_bandwidth_estimated(monkeypatch, capsys):
    monkeypatch.setattr(config, "MEM_BW_PEAK_IS_ESTIMATE", True)
    called = []
    monkeypatch.setattr(app, "run", lambda *a, **k: called.append("run"))

    rc = cli.main([])

    assert rc == 1
    assert called == []  # TUI must not start
    err = capsys.readouterr().err
    assert "does not know the peak memory bandwidth" in err
    assert "amdtop --prime-memory" in err
    assert "amdtop --no-strict" in err


def test_no_strict_bypasses_estimate_error(monkeypatch):
    monkeypatch.setattr(config, "MEM_BW_PEAK_IS_ESTIMATE", True)
    called = []
    monkeypatch.setattr(app, "run", lambda interval: called.append(interval))

    rc = cli.main(["--no-strict"])

    assert rc == 0
    assert called  # TUI started despite the estimated value


def test_prime_memory_runs_priming_only(monkeypatch):
    called = []
    monkeypatch.setattr(memory, "prime_cache", lambda: called.append("prime") or 0)
    monkeypatch.setattr(app, "run", lambda *a, **k: called.append("run"))

    rc = cli.main(["--prime-memory"])

    assert rc == 0
    assert called == ["prime"]


def test_runs_when_bandwidth_known(monkeypatch):
    monkeypatch.setattr(config, "MEM_BW_PEAK_IS_ESTIMATE", False)
    called = []
    monkeypatch.setattr(app, "run", lambda interval: called.append(interval))

    rc = cli.main([])

    assert rc == 0
    assert called  # TUI started
