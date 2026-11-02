import struct
from pathlib import Path

import pytest

from amdtop.telemetry import gpu_metrics as gm

FIXTURE = Path(__file__).parent / "fixtures" / "gpu_metrics_v3_0.bin"


@pytest.fixture
def blob() -> bytes:
    return FIXTURE.read_bytes()


def test_fixture_is_v3_0(blob):
    assert len(blob) == 264
    size, fmt_rev, content_rev = struct.unpack_from("<HBB", blob, 0)
    assert (size, fmt_rev, content_rev) == (264, 3, 0)


def test_format_payload_size():
    # Naturally-aligned struct: 260 payload bytes + 4 trailing pad = 264.
    assert gm._SIZE == 260


def test_parse_header_and_shapes(blob):
    m = gm.parse(blob)
    assert (m.structure_size, m.format_revision, m.content_revision) == (264, 3, 0)
    assert len(m.temp_core) == 16
    assert len(m.core_power) == 16
    assert len(m.coreclk) == 16
    assert len(m.ipu_activity) <= 8
    assert len(m.core_activity) <= 16


def test_scales_are_plausible(blob):
    m = gm.parse(blob)
    # Temperature in a sane range for a running APU (centi-degC -> degC).
    assert m.temp_gfx is None or 10.0 < m.temp_gfx < 120.0
    # Socket power in watts (mW/1000); fixture captured near idle/light load.
    assert m.socket_power is None or 0.0 <= m.socket_power < 200.0
    # gfx clock in MHz.
    assert m.gfxclk is None or 0 <= m.gfxclk < 5000
    # Activity values are percentages.
    for a in m.core_activity:
        assert 0 <= a <= 100
    for a in m.ipu_activity:
        assert 0 <= a <= 100


def test_sentinels_become_none():
    # u16 0xFFFF and u32 0xFFFFFFFF fields must decode to None.
    assert gm._clean16(0xFFFF) is None
    assert gm._clean16(1234) == 1234
    assert gm._clean32(0xFFFFFFFF) is None
    assert gm._clean32(4242) == 4242


def test_short_blob_raises():
    with pytest.raises(ValueError):
        gm.parse(b"\x00" * 10)


def test_read_missing_path_returns_none():
    assert gm.read("/nonexistent/gpu_metrics") is None


def test_dram_and_ipu_traffic(blob):
    # Strix Halo fixture captured at idle: some SoC traffic, NPU idle.
    m = gm.parse(blob)
    assert (m.dram_reads, m.dram_writes) == (866, 282)
    assert (m.ipu_reads, m.ipu_writes) == (0, 0)
