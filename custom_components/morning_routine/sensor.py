"""Sensors exposed by Morning Routine."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_HOLIDAY,
    ATTR_IMAGE,
    ATTR_NAME,
    ATTR_NAME_LB,
    ATTR_NEXT_STEP,
    ATTR_PROGRESS,
    ATTR_TIME_LEFT,
    CONF_HIGH_CONTRAST,
    DOMAIN,
)
from .coordinator import MorningRoutineCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MorningRoutineCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            ActiveStepSensor(coordinator, entry),
            ProgressSensor(coordinator, entry),
            TimeLeftSensor(coordinator, entry),
        ]
    )


class _Base(CoordinatorEntity[MorningRoutineCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _suffix: str = ""

    def __init__(self, coordinator: MorningRoutineCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{self._suffix}"
        # Stable, language-independent entity_id slug.
        # Existing installs keep their old (translated) entity_id thanks to the
        # entity registry — only fresh installs benefit. The card finds either
        # version via the _mr_role marker attribute, so this is just for tidiness.
        self._attr_suggested_object_id = f"morning_routine_{self._suffix}"


class ActiveStepSensor(_Base):
    _attr_translation_key = "active_step"
    _attr_icon = "mdi:run-fast"
    _suffix = "active_step"

    @property
    def native_value(self) -> str | None:
        active = self.coordinator.data.get("active") if self.coordinator.data else None
        return active["name"] if active else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        active = data.get("active")
        # Raw steps list (with id + days) so the in-card editor can edit them
        raw_steps = list(self._entry.options.get("steps", self._entry.data.get("steps", [])))
        return {
            "_mr_role": "active_step",
            ATTR_NAME: active["name"] if active else None,
            ATTR_NAME_LB: active["name_lb"] if active else None,
            ATTR_IMAGE: active["image"] if active else None,
            ATTR_PROGRESS: data.get("progress", 0.0),
            ATTR_TIME_LEFT: data.get("time_left", 0),
            ATTR_NEXT_STEP: data.get("next"),
            "schedule": data.get("schedule", []),
            # True while today counts as a holiday (date range or holiday
            # entity). The card uses it for the badge; automations can use it
            # as a plain template condition.
            ATTR_HOLIDAY: bool(data.get("holiday", False)),
            "all_steps": raw_steps,
            "entry_id": self._entry.entry_id,
            # Integration-wide UI flag — read by the Lovelace card so users can
            # opt into high contrast once for all dashboards instead of editing
            # every card individually.
            "ui_high_contrast": bool(self._entry.options.get(CONF_HIGH_CONTRAST, False)),
        }


class ProgressSensor(_Base):
    _attr_translation_key = "progress"
    _attr_icon = "mdi:progress-clock"
    _attr_native_unit_of_measurement = "%"
    _suffix = "progress"

    @property
    def native_value(self) -> float:
        if not self.coordinator.data:
            return 0.0
        return round(self.coordinator.data.get("progress", 0.0) * 100, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"_mr_role": "progress"}


class TimeLeftSensor(_Base):
    _attr_translation_key = "time_left"
    _attr_icon = "mdi:timer-sand"
    _attr_native_unit_of_measurement = "s"
    _suffix = "time_left"

    @property
    def native_value(self) -> int:
        if not self.coordinator.data:
            return 0
        return int(self.coordinator.data.get("time_left", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"_mr_role": "time_left"}
