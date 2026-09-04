"""Config + options flow for Morning Routine.

Single-instance integration. The initial install creates an empty routine
with sensible default steps; all real configuration happens in Options.
"""
from __future__ import annotations

import os
import uuid
from datetime import date
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_CHIME_ENABLED,
    CONF_DAYS,
    CONF_DURATION,
    CONF_HIGH_CONTRAST,
    CONF_HOLIDAY_ENTITY,
    CONF_HOLIDAY_FROM,
    CONF_HOLIDAY_MODE,
    CONF_HOLIDAY_RANGES,
    CONF_HOLIDAY_TO,
    CONF_IMAGE,
    CONF_LANGUAGE,
    CONF_NAME,
    CONF_NAME_LB,
    CONF_PREWARN_SECONDS,
    CONF_START,
    CONF_STEPS,
    CONF_TTS_ENABLED,
    CONF_TTS_TARGET,
    DAYS_ALL,
    DEFAULT_DURATION_MIN,
    DEFAULT_HOLIDAY_MODE,
    DEFAULT_LANGUAGE,
    DEFAULT_PREWARN_SECONDS,
    DOMAIN,
    HOLIDAY_MODE_SKIP,
    HOLIDAY_MODES,
)

BUNDLED = "/morning_routine_frontend/images"
BUNDLED_FS = os.path.join(os.path.dirname(__file__), "frontend", "images")
LOCAL_MORNING_DIR = "www/morning"

# Curated emoji set — value is the emoji itself, used directly as `image`.
# The card detects emoji vs URL by the absence of a "/" in the value.
EMOJI_OPTIONS: list[dict[str, str]] = [
    {"value": "☕", "label": "☕  Kaffee / Coffee"},
    {"value": "🍵", "label": "🍵  Tee / Tea"},
    {"value": "🥛", "label": "🥛  Milch / Milk"},
    {"value": "🥣", "label": "🥣  Müsli / Cereal"},
    {"value": "🥐", "label": "🥐  Croissant"},
    {"value": "🍞", "label": "🍞  Brot / Bread"},
    {"value": "🥚", "label": "🥚  Ei / Egg"},
    {"value": "🥞", "label": "🥞  Pfannkuchen / Pancakes"},
    {"value": "🍎", "label": "🍎  Apfel / Apple"},
    {"value": "🍌", "label": "🍌  Banane / Banana"},
    {"value": "🪥", "label": "🪥  Zähne putzen / Brush teeth"},
    {"value": "🧼", "label": "🧼  Hände waschen / Wash hands"},
    {"value": "🚿", "label": "🚿  Dusche / Shower"},
    {"value": "🛁", "label": "🛁  Bad / Bath"},
    {"value": "💧", "label": "💧  Trinken / Drink"},
    {"value": "👕", "label": "👕  T-Shirt"},
    {"value": "👖", "label": "👖  Hose / Pants"},
    {"value": "🧥", "label": "🧥  Jacke / Jacket"},
    {"value": "🧦", "label": "🧦  Socken / Socks"},
    {"value": "👟", "label": "👟  Schuhe / Shoes"},
    {"value": "🥾", "label": "🥾  Stiefel / Boots"},
    {"value": "🎒", "label": "🎒  Rucksack / Backpack"},
    {"value": "📚", "label": "📚  Bücher / Books"},
    {"value": "✏️", "label": "✏️  Hausaufgaben / Homework"},
    {"value": "🎨", "label": "🎨  Malen / Painting"},
    {"value": "🎮", "label": "🎮  Spielen / Playing"},
    {"value": "🧸", "label": "🧸  Spielzeug / Toys"},
    {"value": "📺", "label": "📺  Fernsehen / TV"},
    {"value": "🛏️", "label": "🛏️  Bett / Bed"},
    {"value": "😴", "label": "😴  Schlafen / Sleep"},
    {"value": "🚗", "label": "🚗  Auto / Car"},
    {"value": "🚌", "label": "🚌  Bus"},
    {"value": "🚲", "label": "🚲  Fahrrad / Bike"},
    {"value": "🏫", "label": "🏫  Schule / School"},
    {"value": "🌞", "label": "🌞  Sonne / Sun"},
    {"value": "🌙", "label": "🌙  Mond / Moon"},
    {"value": "⭐", "label": "⭐  Stern / Star"},
    {"value": "✅", "label": "✅  Fertig / Done"},
    {"value": "🎉", "label": "🎉  Party / Celebrate"},
    {"value": "💪", "label": "💪  Sport / Workout"},
]


def _image_options(hass: HomeAssistant | None) -> list[dict[str, str]]:
    """Build the picture dropdown.

    Order: emojis first (most users want these), then bundled SVG silhouettes,
    then any custom files placed in /config/www/morning/.
    """
    options: list[dict[str, str]] = list(EMOJI_OPTIONS)
    seen: set[str] = {o["value"] for o in options}

    # Bundled SVG silhouettes (kept for users who prefer monochrome)
    if os.path.isdir(BUNDLED_FS):
        for fname in sorted(os.listdir(BUNDLED_FS)):
            if not fname.lower().endswith((".svg", ".png", ".jpg", ".jpeg", ".webp")):
                continue
            stem = os.path.splitext(fname)[0]
            value = f"{BUNDLED}/{fname}"
            if value in seen:
                continue
            seen.add(value)
            options.append({"value": value, "label": f"🖼️  {stem.title()} (SVG)"})

    # User images in /config/www/morning/
    if hass is not None:
        local_dir = hass.config.path(LOCAL_MORNING_DIR)
        if os.path.isdir(local_dir):
            for fname in sorted(os.listdir(local_dir)):
                if not fname.lower().endswith((".svg", ".png", ".jpg", ".jpeg", ".webp")):
                    continue
                stem = os.path.splitext(fname)[0]
                value = f"/local/morning/{fname}"
                if value in seen:
                    continue
                seen.add(value)
                options.append({"value": value, "label": f"📁  {stem.title()}"})

    return options

DEFAULT_STEPS = [
    {
        CONF_NAME: "Kaffee",
        CONF_NAME_LB: "Kaffi",
        CONF_START: "07:30",
        CONF_DURATION: 15,
        CONF_IMAGE: "☕",
        CONF_DAYS: DAYS_ALL,
    },
    {
        CONF_NAME: "Anziehen",
        CONF_NAME_LB: "Undoen",
        CONF_START: "07:45",
        CONF_DURATION: 10,
        CONF_IMAGE: "👕",
        CONF_DAYS: DAYS_ALL,
    },
    {
        CONF_NAME: "Zähne putzen",
        CONF_NAME_LB: "Zänn pëtzen",
        CONF_START: "07:55",
        CONF_DURATION: 5,
        CONF_IMAGE: "🪥",
        CONF_DAYS: DAYS_ALL,
    },
    {
        CONF_NAME: "Schultasche",
        CONF_NAME_LB: "Schoulrucksak",
        CONF_START: "08:00",
        CONF_DURATION: 5,
        CONF_IMAGE: "🎒",
        CONF_DAYS: ["mon", "tue", "wed", "thu", "fri"],
        # School bag is a school-day thing — mute it during holidays.
        CONF_HOLIDAY_MODE: HOLIDAY_MODE_SKIP,
    },
]


class MorningRoutineConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            steps = [{**s, "id": uuid.uuid4().hex} for s in DEFAULT_STEPS]
            return self.async_create_entry(
                title="Morning Routine",
                data={CONF_STEPS: steps},
                options={
                    CONF_STEPS: steps,
                    CONF_LANGUAGE: user_input.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                    CONF_TTS_ENABLED: user_input.get(CONF_TTS_ENABLED, False),
                    CONF_CHIME_ENABLED: user_input.get(CONF_CHIME_ENABLED, True),
                },
            )

        schema = vol.Schema(
            {
                vol.Optional(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "de", "label": "Deutsch"},
                            {"value": "lb", "label": "Lëtzebuergesch"},
                            {"value": "en", "label": "English"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_TTS_ENABLED, default=False): bool,
                vol.Optional(CONF_CHIME_ENABLED, default=True): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return MorningRoutineOptionsFlow(entry)


class MorningRoutineOptionsFlow(OptionsFlow):
    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry
        self._steps: list[dict] = list(entry.options.get(CONF_STEPS, []))
        self._editing_id: str | None = None

    # ── menu ─────────────────────────────────────────────────────────────────
    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "add_step",
                "edit_step",
                "remove_step",
                "holidays",
                "settings",
                "display",
            ],
        )

    # ── add ──────────────────────────────────────────────────────────────────
    async def async_step_add_step(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is not None:
            user_input["id"] = uuid.uuid4().hex
            self._steps.append(user_input)
            return await self._save_and_exit()
        return self.async_show_form(step_id="add_step", data_schema=self._step_schema())

    # ── edit ─────────────────────────────────────────────────────────────────
    async def async_step_edit_step(self, user_input: dict | None = None) -> ConfigFlowResult:
        if not self._steps:
            return self.async_abort(reason="no_steps")
        if user_input is not None:
            self._editing_id = user_input["step_id"]
            return await self.async_step_edit_form()
        return self.async_show_form(
            step_id="edit_step",
            data_schema=vol.Schema(
                {
                    vol.Required("step_id"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": s["id"], "label": f'{s.get(CONF_START,"??:??")} — {s.get(CONF_NAME,"?")}'}
                                for s in self._steps
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_edit_form(self, user_input: dict | None = None) -> ConfigFlowResult:
        current = next((s for s in self._steps if s["id"] == self._editing_id), None)
        if current is None:
            return self.async_abort(reason="not_found")
        if user_input is not None:
            current.update(user_input)
            return await self._save_and_exit()
        return self.async_show_form(
            step_id="edit_form",
            data_schema=self._step_schema(defaults=current),
        )

    # ── remove ───────────────────────────────────────────────────────────────
    async def async_step_remove_step(self, user_input: dict | None = None) -> ConfigFlowResult:
        if not self._steps:
            return self.async_abort(reason="no_steps")
        if user_input is not None:
            self._steps = [s for s in self._steps if s["id"] != user_input["step_id"]]
            return await self._save_and_exit()
        return self.async_show_form(
            step_id="remove_step",
            data_schema=vol.Schema(
                {
                    vol.Required("step_id"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": s["id"], "label": f'{s.get(CONF_START,"??:??")} — {s.get(CONF_NAME,"?")}'}
                                for s in self._steps
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    # ── global settings ──────────────────────────────────────────────────────
    async def async_step_settings(self, user_input: dict | None = None) -> ConfigFlowResult:
        opts = self.entry.options
        if user_input is not None:
            new_opts = {**opts, **user_input, CONF_STEPS: self._steps}
            return self.async_create_entry(title="", data=new_opts)
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_LANGUAGE,
                    default=opts.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "de", "label": "Deutsch"},
                            {"value": "lb", "label": "Lëtzebuergesch"},
                            {"value": "en", "label": "English"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_TTS_ENABLED, default=opts.get(CONF_TTS_ENABLED, False)
                ): bool,
                vol.Optional(
                    CONF_TTS_TARGET, default=opts.get(CONF_TTS_TARGET, "")
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player")
                ),
                vol.Optional(
                    "tts_service", default=opts.get("tts_service", "tts.cloud_say")
                ): str,
                vol.Optional(
                    CONF_CHIME_ENABLED, default=opts.get(CONF_CHIME_ENABLED, True)
                ): bool,
                vol.Optional(
                    "chime_entity", default=opts.get("chime_entity", "")
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player")
                ),
                vol.Optional(
                    "chime_url", default=opts.get("chime_url", "")
                ): str,
                vol.Optional(
                    CONF_PREWARN_SECONDS,
                    default=opts.get(CONF_PREWARN_SECONDS, DEFAULT_PREWARN_SECONDS),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=600, step=10,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    # ── holidays ─────────────────────────────────────────────────────────────
    @staticmethod
    def _coerce_date(value: Any) -> date | None:
        """Read one date picker value. Empty -> None, garbage -> ValueError."""
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])

    async def async_step_holidays(self, user_input: dict | None = None) -> ConfigFlowResult:
        """One holiday period, set by hand, plus an optional day-off entity.

        Either source is enough to put the routine into holiday mode; each
        step then decides for itself (see the step form) whether it still
        runs, gets muted, or is holiday-only.
        """
        opts = self.entry.options
        errors: dict[str, str] = {}

        stored = [r for r in (opts.get(CONF_HOLIDAY_RANGES) or []) if isinstance(r, dict)]
        first = stored[0] if stored else {}
        from_value: Any = first.get("start", "")
        to_value: Any = first.get("end", "")
        entity_value = opts.get(CONF_HOLIDAY_ENTITY, "")

        if user_input is not None:
            # Re-render with what the user just entered, not the stored values,
            # so nothing they picked is thrown away by an error on another field.
            from_value = user_input.get(CONF_HOLIDAY_FROM, "")
            to_value = user_input.get(CONF_HOLIDAY_TO, "")
            entity_value = user_input.get(CONF_HOLIDAY_ENTITY, entity_value)
            try:
                start_date = self._coerce_date(from_value)
                end_date = self._coerce_date(to_value)
            except ValueError:
                errors["base"] = "invalid_holiday_dates"
            else:
                # One date on its own means that single day; two dates are a
                # period and are swapped if entered the wrong way round.
                ranges: list[dict[str, str]] = []
                if start_date or end_date:
                    first_date = start_date or end_date
                    last_date = end_date or start_date
                    if first_date > last_date:
                        first_date, last_date = last_date, first_date
                    ranges = [
                        {"start": first_date.isoformat(), "end": last_date.isoformat()}
                    ]
                new_opts = {
                    **opts,
                    CONF_STEPS: self._steps,
                    CONF_HOLIDAY_RANGES: ranges,
                    CONF_HOLIDAY_ENTITY: entity_value,
                }
                return self.async_create_entry(title="", data=new_opts)

        def _suggest(value: Any) -> dict[str, Any]:
            # DateSelector has no "empty" default, so an unset period is offered
            # as a suggestion instead of a hard default.
            return {"suggested_value": str(value)[:10] or None}

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_HOLIDAY_FROM, description=_suggest(from_value)
                ): selector.DateSelector(),
                vol.Optional(
                    CONF_HOLIDAY_TO, description=_suggest(to_value)
                ): selector.DateSelector(),
                vol.Optional(
                    CONF_HOLIDAY_ENTITY,
                    description={"suggested_value": entity_value or None},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["input_boolean", "binary_sensor", "calendar", "schedule"]
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="holidays", data_schema=schema, errors=errors
        )

    # ── display & accessibility ──────────────────────────────────────────────
    async def async_step_display(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Visual / accessibility settings, surfaced as its own menu entry so
        the high-contrast toggle is discoverable instead of buried under the
        sound-and-voice form."""
        opts = self.entry.options
        if user_input is not None:
            new_opts = {**opts, **user_input, CONF_STEPS: self._steps}
            return self.async_create_entry(title="", data=new_opts)
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_HIGH_CONTRAST,
                    default=opts.get(CONF_HIGH_CONTRAST, False),
                ): bool,
            }
        )
        return self.async_show_form(step_id="display", data_schema=schema)

    # ── helpers ──────────────────────────────────────────────────────────────
    async def _save_and_exit(self) -> ConfigFlowResult:
        new_opts = {**self.entry.options, CONF_STEPS: self._steps}
        return self.async_create_entry(title="", data=new_opts)

    def _step_schema(self, defaults: dict | None = None) -> vol.Schema:
        d = defaults or {}
        return vol.Schema(
            {
                vol.Required(CONF_NAME, default=d.get(CONF_NAME, "")): str,
                vol.Optional(CONF_NAME_LB, default=d.get(CONF_NAME_LB, "")): str,
                vol.Required(
                    CONF_START, default=d.get(CONF_START, "07:30")
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_DURATION, default=d.get(CONF_DURATION, DEFAULT_DURATION_MIN)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=120, step=1, unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_IMAGE, default=d.get(CONF_IMAGE, "☕")
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_image_options(self.hass),
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        sort=False,
                    )
                ),
                vol.Optional(
                    CONF_DAYS, default=d.get(CONF_DAYS, DAYS_ALL)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[{"value": d, "label": d} for d in DAYS_ALL],
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_HOLIDAY_MODE,
                    default=d.get(CONF_HOLIDAY_MODE, DEFAULT_HOLIDAY_MODE),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(HOLIDAY_MODES),
                        translation_key=CONF_HOLIDAY_MODE,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )
