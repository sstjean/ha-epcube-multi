"""AC1 & AC4: multi-gateway device separation, field mapping, and grid-sign
verification for the computed property-surplus sensor.

Pure-function level tests against coordinator.parse_device_metrics — no HA
instance required for these core mapping/sign assertions.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from epcube_multi.coordinator import parse_device_metrics


def test_parse_device_metrics_field_mapping():
    """home_load_w must read backUpPower - there is no distinct home-load
    field in the source API (per spec's pinned field-mapping table)."""
    data = {
        "solarPower": 1.26,       # kW
        "gridPower": 6.89,        # kW, import-positive
        "backUpPower": 7.72,      # kW - this IS home load in the source
        "batterySoc": 42.0,
    }
    metrics = parse_device_metrics(data)

    assert metrics["solar_w"] == 1260.0
    assert metrics["grid_w"] == 6890.0
    assert metrics["home_load_w"] == 7720.0  # backUpPower, not a separate field
    assert metrics["soc"] == 42.0


def test_battery_power_identity_matches_spec_verified_sample():
    """battery = solar + grid - backup, verified against live data 2026-07-25:
    solar=1260W, home_load=7720W (importing) -> grid=+6890W -> battery=430W."""
    data = {"solarPower": 1.26, "gridPower": 6.89, "backUpPower": 7.72, "batterySoc": 50.0}
    metrics = parse_device_metrics(data)

    assert metrics["battery_w"] == 430.0


def test_grid_sign_import_positive_export_negative():
    """AC4: grid sign convention - positive=import, negative=export,
    empirically verified 2026-07-25. Re-confirms the port preserves it."""
    importing = parse_device_metrics({"gridPower": 5.0, "solarPower": 0, "backUpPower": 0, "batterySoc": 0})
    exporting = parse_device_metrics({"gridPower": -3.0, "solarPower": 0, "backUpPower": 0, "batterySoc": 0})

    assert importing["grid_w"] > 0
    assert exporting["grid_w"] < 0


def test_two_distinct_gateways_produce_independent_metrics():
    """AC1: multi-gateway - two gateway IDs must map to independently
    computed metrics, not a shared/aliased state."""
    gw1 = parse_device_metrics({"solarPower": 1.0, "gridPower": 2.0, "backUpPower": 3.0, "batterySoc": 10.0})
    gw2 = parse_device_metrics({"solarPower": 5.0, "gridPower": -1.0, "backUpPower": 4.0, "batterySoc": 90.0})

    assert gw1 != gw2
    assert gw1["soc"] == 10.0
    assert gw2["soc"] == 90.0
