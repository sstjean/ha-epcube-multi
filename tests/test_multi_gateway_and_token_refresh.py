"""AC1 (integration-level): with a real coordinator wired to a fake API,
both gateways appear as distinct entities/devices, each with independent
sensor readings.

AC3 (integration-level): simulated JWT expiry triggers coordinator re-auth
and polling continues without user action.
"""
import time
from unittest.mock import patch

import pytest

from epcube_multi.coordinator import EpCubeCoordinator


FAKE_DEVICE_LIST = [
    {"id": "3483", "name": "epcube3483", "sgSn": "SN3483"},
    {"id": "5840", "name": "epcube5840", "sgSn": "SN5840"},
]

FAKE_DEVICE_DATA = {
    "SN3483": {"solarPower": 1.26, "gridPower": 6.89, "backUpPower": 7.72, "batterySoc": 42.0,
               "batteryCurrentElectricity": 10.0},
    "SN5840": {"solarPower": 0.5, "gridPower": -1.2, "backUpPower": 2.0, "batterySoc": 88.0,
               "batteryCurrentElectricity": 5.0},
}


def _make_fake_api_request(token_holder):
    """Build a fake api_request that serves device-list/device-info and
    honors a mutable token_holder so re-auth is observable."""

    def fake_api_request(base_url, method, path, data=None, token=None, timeout=30):
        if not token or token != token_holder["current"]:
            from epcube_multi.auth import AuthExpiredError
            raise AuthExpiredError("expired")

        if path == "/home/deviceList":
            return {"status": 200, "data": FAKE_DEVICE_LIST}

        for dev in FAKE_DEVICE_LIST:
            sg_sn = dev["sgSn"]
            if path == f"/home/homeDeviceInfo?sgSn={sg_sn}":
                return {"status": 200, "data": FAKE_DEVICE_DATA[sg_sn]}

        raise AssertionError(f"unexpected path {path}")

    return fake_api_request


@pytest.mark.asyncio
async def test_ac1_two_gateways_produce_independent_coordinator_readings(hass):
    """AC1: with two gateways on the account, coordinator data has two
    distinct entries, each with its own plausible metrics."""
    token_holder = {"current": "token-v1"}

    with patch("epcube_multi.coordinator.authenticate", return_value=token_holder["current"]), \
         patch("epcube_multi.coordinator.jwt_exp", return_value=time.time() + 3600), \
         patch("epcube_multi.coordinator.api_request", side_effect=_make_fake_api_request(token_holder)):
        coordinator = EpCubeCoordinator(hass, "https://monitoring-us.epcube.com/v1/api", "user", "pass")
        data = await coordinator._async_update_data()

    assert set(data.keys()) == {"3483", "5840"}
    dev1 = data["3483"]
    dev2 = data["5840"]
    assert dev1["name"] == "epcube3483"
    assert dev2["name"] == "epcube5840"
    assert dev1 != dev2
    assert dev1["soc"] == 42.0
    assert dev2["soc"] == 88.0


@pytest.mark.asyncio
async def test_ac3_token_refresh_reauths_and_keeps_polling(hass):
    """AC3: simulate a token that's already expired mid-poll -> coordinator
    re-auths transparently and returns fresh data (no silent death)."""
    token_holder = {"current": "old-token"}
    reauth_calls = {"n": 0}

    def fake_authenticate(base_url, username, password, log=None):
        reauth_calls["n"] += 1
        token_holder["current"] = f"token-v{reauth_calls['n'] + 1}"
        return token_holder["current"]

    with patch("epcube_multi.coordinator.authenticate", side_effect=fake_authenticate), \
         patch("epcube_multi.coordinator.jwt_exp", return_value=time.time() + 3600), \
         patch("epcube_multi.coordinator.api_request", side_effect=_make_fake_api_request(token_holder)):
        coordinator = EpCubeCoordinator(hass, "https://monitoring-us.epcube.com/v1/api", "user", "pass")
        # Force an initial (now-stale) token so the first API call 401s and
        # triggers a reauth inside _async_api_get.
        coordinator._token = "stale-token"
        coordinator._token_exp = time.time() + 3600  # not proactively expiring, but stale on the wire
        data = await coordinator._async_update_data()

    assert reauth_calls["n"] >= 1
    assert set(data.keys()) == {"3483", "5840"}
