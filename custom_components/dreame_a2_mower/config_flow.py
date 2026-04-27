"""Config flow for the Dreame A2 Mower integration.

F1: minimal user-step flow. Just collects cloud credentials + country.
F4 (settings) extends this with options-flow for archive retention and
station bearing.

Per spec §5.9 credential discipline: credentials are stored in HA's
encrypted-at-rest config-entry secrets via the standard
``CONF_USERNAME`` / ``CONF_PASSWORD`` constants.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_COUNTRY,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_COUNTRY,
    DEFAULT_NAME,
    DOMAIN,
    LOGGER,
)


class DreameA2MowerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup conversation."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: collect cloud credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # F1: no live validation yet — that's added in F1.4 once the
            # cloud client exists. For now, just accept what's entered.
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=DEFAULT_NAME,
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_COUNTRY, default=DEFAULT_COUNTRY): vol.In(
                        ["eu", "us", "cn", "ru", "i2", "sg", "de"]
                    ),
                }
            ),
            errors=errors,
        )
