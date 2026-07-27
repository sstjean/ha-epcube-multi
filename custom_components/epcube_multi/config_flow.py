"""Config flow for the EP Cube Multi-Gateway integration.

Region dropdown (default US) + username + password only — no manual token
paste. Validates by performing a REAL headless login (captcha solve +
cloud auth) against the chosen region's host before the entry is created.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .auth import AuthExpiredError, CaptchaSolveError, LoginError, authenticate
from .const import (
    CONF_REGION,
    CONF_SURPLUS_MODE,
    DEFAULT_REGION,
    DEFAULT_SURPLUS_MODE,
    DOMAIN,
    REGIONS,
    SURPLUS_MODE_LABELS,
    SURPLUS_MODES,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In(list(REGIONS.keys())),
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)


async def _async_validate_login(hass: HomeAssistant, region: str, username: str, password: str) -> None:
    """Perform a real headless login against the region's host. Raises on failure."""
    base_url = REGIONS[region]
    await hass.async_add_executor_job(authenticate, base_url, username, password, _LOGGER)


class EpCubeMultiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EP Cube Multi-Gateway."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            region = user_input[CONF_REGION]
            username = user_input["username"]
            password = user_input["password"]

            unique_id = f"{region}:{username}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                await _async_validate_login(self.hass, region, username, password)
            except LoginError:
                errors["base"] = "invalid_auth"
            except CaptchaSolveError:
                errors["base"] = "captcha_failed"
            except AuthExpiredError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001 - surface as a clean config-flow error, not a stack trace
                _LOGGER.exception("Unexpected error validating EP Cube login")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"EP Cube ({region}) - {username}",
                    data={
                        CONF_REGION: region,
                        "username": username,
                        "password": password,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "EpCubeMultiOptionsFlow":
        return EpCubeMultiOptionsFlow()


class EpCubeMultiOptionsFlow(config_entries.OptionsFlow):
    """Options flow: choose what per-gateway/property 'surplus' means.

    Single choice applied to ALL gateways in the entry (one config entry =
    one account = one policy). Saving triggers an entry reload so sensors
    recompute with the new mode; unique_ids are unaffected.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            mode = user_input[CONF_SURPLUS_MODE]
            if mode not in SURPLUS_MODES:
                mode = DEFAULT_SURPLUS_MODE
            return self.async_create_entry(title="", data={CONF_SURPLUS_MODE: mode})

        config_entry = self.hass.config_entries.async_get_entry(self.handler)
        current_mode = config_entry.options.get(CONF_SURPLUS_MODE, DEFAULT_SURPLUS_MODE)
        if current_mode not in SURPLUS_MODES:
            current_mode = DEFAULT_SURPLUS_MODE

        schema = vol.Schema(
            {
                vol.Required(CONF_SURPLUS_MODE, default=current_mode): vol.In(
                    {mode: SURPLUS_MODE_LABELS[mode] for mode in SURPLUS_MODES}
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "load_note": (
                    'Note: "Load" is backup-circuit power, not whole-home load '
                    "(the EP Cube cloud API has no separate whole-home-load field)."
                ),
            },
        )
