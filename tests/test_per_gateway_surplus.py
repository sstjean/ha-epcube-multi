"""Test suite for the per-gateway surplus sensor feature.

Covers spec AC-1 through AC-8 (spec-epcube-per-gateway-surplus.md).
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

import pytest

from epcube_multi.const import (
    CONF_SURPLUS_MODE,
    DEFAULT_SURPLUS_MODE,
    SURPLUS_MODE_GRID_EXPORT,
    SURPLUS_MODE_SOLAR_MINUS_LOAD,
)
from epcube_multi.sensor import EpCubeGatewaySurplusSensor, EpCubePropertySurplusSensor, _get_surplus_mode


class _FakeCoordinator:
    """Minimal coordinator stand-in — real CoordinatorEntity only needs
    .data and .last_update_success off the coordinator it wraps."""

    def __init__(self, data):
        self.data = data
        self.last_update_success = True

    def async_add_listener(self, *args, **kwargs):
        return lambda: None


def _fake_entry(options=None):
    return SimpleNamespace(entry_id="entry1", options=options or {})


# ---------------------------------------------------------------------------
# AC-2 / AC-3: export-positive, clamped >= 0, default mode
# ---------------------------------------------------------------------------

def test_ac2_ac3_default_mode_grid_export_clamped_positive():
    """AC-2 & AC-3: fresh install (no options) -> grid_export mode,
    export-positive, clamped >= 0."""
    coordinator = _FakeCoordinator({"devA": {"name": "A", "grid_w": -3000.0, "stale": False}})
    entry = _fake_entry()  # no options set
    sensor = EpCubeGatewaySurplusSensor(coordinator, entry, "devA")

    assert _get_surplus_mode(entry) == SURPLUS_MODE_GRID_EXPORT
    assert sensor.native_value == 3000.0  # exporting 3000W -> surplus 3000

    # Importing gateway -> surplus clamps to 0, never negative
    coordinator2 = _FakeCoordinator({"devA": {"name": "A", "grid_w": 1500.0, "stale": False}})
    sensor2 = EpCubeGatewaySurplusSensor(coordinator2, entry, "devA")
    assert sensor2.native_value == 0.0


# ---------------------------------------------------------------------------
# AC-4: switching to solar_minus_load changes the formula
# ---------------------------------------------------------------------------

def test_ac4_solar_minus_load_mode():
    coordinator = _FakeCoordinator({
        "devA": {"name": "A", "grid_w": -3000.0, "solar_w": 5000.0, "home_load_w": 2000.0, "stale": False},
    })
    entry = _fake_entry({CONF_SURPLUS_MODE: SURPLUS_MODE_SOLAR_MINUS_LOAD})
    sensor = EpCubeGatewaySurplusSensor(coordinator, entry, "devA")

    assert sensor.native_value == 3000.0  # max(0, 5000-2000)


def test_ac4_solar_minus_load_clamps_at_zero():
    coordinator = _FakeCoordinator({
        "devA": {"name": "A", "grid_w": 0.0, "solar_w": 500.0, "home_load_w": 3000.0, "stale": False},
    })
    entry = _fake_entry({CONF_SURPLUS_MODE: SURPLUS_MODE_SOLAR_MINUS_LOAD})
    sensor = EpCubeGatewaySurplusSensor(coordinator, entry, "devA")

    assert sensor.native_value == 0.0  # solar < load -> clamp, not negative


# ---------------------------------------------------------------------------
# AC-5: None-safety — device_data absent
# ---------------------------------------------------------------------------

def test_ac5_device_not_present_returns_none():
    coordinator = _FakeCoordinator({})  # devA not discovered/present
    entry = _fake_entry()
    sensor = EpCubeGatewaySurplusSensor(coordinator, entry, "devA")

    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# AC-5c: stale-payload guard — the core safety net
# ---------------------------------------------------------------------------

def test_ac5c_stale_payload_returns_none_not_false_high_surplus():
    """Given a device whose final data is all-zeros (stale=True),
    surplus_mode=solar_minus_load -> surplus is None, NOT max(0, solar_w-0)."""
    coordinator = _FakeCoordinator({
        "devA": {"name": "A", "grid_w": 0.0, "solar_w": 0.0, "home_load_w": 0.0, "stale": True},
    })
    entry = _fake_entry({CONF_SURPLUS_MODE: SURPLUS_MODE_SOLAR_MINUS_LOAD})
    sensor = EpCubeGatewaySurplusSensor(coordinator, entry, "devA")

    assert sensor.native_value is None


def test_ac5c_stale_guard_also_applies_to_grid_export_mode():
    coordinator = _FakeCoordinator({
        "devA": {"name": "A", "grid_w": 0.0, "solar_w": 0.0, "home_load_w": 0.0, "stale": True},
    })
    entry = _fake_entry()  # default grid_export
    sensor = EpCubeGatewaySurplusSensor(coordinator, entry, "devA")

    assert sensor.native_value is None


def test_non_stale_zero_reading_still_computes_normally():
    """Sanity check the stale flag itself gates the None, not the zero
    values - a legitimately idle (but NOT stale) reading still computes."""
    coordinator = _FakeCoordinator({
        "devA": {"name": "A", "grid_w": 0.0, "solar_w": 0.0, "home_load_w": 0.0, "stale": False},
    })
    entry = _fake_entry()
    sensor = EpCubeGatewaySurplusSensor(coordinator, entry, "devA")

    assert sensor.native_value == 0.0  # not None - genuinely zero surplus


# ---------------------------------------------------------------------------
# AC-6: the core no-cross-netting guard (pinned numeric Given/Then)
# ---------------------------------------------------------------------------

def test_ac6_no_cross_netting_between_gateways():
    """Given gateway A grid_w=-3000 (exporting) AND gateway B grid_w=+1000
    (importing), mode=grid_export; Then A's surplus == 3000 AND B's == 0 -
    NOT a netted 2000, and B is NOT negative. This is a mixed
    export/import pair - MUST NOT pass via two-exporting-gateways only."""
    coordinator = _FakeCoordinator({
        "A": {"name": "A", "grid_w": -3000.0, "stale": False},
        "B": {"name": "B", "grid_w": 1000.0, "stale": False},
    })
    entry = _fake_entry()  # default grid_export

    sensor_a = EpCubeGatewaySurplusSensor(coordinator, entry, "A")
    sensor_b = EpCubeGatewaySurplusSensor(coordinator, entry, "B")

    assert sensor_a.native_value == 3000.0
    assert sensor_b.native_value == 0.0
    # Explicitly assert it is NOT the netted value and NOT negative.
    assert sensor_a.native_value != 2000.0
    assert sensor_b.native_value >= 0.0


# ---------------------------------------------------------------------------
# AC-7: property sensor sign flip
# ---------------------------------------------------------------------------

def test_ac7_property_sensor_export_positive_clamped():
    """Property surplus is ALSO export-positive and clamped >= 0 now -
    a dedicated test against the OLD (export-negative) behavior."""
    coordinator = _FakeCoordinator({
        "A": {"grid_w": -3000.0},
        "B": {"grid_w": 1000.0},
    })
    sensor = EpCubePropertySurplusSensor(coordinator, "entry1")

    # Net: -3000 + 1000 = -2000 (net export) -> surplus = +2000 (positive!)
    assert sensor.native_value == 2000.0
    assert sensor.native_value >= 0  # never negative under the new sign

    # Net import -> clamps to 0, not a negative number
    coordinator2 = _FakeCoordinator({"A": {"grid_w": 5000.0}})
    sensor2 = EpCubePropertySurplusSensor(coordinator2, "entry1")
    assert sensor2.native_value == 0.0


# ---------------------------------------------------------------------------
# Enum-validation guard
# ---------------------------------------------------------------------------

def test_unknown_surplus_mode_falls_back_to_default():
    """A hand-edited entry.options with an unknown mode falls back to the
    default rather than crashing or computing an undefined formula."""
    entry = _fake_entry({CONF_SURPLUS_MODE: "not_a_real_mode"})
    assert _get_surplus_mode(entry) == DEFAULT_SURPLUS_MODE

    coordinator = _FakeCoordinator({"A": {"name": "A", "grid_w": -1000.0, "stale": False}})
    sensor = EpCubeGatewaySurplusSensor(coordinator, entry, "A")
    assert sensor.native_value == 1000.0  # behaves as default (grid_export), no crash
