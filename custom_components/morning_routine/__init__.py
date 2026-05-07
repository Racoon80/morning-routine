"""Morning Routine integration.

Auto-registers a Lovelace card so that installing this integration via HACS
also installs the frontend card — single-install UX.
"""
from __future__ import annotations

import logging
import os

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    SERVICE_SKIP_STEP,
    SERVICE_SNOOZE,
    SERVICE_START_NOW,
)
from .coordinator import MorningRoutineCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

FRONTEND_BASE = "/morning_routine_frontend"
FRONTEND_FS_PATH = os.path.join(os.path.dirname(__file__), "frontend")
_FRONTEND_FLAG = f"{DOMAIN}_frontend_registered"


def _read_version() -> str:
    try:
        import json
        with open(os.path.join(os.path.dirname(__file__), "manifest.json")) as f:
            return json.load(f).get("version", "0")
    except Exception:
        return "0"


async def _register_frontend(hass: HomeAssistant) -> None:
    """Register static path + inject card script. Idempotent per HA session."""
    if hass.data.get(_FRONTEND_FLAG):
        return
    hass.data[_FRONTEND_FLAG] = True
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_BASE, FRONTEND_FS_PATH, cache_headers=False)]
    )
    # Version query string busts browser cache on integration updates.
    add_extra_js_url(hass, f"{FRONTEND_BASE}/morning-routine-card.js?v={_read_version()}")
    _LOGGER.info("Morning Routine frontend registered (card v%s)", _read_version())


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    await _register_frontend(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Morning Routine from a config entry."""
    # Defensive: also register here in case async_setup didn't run for some reason.
    await _register_frontend(hass)

    coordinator = MorningRoutineCoordinator(hass, entry)
    await coordinator.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _skip_step(call) -> None:
        for c in hass.data[DOMAIN].values():
            await c.async_skip_step()

    async def _start_now(call) -> None:
        for c in hass.data[DOMAIN].values():
            await c.async_start_now()

    async def _snooze(call) -> None:
        minutes = call.data.get("minutes", 5)
        for c in hass.data[DOMAIN].values():
            await c.async_snooze(minutes)

    if not hass.services.has_service(DOMAIN, SERVICE_SKIP_STEP):
        hass.services.async_register(DOMAIN, SERVICE_SKIP_STEP, _skip_step)
        hass.services.async_register(DOMAIN, SERVICE_START_NOW, _start_now)
        hass.services.async_register(DOMAIN, SERVICE_SNOOZE, _snooze)

    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: MorningRoutineCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()
    if not hass.data[DOMAIN]:
        for svc in (SERVICE_SKIP_STEP, SERVICE_START_NOW, SERVICE_SNOOZE):
            hass.services.async_remove(DOMAIN, svc)
    return unload_ok
