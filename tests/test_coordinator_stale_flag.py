"""Coordinator-level test for the per-device `stale` flag (spec's coordinator
fix: re-run _data_looks_stale on the FINAL data before parse_device_metrics,
even after a re-auth attempt)."""
import time
from unittest.mock import patch

import pytest

from epcube_multi.coordinator import EpCubeCoordinator


FAKE_DEVICE_LIST = [{"id": "1", "name": "gw1", "sgSn": "SN1"}]


def _fake_api_request_factory(device_data_sequence):
    """Returns fake api_request; each call to homeDeviceInfo consumes the
    next entry in device_data_sequence (to simulate stale-then-still-stale
    across the reauth retry)."""
    calls = {"device_info_n": 0}

    def fake_api_request(base_url, method, path, data=None, token=None, timeout=30):
        if path == "/home/deviceList":
            return {"status": 200, "data": FAKE_DEVICE_LIST}
        if path == "/home/homeDeviceInfo?sgSn=SN1":
            idx = min(calls["device_info_n"], len(device_data_sequence) - 1)
            calls["device_info_n"] += 1
            return {"status": 200, "data": device_data_sequence[idx]}
        raise AssertionError(f"unexpected path {path}")

    return fake_api_request


@pytest.mark.asyncio
async def test_stale_flag_true_when_reauth_still_returns_zeros(hass):
    """If even the post-reauth refetch is all-zero, the stale flag must be
    True on the FINAL stored reading (stale-guard requirement)."""
    stale_payload = {"solarPower": 0, "gridPower": 0, "backUpPower": 0, "batterySoc": 0,
                      "batteryCurrentElectricity": 0}
    fake_api = _fake_api_request_factory([stale_payload, stale_payload])  # stale both times

    with patch("epcube_multi.coordinator.authenticate", return_value="tok"), \
         patch("epcube_multi.coordinator.jwt_exp", return_value=time.time() + 3600), \
         patch("epcube_multi.coordinator.api_request", side_effect=fake_api):
        coordinator = EpCubeCoordinator(hass, "https://monitoring-us.epcube.com/v1/api", "user", "pass")
        data = await coordinator._async_update_data()

    assert data["1"]["stale"] is True


@pytest.mark.asyncio
async def test_stale_flag_false_when_reauth_recovers_fresh_data(hass):
    """If the first read is stale but the post-reauth refetch is fresh,
    stale must be False on the final stored reading."""
    stale_payload = {"solarPower": 0, "gridPower": 0, "backUpPower": 0, "batterySoc": 0,
                      "batteryCurrentElectricity": 0}
    fresh_payload = {"solarPower": 2.0, "gridPower": 1.0, "backUpPower": 1.5, "batterySoc": 60,
                      "batteryCurrentElectricity": 10}
    fake_api = _fake_api_request_factory([stale_payload, fresh_payload])

    with patch("epcube_multi.coordinator.authenticate", return_value="tok"), \
         patch("epcube_multi.coordinator.jwt_exp", return_value=time.time() + 3600), \
         patch("epcube_multi.coordinator.api_request", side_effect=fake_api):
        coordinator = EpCubeCoordinator(hass, "https://monitoring-us.epcube.com/v1/api", "user", "pass")
        data = await coordinator._async_update_data()

    assert data["1"]["stale"] is False


@pytest.mark.asyncio
async def test_stale_flag_false_on_genuinely_live_first_read(hass):
    """No staleness detected at all -> stale=False, no reauth triggered."""
    fresh_payload = {"solarPower": 2.0, "gridPower": 1.0, "backUpPower": 1.5, "batterySoc": 60,
                      "batteryCurrentElectricity": 10}
    fake_api = _fake_api_request_factory([fresh_payload])

    with patch("epcube_multi.coordinator.authenticate", return_value="tok") as mock_auth, \
         patch("epcube_multi.coordinator.jwt_exp", return_value=time.time() + 3600), \
         patch("epcube_multi.coordinator.api_request", side_effect=fake_api):
        coordinator = EpCubeCoordinator(hass, "https://monitoring-us.epcube.com/v1/api", "user", "pass")
        data = await coordinator._async_update_data()

    assert data["1"]["stale"] is False
    # Only the initial ensure_auth call, no reauth triggered by staleness.
    assert mock_auth.call_count == 1
