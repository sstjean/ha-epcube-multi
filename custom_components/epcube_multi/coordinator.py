"""DataUpdateCoordinator for the EP Cube Multi-Gateway integration.

Ported from sstjean/EPCubeGraph local/epcube-exporter/epcube_collector.py @
e4a6c69: device discovery (_discover_devices), per-device metric polling,
and the token-refresh functions (_token_expiring_soon/_reauth), which live
in the exporter's collector module (NOT auth.py) and are ported here into
the coordinator's poll loop per the pinned spec detail.

All network + CPU-bound OpenCV work goes through hass.async_add_executor_job
so the auth/captcha solve never blocks the event loop.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .auth import AuthExpiredError, api_request, authenticate, jwt_exp
from .const import (
    DEFAULT_SCAN_INTERVAL,
    ENDPOINT_DEVICE_INFO,
    ENDPOINT_DEVICE_LIST,
    STALE_SESSION_FIELDS,
)

_LOGGER = logging.getLogger(__name__)

_TOKEN_REFRESH_MARGIN_SECONDS = 300  # re-auth proactively within 5 min of expiry


def parse_device_metrics(data: dict) -> dict:
    """Extract structured metrics from EP Cube API homeDeviceInfo response.

    Pure function — no side effects, no I/O.

    Source field mapping (verified at e4a6c69 parse_device_metrics, pinned
    in spec): solar<-solarPower, grid<-gridPower (signed, import-positive),
    home_load<-backUpPower (there is NO distinct home-load field in the
    source API; "home load" IS backup power there — do not invent a
    separate field), battery is computed = solar + grid - backup.
    """
    solar_w = _safe_float(data.get("solarPower", 0)) * 1000
    grid_w = _safe_float(data.get("gridPower", 0)) * 1000
    home_load_w = _safe_float(data.get("backUpPower", 0)) * 1000
    battery_w = round(solar_w + grid_w - home_load_w, 1)
    return {
        "soc": _safe_float(data.get("batterySoc", 0)),
        "solar_w": round(solar_w, 1),
        "grid_w": round(grid_w, 1),
        "home_load_w": round(home_load_w, 1),
        "battery_w": battery_w,
    }


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _data_looks_stale(data: dict) -> bool:
    """Detect the EP Cube cloud's silent session expiry.

    When the JWT expires, the cloud API returns HTTP 200 with all
    operational fields at zero instead of a 401. Ported verbatim check
    from epcube_collector.py@e4a6c69's _data_looks_stale.
    """
    if not data:
        return True
    return all(_safe_float(data.get(f, 0)) == 0 for f in STALE_SESSION_FIELDS)


class EpCubeCoordinator(DataUpdateCoordinator):
    """Polls all gateways on one EP Cube account (one region/one login)."""

    def __init__(self, hass: HomeAssistant, base_url: str, username: str, password: str,
                 scan_interval: int = DEFAULT_SCAN_INTERVAL):
        super().__init__(
            hass,
            _LOGGER,
            name="epcube_multi",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._base_url = base_url
        self._username = username
        self._password = password
        self._token: str | None = None
        self._token_exp: float = 0
        self._devices: list[dict] = []
        self._discovered = False

    async def _async_ensure_auth(self) -> None:
        if not self._token or self._token_expiring_soon():
            self._token = await self.hass.async_add_executor_job(
                authenticate, self._base_url, self._username, self._password, _LOGGER
            )
            self._token_exp = jwt_exp(self._token)

    def _token_expiring_soon(self) -> bool:
        if not self._token_exp:
            return False
        return time.time() > (self._token_exp - _TOKEN_REFRESH_MARGIN_SECONDS)

    async def _async_reauth(self) -> None:
        _LOGGER.info("Re-authenticating (401 or stale-session detected)...")
        self._token = await self.hass.async_add_executor_job(
            authenticate, self._base_url, self._username, self._password, _LOGGER
        )
        self._token_exp = jwt_exp(self._token)

    async def _async_api_get(self, path: str) -> dict:
        try:
            return await self.hass.async_add_executor_job(
                api_request, self._base_url, "GET", path, None, self._token
            )
        except AuthExpiredError:
            await self._async_reauth()
            return await self.hass.async_add_executor_job(
                api_request, self._base_url, "GET", path, None, self._token
            )

    async def _async_discover_devices(self) -> None:
        await self._async_ensure_auth()
        result = await self._async_api_get(ENDPOINT_DEVICE_LIST)
        if result.get("status") != 200:
            raise UpdateFailed(
                f"Cloud {ENDPOINT_DEVICE_LIST} returned status={result.get('status')}: "
                f"{result.get('message', 'no message')}"
            )
        devices = result.get("data") or []
        if not devices:
            _LOGGER.warning("Cloud returned empty device list — retaining current devices")
            return
        self._devices = devices
        self._discovered = True

    async def _async_update_data(self) -> dict:
        if not self._discovered:
            await self._async_discover_devices()

        readings: dict[str, dict] = {}
        for device in self._devices:
            sg_sn = device.get("sgSn", "")
            dev_id = str(device.get("id"))
            info = await self._async_api_get(f"{ENDPOINT_DEVICE_INFO}?sgSn={sg_sn}")
            data = info.get("data", {})

            if _data_looks_stale(data):
                _LOGGER.warning("Stale data detected for device %s — forcing re-auth", dev_id)
                await self._async_reauth()
                info = await self._async_api_get(f"{ENDPOINT_DEVICE_INFO}?sgSn={sg_sn}")
                data = info.get("data", {})

            # Re-check staleness on the FINAL data (post-reauth refetch may
            # still be all-zero if reauth itself didn't yield fresh data).
            # Stored per-device so surplus sensors can refuse to compute on
            # a stale/all-zero payload instead of reporting a false surplus.
            is_stale = _data_looks_stale(data)

            readings[dev_id] = {
                "name": device.get("name", dev_id),
                "sg_sn": sg_sn,
                "stale": is_stale,
                **parse_device_metrics(data),
            }

        return readings
