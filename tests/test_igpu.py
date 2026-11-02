from amdtop.telemetry.igpu import throttle_pct


def test_full_interval_is_100_percent():
    assert throttle_pct(1000, 1.0) == 100.0


def test_partial_interval():
    assert throttle_pct(250, 1.0) == 25.0
    assert throttle_pct(250, 0.5) == 50.0


def test_jitter_above_interval_is_clamped():
    assert throttle_pct(1003, 1.0) == 100.0


def test_unusable_samples_return_none():
    assert throttle_pct(-5, 1.0) is None  # counter reset
    assert throttle_pct(10, 0.0) is None
