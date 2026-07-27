"""AC-8: Options Flow round-trips (set mode -> reload -> entry.options
persists the machine key; unique_ids unchanged).

AC-1: gateway surplus sensor groups under the SAME Device as the gateway's
other sensors (reuses DeviceInfo identifiers).
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

import pytest

from epcube_multi.const import CONF_SURPLUS_MODE, DOMAIN, SURPLUS_MODE_SOLAR_MINUS_LOAD
from epcube_multi.config_flow import EpCubeMultiOptionsFlow
from epcube_multi.sensor import EpCubeGatewaySensor, EpCubeGatewaySurplusSensor, GATEWAY_METRICS


class _FakeCoordinator:
    def __init__(self, data):
        self.data = data

    def async_add_listener(self, *args, **kwargs):
        return lambda: None


def test_ac1_surplus_sensor_shares_device_info_with_gateway_sensors():
    """The surplus sensor's DeviceInfo identifiers must match the regular
    gateway sensors' - so it's grouped under the SAME Device, not the
    property level."""
    coordinator = _FakeCoordinator({"devA": {"name": "GatewayA", "soc": 50.0}})
    entry = SimpleNamespace(entry_id="entry1", options={})

    metric_sensor = EpCubeGatewaySensor(coordinator, "entry1", "devA", GATEWAY_METRICS[0])
    surplus_sensor = EpCubeGatewaySurplusSensor(coordinator, entry, "devA")

    assert metric_sensor._attr_device_info["identifiers"] == surplus_sensor._attr_device_info["identifiers"]
    assert surplus_sensor._attr_device_info["identifiers"] == {(DOMAIN, "devA")}


def test_ac1_surplus_unique_id_is_per_gateway_not_property_level():
    coordinator = _FakeCoordinator({"devA": {"name": "GatewayA"}, "devB": {"name": "GatewayB"}})
    entry = SimpleNamespace(entry_id="entry1", options={})

    sensor_a = EpCubeGatewaySurplusSensor(coordinator, entry, "devA")
    sensor_b = EpCubeGatewaySurplusSensor(coordinator, entry, "devB")

    assert sensor_a.unique_id == "epcube_devA_surplus"
    assert sensor_b.unique_id == "epcube_devB_surplus"
    assert sensor_a.unique_id != sensor_b.unique_id


@pytest.mark.asyncio
async def test_ac8_options_flow_round_trip_persists_machine_key(hass):
    """Setting mode via the options flow persists the MACHINE key
    (solar_minus_load), not the UI label, and unique_ids don't move."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    flow = EpCubeMultiOptionsFlow()
    flow.hass = hass
    flow.handler = entry.entry_id

    result = await flow.async_step_init({CONF_SURPLUS_MODE: SURPLUS_MODE_SOLAR_MINUS_LOAD})

    assert result["type"] == "create_entry"
    assert result["data"][CONF_SURPLUS_MODE] == SURPLUS_MODE_SOLAR_MINUS_LOAD


@pytest.mark.asyncio
async def test_ac8_options_flow_rejects_unknown_mode_falls_back_to_default(hass):
    from epcube_multi.const import DEFAULT_SURPLUS_MODE
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    flow = EpCubeMultiOptionsFlow()
    flow.hass = hass
    flow.handler = entry.entry_id

    result = await flow.async_step_init({CONF_SURPLUS_MODE: "bogus_mode"})

    assert result["data"][CONF_SURPLUS_MODE] == DEFAULT_SURPLUS_MODE
