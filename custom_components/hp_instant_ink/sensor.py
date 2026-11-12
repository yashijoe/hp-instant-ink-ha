"""Sensors for the HP Instant Ink integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CONF_HOST, PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MODEL, CONF_SERIAL, DOMAIN, HISTORY_ATTRIBUTE_LIMIT
from .coordinator import HPInstantInkConfigEntry, HPInstantInkCoordinator, InkData

INK_TRANSLATION_KEYS = {
    "K": "ink_black",
    "CMY": "ink_tricolor",
    "C": "ink_cyan",
    "M": "ink_magenta",
    "Y": "ink_yellow",
}


@dataclass(frozen=True, kw_only=True)
class HPInkSensorDescription(SensorEntityDescription):
    """Describes a sensor and how to read its value."""

    value_fn: Callable[[InkData], int | float | date | None]
    attributes_fn: Callable[[InkData], dict[str, Any]] | None = None


def _last_period(data: InkData) -> int | None:
    return data.history[0]["printed"] if data.history else None


def _history_attributes(data: InkData) -> dict[str, Any]:
    return {"history": data.history[:HISTORY_ATTRIBUTE_LIMIT]}


SENSORS: tuple[HPInkSensorDescription, ...] = (
    HPInkSensorDescription(
        key="total_pages",
        translation_key="total_pages",
        icon="mdi:printer",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.total_pages,
        attributes_fn=lambda data: {
            "monochrome": data.mono_pages,
            "color": data.color_pages,
            "printer_online": data.printer_online,
        },
    ),
    HPInkSensorDescription(
        key="period_pages",
        translation_key="period_pages",
        icon="mdi:file-document-multiple",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.status.printed,
    ),
    HPInkSensorDescription(
        key="plan_remaining",
        translation_key="plan_remaining",
        icon="mdi:file-check",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.plan_remaining,
        attributes_fn=lambda data: {"plan_pages": data.status.plan_pages},
    ),
    HPInkSensorDescription(
        key="rollover_remaining",
        translation_key="rollover_remaining",
        icon="mdi:file-plus",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.rollover_remaining,
        attributes_fn=lambda data: {
            "at_period_start": data.status.rollover_start,
            "used_this_period": data.status.rollover_used,
        },
    ),
    HPInkSensorDescription(
        key="rollover_projected",
        translation_key="rollover_projected",
        icon="mdi:file-arrow-up-down",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.rollover_projected,
    ),
    HPInkSensorDescription(
        key="free_remaining",
        translation_key="free_remaining",
        icon="mdi:file-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.free_remaining,
    ),
    HPInkSensorDescription(
        key="overage_pages",
        translation_key="overage_pages",
        icon="mdi:file-alert",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.overage_pages,
        attributes_fn=lambda data: {
            "blocks": data.status.overage_blocks,
            "pages_left_in_block": data.status.overage_leftover,
        },
    ),
    HPInkSensorDescription(
        key="overage_cost",
        translation_key="overage_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: data.status.overage_cost,
    ),
    HPInkSensorDescription(
        key="days_remaining",
        translation_key="days_remaining",
        icon="mdi:calendar-clock",
        native_unit_of_measurement=UnitOfTime.DAYS,
        value_fn=lambda data: data.status.days_remaining,
    ),
    HPInkSensorDescription(
        key="next_renewal",
        translation_key="next_renewal",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: data.status.next_renewal,
    ),
    HPInkSensorDescription(
        key="period_start",
        translation_key="period_start",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.status.period_start,
    ),
    HPInkSensorDescription(
        key="last_period_pages",
        translation_key="last_period_pages",
        icon="mdi:history",
        value_fn=_last_period,
        attributes_fn=_history_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HPInstantInkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the sensors for one printer."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        HPInkSensor(coordinator, description) for description in SENSORS
    ]
    entities.extend(HPInkLevelSensor(coordinator, code) for code in coordinator.data.supplies)
    async_add_entities(entities)


class HPInkEntity(CoordinatorEntity[HPInstantInkCoordinator], SensorEntity):
    """Common device info for every sensor of a printer."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HPInstantInkCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        serial = entry.data.get(CONF_SERIAL, entry.entry_id)
        host = {**entry.data, **entry.options}[CONF_HOST]
        self._attr_unique_id = f"{serial}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            manufacturer="HP",
            model=entry.data.get(CONF_MODEL),
            name=entry.title,
            serial_number=entry.data.get(CONF_SERIAL),
            configuration_url=f"https://{host}",
        )


class HPInkSensor(HPInkEntity):
    """A plan or counter sensor."""

    entity_description: HPInkSensorDescription
    _unrecorded_attributes = frozenset({"history"})

    def __init__(
        self, coordinator: HPInstantInkCoordinator, description: HPInkSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        if description.device_class is SensorDeviceClass.MONETARY:
            self._attr_native_unit_of_measurement = coordinator.hass.config.currency

    @property
    def native_value(self) -> int | float | date | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the extra details."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)


class HPInkLevelSensor(HPInkEntity):
    """Ink level of one cartridge."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator: HPInstantInkCoordinator, code: str) -> None:
        super().__init__(coordinator, f"ink_{code.lower()}")
        self._code = code
        if code in INK_TRANSLATION_KEYS:
            self._attr_translation_key = INK_TRANSLATION_KEYS[code]
        else:
            self._attr_name = f"Ink {code}"

    @property
    def native_value(self) -> int | None:
        """Return the ink level in percent."""
        return self.coordinator.data.supplies.get(self._code)
