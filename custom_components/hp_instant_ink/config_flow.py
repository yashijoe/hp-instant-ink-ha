"""Config flow: printer address and plan details, all entered by hand."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)

from .api import (
    HPPrinterClient,
    HPPrinterConnectionError,
    HPPrinterError,
    HPPrinterUnsupportedError,
    PrinterIdentity,
    normalize_host,
)
from .const import (
    CONF_BILLING_DAY,
    CONF_CARRY_OVERAGE_LEFTOVER,
    CONF_INITIAL_PRINTED,
    CONF_INITIAL_ROLLOVER,
    CONF_MODEL,
    CONF_OVERAGE_BLOCK_PRICE,
    CONF_OVERAGE_BLOCK_SIZE,
    CONF_PLAN_PAGES,
    CONF_ROLLOVER_MAX,
    CONF_SERIAL,
    DEFAULT_OVERAGE_BLOCK_PRICE,
    DEFAULT_OVERAGE_BLOCK_SIZE,
    DEFAULT_PLAN_PAGES,
    DEFAULT_ROLLOVER_MAX,
    DOMAIN,
)

INT_KEYS = (
    CONF_PLAN_PAGES,
    CONF_ROLLOVER_MAX,
    CONF_BILLING_DAY,
    CONF_OVERAGE_BLOCK_SIZE,
    CONF_INITIAL_PRINTED,
    CONF_INITIAL_ROLLOVER,
)


def _number(minimum: float, maximum: float, step: float = 1) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=minimum, max=maximum, step=step, mode=NumberSelectorMode.BOX)
    )


def _plan_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Fields shared by the first setup and the options form."""
    return {
        vol.Required(
            CONF_PLAN_PAGES, default=defaults.get(CONF_PLAN_PAGES, DEFAULT_PLAN_PAGES)
        ): _number(1, 5000),
        vol.Required(
            CONF_ROLLOVER_MAX, default=defaults.get(CONF_ROLLOVER_MAX, DEFAULT_ROLLOVER_MAX)
        ): _number(0, 15000),
        vol.Required(
            CONF_BILLING_DAY, default=defaults.get(CONF_BILLING_DAY, 1)
        ): _number(1, 31),
        vol.Required(
            CONF_OVERAGE_BLOCK_SIZE,
            default=defaults.get(CONF_OVERAGE_BLOCK_SIZE, DEFAULT_OVERAGE_BLOCK_SIZE),
        ): _number(1, 1000),
        vol.Required(
            CONF_OVERAGE_BLOCK_PRICE,
            default=defaults.get(CONF_OVERAGE_BLOCK_PRICE, DEFAULT_OVERAGE_BLOCK_PRICE),
        ): _number(0, 1000, 0.01),
        vol.Required(
            CONF_CARRY_OVERAGE_LEFTOVER,
            default=defaults.get(CONF_CARRY_OVERAGE_LEFTOVER, False),
        ): BooleanSelector(),
    }


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    """Number selectors return floats: store whole numbers as ints."""
    cleaned = dict(user_input)
    for key in INT_KEYS:
        if key in cleaned:
            cleaned[key] = int(cleaned[key])
    if CONF_HOST in cleaned:
        cleaned[CONF_HOST] = normalize_host(cleaned[CONF_HOST])
    return cleaned


class HPInstantInkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a printer."""

    VERSION = 1

    async def _async_identify(self, host: str) -> tuple[PrinterIdentity | None, str | None]:
        client = HPPrinterClient(async_get_clientsession(self.hass, verify_ssl=False), host)
        try:
            identity = await client.async_get_identity()
            await client.async_get_data()
        except HPPrinterConnectionError:
            return None, "cannot_connect"
        except HPPrinterUnsupportedError:
            return None, "unsupported"
        except HPPrinterError:
            return None, "unknown"
        return identity, None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the printer address and the plan details."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            identity, error = await self._async_identify(data[CONF_HOST])
            if identity is None:
                errors["base"] = error or "unknown"
            else:
                await self.async_set_unique_id(identity.serial)
                self._abort_if_unique_id_configured()
                data[CONF_MODEL] = identity.model
                data[CONF_SERIAL] = identity.serial
                return self.async_create_entry(title=identity.model, data=data)

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): TextSelector(),
                **_plan_fields(defaults),
                vol.Required(
                    CONF_INITIAL_PRINTED, default=defaults.get(CONF_INITIAL_PRINTED, 0)
                ): _number(0, 100000),
                vol.Required(
                    CONF_INITIAL_ROLLOVER, default=defaults.get(CONF_INITIAL_ROLLOVER, 0)
                ): _number(0, 15000),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        """Return the options flow."""
        return HPInstantInkOptionsFlow()


class HPInstantInkOptionsFlow(OptionsFlow):
    """Change the printer address or the plan details later."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the plan settings."""
        if user_input is not None:
            return self.async_create_entry(data=_clean(user_input))

        current = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=current.get(CONF_HOST, "")): TextSelector(),
                **_plan_fields(current),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
