"""HP Instant Ink: local page counter and plan tracking for Home Assistant."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_PERIOD_START,
    ATTR_PRINTED_PAGES,
    ATTR_ROLLOVER_PAGES,
    DOMAIN,
    SERVICE_ADJUST,
)
from .coordinator import (
    STORAGE_VERSION,
    HPInstantInkConfigEntry,
    HPInstantInkCoordinator,
    storage_key,
)

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ADJUST_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_PRINTED_PAGES): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_ROLLOVER_PAGES): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_PERIOD_START): cv.date,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the service used to align the counters with the HP account."""

    async def async_adjust(call: ServiceCall) -> None:
        entries: list[HPInstantInkConfigEntry] = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]
        if entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID):
            entries = [entry for entry in entries if entry.entry_id == entry_id]
        if len(entries) != 1:
            raise ServiceValidationError(
                "Specify config_entry_id: found "
                f"{len(entries)} loaded HP Instant Ink printers"
            )
        try:
            await entries[0].runtime_data.async_adjust(
                printed=call.data.get(ATTR_PRINTED_PAGES),
                rollover=call.data.get(ATTR_ROLLOVER_PAGES),
                period_start=call.data.get(ATTR_PERIOD_START),
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    hass.services.async_register(DOMAIN, SERVICE_ADJUST, async_adjust, schema=ADJUST_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HPInstantInkConfigEntry) -> bool:
    """Set up a printer from a config entry."""
    coordinator = HPInstantInkCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_change))
    return True


async def _async_reload_on_change(hass: HomeAssistant, entry: HPInstantInkConfigEntry) -> None:
    """Reload when the plan settings are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HPInstantInkConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: HPInstantInkConfigEntry) -> None:
    """Delete the saved history when the printer is removed."""
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()
