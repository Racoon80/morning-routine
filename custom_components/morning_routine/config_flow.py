"""Config + options flow for Morning Routine.

Single-instance integration. The initial install creates an empty routine
with sensible default steps; all real configuration happens in Options.
"""
from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CHIME_ENABLED,
    CONF_DAYS,
    CONF_DURATION,
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
    DEFAULT_LANGUAGE,
    DEFAULT_PREWARN_SECONDS,
    DOMAIN,
)

BUNDLED = "/morning_routine_frontend/images"

DEFAULT_STEPS = [
    {
        CONF_NAME: "Kaffee",
        CONF_NAME_LB: "Kaffi",
        CONF_START: "07:30",
        CONF_DURATION: 15,
        CONF_IMAGE: f"{BUNDLED}/coffee.svg",
        CONF_DAYS: DAYS_ALL,
    },
    {
        CONF_NAME: "Anziehen",
        CONF_NAME_LB: "Undoen",
        CONF_START: "07:45",
        CONF_DURATION: 10,
        CONF_IMAGE: f"{BUNDLED}/clothes.svg",
        CONF_DAYS: DAYS_ALL,
    },
    {
        CONF_NAME: "Zähne putzen",
        CONF_NAME_LB: "Zänn pëtzen",
        CONF_START: "07:55",
        CONF_DURATION: 5,
        CONF_IMAGE: f"{BUNDLED}/teeth.svg",
        CONF_DAYS: DAYS_ALL,
    },
]


class MorningRoutineConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
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
    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_step", "edit_step", "remove_step", "settings"],
        )

    # ── add ──────────────────────────────────────────────────────────────────
    async def async_step_add_step(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            user_input["id"] = uuid.uuid4().hex
            self._steps.append(user_input)
            return await self._save_and_exit()
        return self.async_show_form(step_id="add_step", data_schema=self._step_schema())

    # ── edit ─────────────────────────────────────────────────────────────────
    async def async_step_edit_step(self, user_input: dict | None = None) -> FlowResult:
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

    async def async_step_edit_form(self, user_input: dict | None = None) -> FlowResult:
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
    async def async_step_remove_step(self, user_input: dict | None = None) -> FlowResult:
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
    async def async_step_settings(self, user_input: dict | None = None) -> FlowResult:
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

    # ── helpers ──────────────────────────────────────────────────────────────
    async def _save_and_exit(self) -> FlowResult:
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
                    CONF_IMAGE, default=d.get(CONF_IMAGE, f"{BUNDLED}/coffee.svg")
                ): str,
                vol.Optional(
                    CONF_DAYS, default=d.get(CONF_DAYS, DAYS_ALL)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[{"value": d, "label": d} for d in DAYS_ALL],
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )
