"""Data coordinator: polls the printer and keeps the plan ledger up to date."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import HPPrinterClient, HPPrinterError
from .const import (
    CONF_BILLING_DAY,
    CONF_CARRY_OVERAGE_LEFTOVER,
    CONF_INITIAL_PRINTED,
    CONF_INITIAL_ROLLOVER,
    CONF_OVERAGE_BLOCK_PRICE,
    CONF_OVERAGE_BLOCK_SIZE,
    CONF_PLAN_PAGES,
    CONF_ROLLOVER_MAX,
    DEFAULT_OVERAGE_BLOCK_PRICE,
    DEFAULT_OVERAGE_BLOCK_SIZE,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .ledger import Ledger, PeriodStatus, PlanConfig

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

type HPInstantInkConfigEntry = ConfigEntry[HPInstantInkCoordinator]


@dataclass(frozen=True)
class InkData:
    """Everything the sensors show."""

    status: PeriodStatus
    total_pages: int
    mono_pages: int | None
    color_pages: int | None
    supplies: dict[str, int]
    history: list[dict[str, Any]]
    printer_online: bool


def storage_key(entry_id: str) -> str:
    """Return the storage file name for a config entry."""
    return f"{DOMAIN}.{entry_id}"


class HPInstantInkCoordinator(DataUpdateCoordinator[InkData]):
    """Polls one printer and does the plan accounting."""

    config_entry: HPInstantInkConfigEntry

    def __init__(self, hass: HomeAssistant, entry: HPInstantInkConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
        )
        settings = {**entry.data, **entry.options}
        self.client = HPPrinterClient(
            async_get_clientsession(hass, verify_ssl=False), settings[CONF_HOST]
        )
        self.plan = PlanConfig(
            plan_pages=int(settings[CONF_PLAN_PAGES]),
            rollover_max=int(settings[CONF_ROLLOVER_MAX]),
            billing_day=int(settings[CONF_BILLING_DAY]),
            overage_block_size=int(
                settings.get(CONF_OVERAGE_BLOCK_SIZE, DEFAULT_OVERAGE_BLOCK_SIZE)
            ),
            overage_block_price=float(
                settings.get(CONF_OVERAGE_BLOCK_PRICE, DEFAULT_OVERAGE_BLOCK_PRICE)
            ),
            carry_overage_leftover=bool(settings.get(CONF_CARRY_OVERAGE_LEFTOVER, False)),
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        self.ledger = Ledger(self.plan)
        self.supplies: dict[str, int] = {}
        self._mono: int | None = None
        self._color: int | None = None
        self._was_online = True

    async def async_load(self) -> None:
        """Restore the ledger saved on disk."""
        stored = await self._store.async_load() or {}
        self.ledger = Ledger(self.plan, stored.get("ledger"))
        self.supplies = dict(stored.get("supplies", {}))
        if not self.ledger.initialised:
            self.ledger.set_initial(
                self.config_entry.data.get(CONF_INITIAL_PRINTED, 0),
                self.config_entry.data.get(CONF_INITIAL_ROLLOVER, 0),
            )

    def _data_to_save(self) -> dict[str, Any]:
        return {"ledger": self.ledger.as_dict(), "supplies": self.supplies}

    def _build(self, today: date, online: bool) -> InkData:
        return InkData(
            status=self.ledger.status(today),
            total_pages=self.ledger.last_total or 0,
            mono_pages=self._mono,
            color_pages=self._color,
            supplies=dict(self.supplies),
            history=list(reversed(self.ledger.history)),
            printer_online=online,
        )

    async def _async_update_data(self) -> InkData:
        total: int | None = None
        online = True
        try:
            printer = await self.client.async_get_data()
        except HPPrinterError as err:
            online = False
            if self.ledger.last_total is None:
                raise UpdateFailed(f"No reading from the printer yet: {err}") from err
            if self._was_online:
                _LOGGER.info("Printer unreachable, keeping the last known values: %s", err)
        else:
            total = printer.total_pages
            self._mono, self._color = printer.mono_pages, printer.color_pages
            if printer.supplies and printer.supplies != self.supplies:
                self.supplies = dict(printer.supplies)
                self._store.async_delay_save(self._data_to_save, 10)
        self._was_online = online

        today = dt_util.now().date()
        if self.ledger.update(today, total):
            self._store.async_delay_save(self._data_to_save, 10)
        return self._build(today, online)

    async def async_adjust(
        self,
        *,
        printed: int | None = None,
        rollover: int | None = None,
        period_start: date | None = None,
    ) -> None:
        """Correct the current period and refresh the sensors."""
        self.ledger.adjust(printed=printed, rollover=rollover, period_start=period_start)
        today = dt_util.now().date()
        self.ledger.update(today, None)
        await self._store.async_save(self._data_to_save())
        online = self.data.printer_online if self.data else True
        self.async_set_updated_data(self._build(today, online))
