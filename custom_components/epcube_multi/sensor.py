"""Sensor platform for the EP Cube Multi-Gateway integration.

Per-gateway entities keyed by device id, plus one computed whole-property
surplus sensor. Uses the HA device registry so each gateway is its own
Device with its sensors grouped under it.
"""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SURPLUS_MODE, DEFAULT_SURPLUS_MODE, DOMAIN, SURPLUS_MODE_GRID_EXPORT, SURPLUS_MODE_SOLAR_MINUS_LOAD, SURPLUS_MODES


@dataclass(frozen=True)
class _GatewayMetricDescription:
    key: str
    name_suffix: str
    device_class: SensorDeviceClass | None
    unit: str | None
    signed: bool = False


GATEWAY_METRICS: tuple[_GatewayMetricDescription, ...] = (
    _GatewayMetricDescription("soc", "State of Charge", SensorDeviceClass.BATTERY, PERCENTAGE),
    _GatewayMetricDescription("grid_w", "Grid Power", SensorDeviceClass.POWER, UnitOfPower.WATT, signed=True),
    _GatewayMetricDescription("solar_w", "Solar Power", SensorDeviceClass.POWER, UnitOfPower.WATT),
    _GatewayMetricDescription("home_load_w", "Home Load", SensorDeviceClass.POWER, UnitOfPower.WATT),
    _GatewayMetricDescription("battery_w", "Battery Power", SensorDeviceClass.POWER, UnitOfPower.WATT, signed=True),
)


def _get_surplus_mode(entry: ConfigEntry) -> str:
    """Read surplus_mode from entry.options, enum-validated.

    Unknown/undefined/hand-edited values fall back to the default rather
    than crashing or computing an undefined formula (validation guard).
    """
    mode = entry.options.get(CONF_SURPLUS_MODE, DEFAULT_SURPLUS_MODE)
    if mode not in SURPLUS_MODES:
        return DEFAULT_SURPLUS_MODE
    return mode


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up EP Cube sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Coordinator's first refresh (triggered in __init__.py) populates
    # coordinator.data with one entry per discovered device id.
    entities: list[SensorEntity] = []
    for dev_id in coordinator.data:
        for metric in GATEWAY_METRICS:
            entities.append(EpCubeGatewaySensor(coordinator, entry.entry_id, dev_id, metric))
        entities.append(EpCubeGatewaySurplusSensor(coordinator, entry, dev_id))

    entities.append(EpCubePropertySurplusSensor(coordinator, entry.entry_id))

    async_add_entities(entities)


class EpCubeGatewaySensor(CoordinatorEntity, SensorEntity):
    """A single metric for one EP Cube gateway device."""

    def __init__(self, coordinator, entry_id: str, dev_id: str, metric: _GatewayMetricDescription):
        super().__init__(coordinator)
        self._dev_id = dev_id
        self._metric = metric
        self._attr_unique_id = f"epcube_{dev_id}_{metric.key}"
        self._attr_device_class = metric.device_class
        self._attr_native_unit_of_measurement = metric.unit
        self._attr_state_class = SensorStateClass.MEASUREMENT
        dev_name = (coordinator.data.get(dev_id) or {}).get("name", dev_id)
        self._attr_name = f"EP Cube {dev_name} {metric.name_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dev_id)},
            name=f"EP Cube {dev_name}",
            manufacturer="Canadian Solar",
            model="EP Cube",
        )

    @property
    def native_value(self):
        device_data = self.coordinator.data.get(self._dev_id)
        if not device_data:
            return None
        return device_data.get(self._metric.key)


class EpCubeGatewaySurplusSensor(CoordinatorEntity, SensorEntity):
    """Per-gateway surplus: how much spare power is available at THIS
    gateway right now. Export-positive, clamped at >= 0 (design decision
    2026-07-26) — "surplus = spare watts, always a positive number."

    Definition is user-selectable via the integration's Options Flow
    (surplus_mode), applied uniformly to all gateways in the entry:
      - "grid_export" (default): max(0, -grid_w) — conservative, only
        counts power actually flowing to the grid right now.
      - "solar_minus_load": max(0, solar_w - home_load_w) — aggressive,
        shows headroom even while the battery is charging. NOTE: "Load"
        here is BACKUP-CIRCUIT power (home_load_w <- backUpPower), not
        whole-home load - the source API has no distinct home-load field,
        so this mode can overstate true headroom for non-backup circuits.

    Refuses to compute on a stale/all-zero payload (silent JWT-expiry
    case) - returns None (unknown) rather than a false-high surplus.
    """

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry: ConfigEntry, dev_id: str):
        super().__init__(coordinator)
        self._entry = entry
        self._dev_id = dev_id
        self._attr_unique_id = f"epcube_{dev_id}_surplus"
        dev_name = (coordinator.data.get(dev_id) or {}).get("name", dev_id)
        self._attr_name = f"EP Cube {dev_name} Surplus"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dev_id)},
            name=f"EP Cube {dev_name}",
            manufacturer="Canadian Solar",
            model="EP Cube",
        )

    @property
    def native_value(self):
        device_data = self.coordinator.data.get(self._dev_id)
        if not device_data:
            return None
        if device_data.get("stale"):
            return None

        mode = _get_surplus_mode(self._entry)
        if mode == SURPLUS_MODE_SOLAR_MINUS_LOAD:
            solar_w = device_data.get("solar_w", 0.0)
            home_load_w = device_data.get("home_load_w", 0.0)
            return round(max(0.0, solar_w - home_load_w), 1)

        # Default: grid_export
        grid_w = device_data.get("grid_w", 0.0)
        return round(max(0.0, -grid_w), 1)


class EpCubePropertySurplusSensor(CoordinatorEntity, SensorEntity):
    """Computed whole-property surplus: total spare power across every
    gateway, export-positive and clamped at >= 0 (design decision).

    BEHAVIOR CHANGE (v1.1.0): previously export-negative
    (max signed sum, negative on export). Now max(0, -sum(grid_w)) so the
    mental model is the same everywhere: "surplus = spare watts, always a
    positive number." A deficit/import is simply 0 surplus. See CHANGELOG.
    """

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry_id: str):
        super().__init__(coordinator)
        self._attr_unique_id = f"epcube_property_surplus_{entry_id}"
        self._attr_name = "EP Cube Property Surplus"

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        total = 0.0
        for device_data in self.coordinator.data.values():
            grid_w = device_data.get("grid_w")
            if grid_w is not None:
                total += grid_w
        # grid_w is import-positive/export-negative; surplus is
        # export-positive and clamped, so it's max(0, -sum(grid_w)).
        return round(max(0.0, -total), 1)
