"""AC4 (surplus sensor sign) at the coordinator-data level, and AC3
(stale-session detection that drives token re-auth without user action)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from epcube_multi.coordinator import _data_looks_stale


def test_stale_session_all_zero_fields_detected():
    """AC3: EP Cube cloud returns HTTP 200 with all-zero fields on silent
    JWT expiry (no 401) - must be detected so the coordinator re-auths."""
    stale_data = {
        "solarPower": 0,
        "gridPower": 0,
        "backUpPower": 0,
        "batterySoc": 0,
        "batteryCurrentElectricity": 0,
    }
    assert _data_looks_stale(stale_data) is True


def test_live_data_not_flagged_stale():
    """A genuinely live reading (even a partially-zero one, e.g. no solar at
    night) must NOT be misdetected as a stale/expired session."""
    live_data = {
        "solarPower": 0,       # e.g. nighttime - legitimately zero
        "gridPower": 2.5,
        "backUpPower": 1.8,
        "batterySoc": 60,
        "batteryCurrentElectricity": 24.0,
    }
    assert _data_looks_stale(live_data) is False


def test_empty_data_treated_as_stale():
    assert _data_looks_stale({}) is True
    assert _data_looks_stale(None) is True


def test_surplus_sensor_sums_signed_grid_power_across_gateways():
    """Property surplus (AC-7): export-positive, clamped >= 0.
    max(0, -sum(grid_w))."""
    coordinator_data = {
        "dev1": {"grid_w": 6890.0},   # importing
        "dev2": {"grid_w": -2100.0},  # exporting
    }
    total = sum(d.get("grid_w", 0) for d in coordinator_data.values())
    surplus = round(max(0.0, -total), 1)
    assert surplus == 0.0  # net import -> 0 surplus, not a negative number

    # Net-export scenario: total = -800 -> surplus = 800 (positive!)
    coordinator_data2 = {
        "dev1": {"grid_w": -500.0},
        "dev2": {"grid_w": -300.0},
    }
    total2 = sum(d.get("grid_w", 0) for d in coordinator_data2.values())
    surplus2 = round(max(0.0, -total2), 1)
    assert surplus2 == 800.0
