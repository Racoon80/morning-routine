"""Morning Routine integration.

Auto-registers a Lovelace card so that installing this integration via HACS
also installs the frontend card — single-install UX.
"""
from __future__ import annotations

import logging
import os
from datetime import date

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.loader import async_get_integration

from .const import (
    CONF_HOLIDAY_RANGES,
    DOMAIN,
    SERVICE_RESET_SNOOZE,
    SERVICE_SET_HOLIDAY,
    SERVICE_SET_STEPS,
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
_RESOURCE_FLAG = f"{DOMAIN}_resource_registered"
_CARD_URL_KEY = f"{DOMAIN}_card_url"


async def _read_version(hass: HomeAssistant) -> str:
    # HA's integration loader caches manifest.json off the event loop, so we
    # avoid sync open() which is blocked since HA 2024.x.
    try:
        integration = await async_get_integration(hass, DOMAIN)
        return integration.version or "0"
    except Exception:
        return "0"


async def _register_frontend(hass: HomeAssistant) -> None:
    """Register static path + inject card script. Idempotent per HA session.

    Three layers so the card shows up in every HA configuration:
      1. Serve the JS as a static path
      2. add_extra_js_url   — loads in main HA frontend
      3. Lovelace resource  — required for the dashboard card picker to
         see the card in storage-mode dashboards (most users)

    Layers 1+2 happen once per HA session. Layer 3 is tracked separately and
    retried: `lovelace` is not a dependency of this integration, so during an
    early `async_setup` it is often not set up yet. The old code marked the
    whole registration done before that call, so one early miss was permanent
    and every dashboard ended up showing "Custom element doesn't exist:
    morning-routine-card".
    """
    card_url = hass.data.get(_CARD_URL_KEY)
    if card_url is None:
        version = await _read_version(hass)
        card_url = f"{FRONTEND_BASE}/morning-routine-card.js?v={version}"
        hass.data[_CARD_URL_KEY] = card_url

    if not hass.data.get(_FRONTEND_FLAG):
        hass.data[_FRONTEND_FLAG] = True
        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_BASE, FRONTEND_FS_PATH, cache_headers=False)]
        )
        add_extra_js_url(hass, card_url)
        _LOGGER.info("Morning Routine frontend registered (card %s)", card_url)

    await _register_card_resource(hass, card_url)


async def _register_card_resource(hass: HomeAssistant, card_url: str) -> None:
    """Add the Lovelace resource, retrying once HA has finished starting."""
    if hass.data.get(_RESOURCE_FLAG):
        return
    if await _ensure_lovelace_resource(hass, card_url):
        hass.data[_RESOURCE_FLAG] = True
        return
    if hass.is_running:
        _LOGGER.warning(
            "Could not register the Lovelace resource for the card. Add %s "
            "manually under Settings → Dashboards → Resources (type: "
            "JavaScript module) if the card shows as an unknown element.",
            card_url,
        )
        return

    async def _retry(_event) -> None:
        # Lovelace is set up by the time HA reports "started".
        if await _ensure_lovelace_resource(hass, card_url):
            hass.data[_RESOURCE_FLAG] = True
        else:
            _LOGGER.warning(
                "Could not register the Lovelace resource for the card. Add %s "
                "manually under Settings → Dashboards → Resources (type: "
                "JavaScript module).",
                card_url,
            )

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _retry)


async def _ensure_lovelace_resource(hass: HomeAssistant, url: str) -> bool:
    """Add the card URL to Lovelace storage-mode resources if missing.

    Without this the dashboard card picker shows the card as "still
    loading" because Lovelace only loads cards from its own resource
    list, ignoring add_extra_js_url. YAML-mode users manage resources
    themselves, so this is a no-op for them.
    """
    try:
        ll = hass.data.get("lovelace")
        if ll is None:
            return False
        # Newer HA exposes resources as ll.resources, older as ll["resources"].
        resources = getattr(ll, "resources", None)
        if resources is None and isinstance(ll, dict):
            resources = ll.get("resources")
        if resources is None:
            return False
        # Only storage mode supports programmatic resource management. YAML
        # mode users manage resources themselves, so treat that as done.
        store_mode = getattr(resources, "store", None)
        if store_mode is None:
            return True
        # Ensure resources are loaded; in modern HA this is already done at
        # startup but during an early-setup race we want to be safe.
        if hasattr(resources, "async_load") and not getattr(resources, "data", None):
            await resources.async_load()

        url_base = url.split("?", 1)[0]
        items = list(resources.async_items()) if hasattr(resources, "async_items") else []
        existing = next(
            (r for r in items if r.get("url", "").split("?", 1)[0] == url_base),
            None,
        )
        if existing:
            # Refresh the URL so the version query string is current.
            if existing.get("url") != url and hasattr(resources, "async_update_item"):
                await resources.async_update_item(
                    existing["id"], {"res_type": "module", "url": url}
                )
            return True
        if hasattr(resources, "async_create_item"):
            await resources.async_create_item({"res_type": "module", "url": url})
            _LOGGER.info("Registered Lovelace resource: %s", url)
            return True
        return False
    except Exception as err:  # noqa: BLE001 - never break setup over this
        _LOGGER.warning(
            "Could not auto-register Lovelace resource for the card: %s. "
            "Add %s manually under Settings → Dashboards → Resources.",
            err,
            url,
        )
        return False


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

    async def _reset_snooze(call) -> None:
        for c in hass.data[DOMAIN].values():
            await c.async_reset_snooze()

    async def _set_holiday(call) -> None:
        """Set or clear the manual holiday period. Used by the card's dialog.

        Same rules as the options form: one date on its own is a single day,
        reversed dates are swapped, and no dates at all clears the period.
        """
        def _read(value) -> date | None:
            if value in (None, ""):
                return None
            if isinstance(value, date):
                return value
            return date.fromisoformat(str(value)[:10])

        try:
            start = _read(call.data.get("start"))
            end = _read(call.data.get("end"))
        except (TypeError, ValueError) as err:
            raise ServiceValidationError(
                "start and end must be dates in YYYY-MM-DD form (or empty)"
            ) from err

        ranges: list[dict[str, str]] = []
        if start or end:
            first, last = start or end, end or start
            if first > last:
                first, last = last, first
            ranges = [{"start": first.isoformat(), "end": last.isoformat()}]

        for eid in list(hass.data[DOMAIN].keys()):
            target_entry = hass.config_entries.async_get_entry(eid)
            if target_entry is None:
                continue
            hass.config_entries.async_update_entry(
                target_entry,
                options={**target_entry.options, CONF_HOLIDAY_RANGES: ranges},
            )

    async def _set_steps(call) -> None:
        """Replace the entire step list. Used by the in-card editor."""
        from .const import CONF_STEPS, DAYS_ALL, DEFAULT_HOLIDAY_MODE, HOLIDAY_MODES
        import uuid

        raw_steps = call.data.get("steps", [])
        if not isinstance(raw_steps, list):
            return
        cleaned: list[dict] = []
        seen_ids: set[str] = set()
        for s in raw_steps:
            if not isinstance(s, dict):
                continue
            sid = s.get("id") or uuid.uuid4().hex
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            try:
                duration = max(1, min(600, int(s.get("duration", 15))))
            except (TypeError, ValueError):
                duration = 15
            start = s.get("start") or "07:30"
            # accept either "HH:MM" or "HH:MM:SS"
            if isinstance(start, str) and len(start) >= 5:
                start = start[:5]
            else:
                start = "07:30"
            days = s.get("days") or DAYS_ALL
            if not isinstance(days, list):
                days = DAYS_ALL
            days = [d for d in days if d in DAYS_ALL] or DAYS_ALL
            holiday_mode = s.get("holiday_mode", DEFAULT_HOLIDAY_MODE)
            if holiday_mode not in HOLIDAY_MODES:
                holiday_mode = DEFAULT_HOLIDAY_MODE
            cleaned.append({
                "id": sid,
                "name": str(s.get("name") or "").strip() or "Step",
                "name_lb": str(s.get("name_lb") or s.get("name") or "").strip(),
                "start": start,
                "duration": duration,
                "image": str(s.get("image") or "☕"),
                "days": days,
                "holiday_mode": holiday_mode,
            })

        # Apply to all entries (single-instance integration, but loop for safety)
        for eid in list(hass.data[DOMAIN].keys()):
            target_entry = hass.config_entries.async_get_entry(eid)
            if target_entry is None:
                continue
            new_options = {**target_entry.options, CONF_STEPS: cleaned}
            hass.config_entries.async_update_entry(target_entry, options=new_options)

    if not hass.services.has_service(DOMAIN, SERVICE_SKIP_STEP):
        hass.services.async_register(DOMAIN, SERVICE_SKIP_STEP, _skip_step)
        hass.services.async_register(DOMAIN, SERVICE_START_NOW, _start_now)
        hass.services.async_register(DOMAIN, SERVICE_SNOOZE, _snooze)
        hass.services.async_register(DOMAIN, SERVICE_SET_STEPS, _set_steps)
        hass.services.async_register(DOMAIN, SERVICE_SET_HOLIDAY, _set_holiday)
        hass.services.async_register(DOMAIN, SERVICE_RESET_SNOOZE, _reset_snooze)

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
        for svc in (
            SERVICE_SKIP_STEP,
            SERVICE_START_NOW,
            SERVICE_SNOOZE,
            SERVICE_SET_STEPS,
            SERVICE_SET_HOLIDAY,
            SERVICE_RESET_SNOOZE,
        ):
            hass.services.async_remove(DOMAIN, svc)
    return unload_ok
