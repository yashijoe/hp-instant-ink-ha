"""Tests that load the integration in Home Assistant's test harness.

Skipped when pytest-homeassistant-custom-component is not installed.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.config_entries import SOURCE_USER  # noqa: E402
from homeassistant.const import CONF_HOST  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.hp_instant_ink.api import (  # noqa: E402
    HPPrinterClient,
    HPPrinterConnectionError,
    PrinterData,
    PrinterIdentity,
)
from custom_components.hp_instant_ink.const import (  # noqa: E402
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
    DOMAIN,
)

SERIAL = "TESTSERIAL1"
IDENTITY = PrinterIdentity(model="HP Envy 6100e series", serial=SERIAL, firmware="1.0")

ENTRY_DATA = {
    CONF_HOST: "192.168.1.50",
    CONF_PLAN_PAGES: 50,
    CONF_ROLLOVER_MAX: 150,
    CONF_BILLING_DAY: 5,
    CONF_OVERAGE_BLOCK_SIZE: 10,
    CONF_OVERAGE_BLOCK_PRICE: 1.5,
    CONF_CARRY_OVERAGE_LEFTOVER: False,
    CONF_INITIAL_PRINTED: 12,
    CONF_INITIAL_ROLLOVER: 30,
    CONF_MODEL: IDENTITY.model,
    CONF_SERIAL: SERIAL,
}


def printer(total: int) -> PrinterData:
    return PrinterData(
        total_pages=total, mono_pages=225, color_pages=337, supplies={"CMY": 80, "K": 90}
    )


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def mock_printer():
    with (
        patch.object(HPPrinterClient, "async_get_identity", AsyncMock(return_value=IDENTITY)),
        patch.object(
            HPPrinterClient, "async_get_data", AsyncMock(return_value=printer(562))
        ) as get_data,
    ):
        yield get_data


def state_of(hass, key: str):
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_{key}")
    assert entity_id, f"no entity for {key}"
    return hass.states.get(entity_id)


async def setup_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id=SERIAL, title=IDENTITY.model
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow_creates_entry(hass, mock_printer):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "http://192.168.1.50/",
            CONF_PLAN_PAGES: 50.0,
            CONF_ROLLOVER_MAX: 150.0,
            CONF_BILLING_DAY: 5.0,
            CONF_OVERAGE_BLOCK_SIZE: 10.0,
            CONF_OVERAGE_BLOCK_PRICE: 1.5,
            CONF_CARRY_OVERAGE_LEFTOVER: False,
            CONF_INITIAL_PRINTED: 12.0,
            CONF_INITIAL_ROLLOVER: 30.0,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == IDENTITY.model
    assert result["data"] == ENTRY_DATA
    assert isinstance(result["data"][CONF_PLAN_PAGES], int)


async def test_config_flow_reports_unreachable_printer(hass):
    with patch.object(
        HPPrinterClient, "async_get_identity", AsyncMock(side_effect=HPPrinterConnectionError)
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {key: value for key, value in ENTRY_DATA.items() if key not in (CONF_MODEL, CONF_SERIAL)},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_sensors_and_renewal(hass, mock_printer, freezer):
    freezer.move_to("2026-11-12 12:00:00+00:00")
    entry = await setup_entry(hass)

    assert state_of(hass, "total_pages").state == "562"
    assert state_of(hass, "period_pages").state == "12"
    assert state_of(hass, "plan_remaining").state == "38"
    assert state_of(hass, "rollover_remaining").state == "30"
    assert state_of(hass, "rollover_projected").state == "68"
    assert state_of(hass, "free_remaining").state == "68"
    assert state_of(hass, "overage_pages").state == "0"
    assert float(state_of(hass, "overage_cost").state) == 0
    assert state_of(hass, "days_remaining").state == "23"
    assert state_of(hass, "next_renewal").state == "2026-12-05"
    assert state_of(hass, "period_start").state == "2026-11-05"
    assert state_of(hass, "last_period_pages").state == "unknown"
    assert state_of(hass, "ink_k").state == "90"
    assert state_of(hass, "ink_cmy").state == "80"

    # 20 more pages, then the renewal day arrives while the printer is off.
    coordinator = entry.runtime_data
    mock_printer.return_value = printer(582)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert state_of(hass, "period_pages").state == "32"

    freezer.move_to("2026-12-05 12:00:00+00:00")
    mock_printer.side_effect = HPPrinterConnectionError("off")
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert state_of(hass, "period_pages").state == "0"
    assert state_of(hass, "rollover_remaining").state == "48"
    assert state_of(hass, "period_start").state == "2026-12-05"
    last = state_of(hass, "last_period_pages")
    assert last.state == "32"
    assert last.attributes["history"][0]["start"] == "2026-11-05"
    assert last.attributes["history"][0]["accumulated"] == 18
    assert state_of(hass, "total_pages").attributes["printer_online"] is False


async def test_history_survives_restart(hass, mock_printer, freezer):
    freezer.move_to("2026-11-12 12:00:00+00:00")
    entry = await setup_entry(hass)
    freezer.move_to("2026-12-06 12:00:00+00:00")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert state_of(hass, "last_period_pages").state == "12"

    await entry.runtime_data._store.async_save(entry.runtime_data._data_to_save())
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert state_of(hass, "last_period_pages").state == "12"
    assert state_of(hass, "rollover_remaining").state == "68"


async def test_adjust_service(hass, mock_printer, freezer):
    freezer.move_to("2026-11-12 12:00:00+00:00")
    await setup_entry(hass)
    await hass.services.async_call(
        DOMAIN,
        "adjust",
        {"printed_pages": 60, "rollover_pages": 5, "period_start": date(2026, 11, 8)},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert state_of(hass, "period_pages").state == "60"
    assert state_of(hass, "rollover_remaining").state == "0"
    assert state_of(hass, "overage_pages").state == "5"
    assert float(state_of(hass, "overage_cost").state) == 1.5
    assert state_of(hass, "period_start").state == "2026-11-08"


async def test_options_change_the_plan(hass, mock_printer, freezer):
    freezer.move_to("2026-11-12 12:00:00+00:00")
    entry = await setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.1.60",
            CONF_PLAN_PAGES: 100.0,
            CONF_ROLLOVER_MAX: 300.0,
            CONF_BILLING_DAY: 5.0,
            CONF_OVERAGE_BLOCK_SIZE: 10.0,
            CONF_OVERAGE_BLOCK_PRICE: 1.5,
            CONF_CARRY_OVERAGE_LEFTOVER: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.runtime_data.client.host == "192.168.1.60"
    assert state_of(hass, "plan_remaining").state == "88"
    assert state_of(hass, "period_pages").state == "12"
