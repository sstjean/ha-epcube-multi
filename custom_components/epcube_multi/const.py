"""Constants for the EP Cube Multi-Gateway integration."""
from __future__ import annotations

DOMAIN = "epcube_multi"

# Regional EP Cube cloud API hosts.
# DNS+HTTP-verified 2026-07-25: three regional backends exist and answer the
# API live at /v1/api. monitoring.epcube.com (no suffix) is a US alias (same
# IPs), not a distinct region. au/uk/de/cn/in/apac/emea/global do NOT resolve.
# Only these three regions exist.
REGIONS: dict[str, str] = {
    "US": "https://monitoring-us.epcube.com/v1/api",  # AWS us-west-1
    "EU": "https://monitoring-eu.epcube.com/v1/api",  # AWS eu-west-3 (Paris)
    "JP": "https://monitoring-jp.epcube.com/v1/api",  # AWS ap-northeast-1 (Tokyo)
}
DEFAULT_REGION = "US"

CONF_REGION = "region"

# API endpoints (paths relative to the region's CLOUD_API_BASE)
ENDPOINT_CAPTCHA_GET = "/common/captcha/get"
ENDPOINT_CAPTCHA_CHECK = "/common/captcha/check"
ENDPOINT_LOGIN = "/common/login"
ENDPOINT_DEVICE_LIST = "/home/deviceList"
ENDPOINT_DEVICE_INFO = "/home/homeDeviceInfo"

DEFAULT_SCAN_INTERVAL = 30  # seconds
DEFAULT_DISCOVERY_INTERVAL = 3600  # seconds between device-list re-queries

# Fields the cloud returns all-zero on silent JWT expiry (HTTP 200, no 401).
STALE_SESSION_FIELDS = (
    "solarPower",
    "gridPower",
    "backUpPower",
    "batterySoc",
    "batteryCurrentElectricity",
)

# Per-gateway surplus sensor: user-selectable definition of "surplus".
# Both modes are export-positive and clamped at >= 0 (design decision).
CONF_SURPLUS_MODE = "surplus_mode"
SURPLUS_MODE_GRID_EXPORT = "grid_export"
SURPLUS_MODE_SOLAR_MINUS_LOAD = "solar_minus_load"
SURPLUS_MODES = (SURPLUS_MODE_GRID_EXPORT, SURPLUS_MODE_SOLAR_MINUS_LOAD)
DEFAULT_SURPLUS_MODE = SURPLUS_MODE_GRID_EXPORT

SURPLUS_MODE_LABELS = {
    SURPLUS_MODE_GRID_EXPORT: "Power sent to Grid",
    SURPLUS_MODE_SOLAR_MINUS_LOAD: "Solar minus Load",
}

