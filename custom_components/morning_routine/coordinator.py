"""Time tracker for Morning Routine.

Ticks once per second while a step is active to update progress.
Falls back to a slower polling interval when idle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHIME_ENABLED,
    CONF_DAYS,
    CONF_DURATION,
    CONF_IMAGE,
    CONF_NAME,
    CONF_NAME_LB,
    CONF_PREWARN_SECONDS,
    CONF_START,
    CONF_STEPS,
    CONF_TTS_ENABLED,
    CONF_TTS_TARGET,
    DAYS_ALL,
    DEFAULT_DURATION_MIN,
    DEFAULT_PREWARN_SECONDS,
    DOMAIN,
    EVENT_ROUTINE_FINISHED,
    EVENT_STEP_FINISHED,
    EVENT_STEP_PREWARN,
    EVENT_STEP_STARTED,
)

_LOGGER = logging.getLogger(__name__)

TICK_ACTIVE = timedelta(seconds=1)
TICK_IDLE = timedelta(seconds=30)


@dataclass
class Step:
    name: str
    name_lb: str
    start: time
    duration: timedelta
    image: str
    days: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        start_str = data[CONF_START]
        if isinstance(start_str, str):
            hh, mm = start_str.split(":")[:2]
            start = time(int(hh), int(mm))
        else:
            start = start_str
        duration_min = data.get(CONF_DURATION, DEFAULT_DURATION_MIN)
        return cls(
            name=data.get(CONF_NAME, ""),
            name_lb=data.get(CONF_NAME_LB, data.get(CONF_NAME, "")),
            start=start,
            duration=timedelta(minutes=int(duration_min)),
            image=data.get(CONF_IMAGE, ""),
            days=data.get(CONF_DAYS, DAYS_ALL),
        )

    def end(self, ref_date: datetime) -> datetime:
        return self.start_dt(ref_date) + self.duration

    def start_dt(self, ref_date: datetime) -> datetime:
        return ref_date.replace(
            hour=self.start.hour,
            minute=self.start.minute,
            second=0,
            microsecond=0,
        )

    def runs_today(self, now: datetime) -> bool:
        weekday = DAYS_ALL[now.weekday()]
        return weekday in self.days


class MorningRoutineCoordinator(DataUpdateCoordinator):
    """Tracks the active step and progress, fires events on transitions."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=TICK_IDLE)
        self.entry = entry
        self._unsub_tick = None
        self._steps: list[Step] = []
        self._active_idx: int | None = None
        self._snooze_offset = timedelta(0)
        self._prewarned_idx: int | None = None
        self._reload_steps()

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def async_start(self) -> None:
        await self.async_config_entry_first_refresh()
        # Tick every 1s unconditionally — this is a small dataclass compute,
        # no I/O, and the user expects a per-second countdown. Earlier we
        # tried debounced refresh on top of the coordinator's own update_interval
        # but the debouncer collapsed bursts and the sensor only re-wrote
        # state every several seconds. A direct interval is reliable.
        self._unsub_tick = async_track_time_interval(
            self.hass, self._tick, TICK_ACTIVE
        )

    async def async_stop(self) -> None:
        if self._unsub_tick:
            self._unsub_tick()
            self._unsub_tick = None

    # ── config ───────────────────────────────────────────────────────────────
    def _reload_steps(self) -> None:
        raw_steps = self.entry.options.get(
            CONF_STEPS, self.entry.data.get(CONF_STEPS, [])
        )
        self._steps = [Step.from_dict(s) for s in raw_steps]
        self._steps.sort(key=lambda s: s.start)

    # ── tick ─────────────────────────────────────────────────────────────────
    @callback
    def _tick(self, _now: datetime) -> None:
        # Bypass the request-refresh debouncer — it collapses our 1s ticks.
        # We compute fresh data, push it, and force-write the sensor state
        # so attribute-only changes (progress, time_left) propagate every tick.
        self.hass.async_create_task(self._async_force_refresh())

    async def _async_force_refresh(self) -> None:
        try:
            new_data = await self._async_update_data()
        except Exception:
            return
        self.async_set_updated_data(new_data)

    async def _async_update_data(self) -> dict[str, Any]:
        now = dt_util.now() - self._snooze_offset
        self._reload_steps()

        new_idx = self._compute_active(now)
        prev_idx = self._active_idx

        # Auto-reset snooze offset once the (shifted) routine has completed
        # its last step of the day. Without this, calling start_now or snooze
        # leaves the routine permanently shifted, and the next morning the
        # real-time schedule is off by however much was offset.
        if (
            self._snooze_offset != timedelta(0)
            and prev_idx is not None
            and new_idx is None
            and self._was_last_step_today(prev_idx, now)
        ):
            _LOGGER.info("Routine finished — clearing snooze offset (was %s)", self._snooze_offset)
            self._snooze_offset = timedelta(0)
            now = dt_util.now()
            new_idx = self._compute_active(now)

        await self._maybe_prewarn(now)

        if new_idx != prev_idx:
            await self._fire_transitions(prev_idx, new_idx, now)
            self._active_idx = new_idx

        if new_idx is None:
            return {
                "active": None,
                "progress": 0.0,
                "time_left": 0,
                "next": self._next_step_today(now),
                "schedule": self._today_schedule(now),
            }

        step = self._steps[new_idx]
        start_dt = step.start_dt(now)
        elapsed = (now - start_dt).total_seconds()
        total = step.duration.total_seconds()
        progress = max(0.0, min(1.0, elapsed / total)) if total > 0 else 1.0
        time_left = max(0, int(total - elapsed))

        return {
            "active": {
                "index": new_idx,
                "name": step.name,
                "name_lb": step.name_lb,
                "image": step.image,
                "duration": int(total),
            },
            "progress": progress,
            "time_left": time_left,
            "next": self._next_step_today(now, after_idx=new_idx),
            "schedule": self._today_schedule(now),
        }

    def _compute_active(self, now: datetime) -> int | None:
        for idx, step in enumerate(self._steps):
            if not step.runs_today(now):
                continue
            start_dt = step.start_dt(now)
            end_dt = start_dt + step.duration
            if start_dt <= now < end_dt:
                return idx
        return None

    def _today_schedule(self, now: datetime) -> list[dict]:
        """Return all steps that run today, with status flags for the card."""
        sched: list[dict] = []
        for idx, step in enumerate(self._steps):
            if not step.runs_today(now):
                continue
            start_dt = step.start_dt(now)
            end_dt = start_dt + step.duration
            if now >= end_dt:
                status = "done"
            elif start_dt <= now < end_dt:
                status = "active"
            else:
                status = "upcoming"
            sched.append({
                "index": idx,
                "name": step.name,
                "name_lb": step.name_lb,
                "image": step.image,
                "start": step.start.strftime("%H:%M"),
                "duration": int(step.duration.total_seconds()),
                "status": status,
            })
        return sched

    def _next_step_today(self, now: datetime, after_idx: int | None = None) -> dict | None:
        for idx, step in enumerate(self._steps):
            if after_idx is not None and idx <= after_idx:
                continue
            if not step.runs_today(now):
                continue
            if step.start_dt(now) > now:
                return {
                    "name": step.name,
                    "name_lb": step.name_lb,
                    "start": step.start.strftime("%H:%M"),
                    "image": step.image,
                }
        return None

    async def _fire_transitions(
        self, prev_idx: int | None, new_idx: int | None, now: datetime
    ) -> None:
        if prev_idx is not None:
            self.hass.bus.async_fire(
                EVENT_STEP_FINISHED,
                {"index": prev_idx, "name": self._steps[prev_idx].name},
            )
        if new_idx is not None:
            step = self._steps[new_idx]
            self.hass.bus.async_fire(
                EVENT_STEP_STARTED,
                {
                    "index": new_idx,
                    "name": step.name,
                    "name_lb": step.name_lb,
                    "image": step.image,
                    "duration": int(step.duration.total_seconds()),
                },
            )
            await self._maybe_announce(step)
        else:
            if prev_idx is not None and self._was_last_step_today(prev_idx, now):
                self.hass.bus.async_fire(EVENT_ROUTINE_FINISHED, {})

    def _was_last_step_today(self, idx: int, now: datetime) -> bool:
        for later_idx in range(idx + 1, len(self._steps)):
            if self._steps[later_idx].runs_today(now):
                return False
        return True

    async def _maybe_prewarn(self, now: datetime) -> None:
        """Fire a one-shot pre-warning event N seconds before each step."""
        prewarn = int(self.entry.options.get(CONF_PREWARN_SECONDS, DEFAULT_PREWARN_SECONDS))
        if prewarn <= 0:
            return
        for idx, step in enumerate(self._steps):
            if not step.runs_today(now):
                continue
            start_dt = step.start_dt(now)
            delta = (start_dt - now).total_seconds()
            if 0 < delta <= prewarn and self._prewarned_idx != idx:
                self._prewarned_idx = idx
                self.hass.bus.async_fire(
                    EVENT_STEP_PREWARN,
                    {
                        "index": idx,
                        "name": step.name,
                        "name_lb": step.name_lb,
                        "image": step.image,
                        "in_seconds": int(delta),
                    },
                )
                await self._announce_prewarn(step)
                return
        # reset prewarn marker once we leave the warning window
        if self._prewarned_idx is not None:
            step = self._steps[self._prewarned_idx]
            if step.start_dt(now) <= now:
                self._prewarned_idx = None

    async def _announce_prewarn(self, step: Step) -> None:
        opts = self.entry.options
        if not opts.get(CONF_TTS_ENABLED, False):
            return
        target = opts.get(CONF_TTS_TARGET)
        if not target:
            return
        tts_service = opts.get("tts_service", "tts.cloud_say")
        language = opts.get("language", "de")
        word = step.name_lb if language == "lb" else step.name
        prefix = {"de": "Gleich", "lb": "Geschwënn", "en": "Soon"}.get(language, "Soon")
        try:
            domain, service = tts_service.split(".", 1)
        except ValueError:
            return
        await self.hass.services.async_call(
            domain, service,
            {"entity_id": target, "message": f"{prefix}: {word}"},
            blocking=False,
        )

    async def _maybe_announce(self, step: Step) -> None:
        opts = self.entry.options
        if opts.get(CONF_CHIME_ENABLED, True):
            chime = opts.get("chime_entity")
            if chime:
                await self.hass.services.async_call(
                    "media_player", "play_media",
                    {
                        "entity_id": chime,
                        "media_content_id": opts.get("chime_url", ""),
                        "media_content_type": "music",
                    },
                    blocking=False,
                )
        if opts.get(CONF_TTS_ENABLED, False):
            target = opts.get(CONF_TTS_TARGET)
            tts_service = opts.get("tts_service", "tts.cloud_say")
            if target:
                language = opts.get("language", "de")
                msg = step.name_lb if language == "lb" else step.name
                domain, service = tts_service.split(".", 1)
                await self.hass.services.async_call(
                    domain, service,
                    {"entity_id": target, "message": f"Elo: {msg}"},
                    blocking=False,
                )

    # ── services ─────────────────────────────────────────────────────────────
    # The snooze_offset is subtracted from real time to get simulated time:
    #   simulated = real - offset
    # → positive offset moves the routine to an EARLIER simulated time.
    # → negative offset moves it to a LATER simulated time.

    async def async_skip_step(self) -> None:
        """End current step immediately by jumping past its end."""
        if self._active_idx is None:
            return
        step = self._steps[self._active_idx]
        now = dt_util.now()
        sim_now = now - self._snooze_offset
        end_dt = step.start_dt(sim_now) + step.duration
        target_sim = end_dt + timedelta(seconds=1)
        self._snooze_offset = now - target_sim
        await self.async_request_refresh()

    async def async_start_now(self) -> None:
        """Start the first step now regardless of clock time."""
        if not self._steps:
            return
        first = self._steps[0]
        now = dt_util.now()
        target_sim = first.start_dt(now) + timedelta(seconds=1)
        self._snooze_offset = now - target_sim
        await self.async_request_refresh()

    async def async_reset_snooze(self) -> None:
        """Clear any snooze offset so the routine returns to real clock time."""
        if self._snooze_offset != timedelta(0):
            _LOGGER.info("Manual reset of snooze offset (was %s)", self._snooze_offset)
            self._snooze_offset = timedelta(0)
        await self.async_request_refresh()

    async def async_snooze(self, minutes: int = 5) -> None:
        # Snooze pushes the routine forward in real time.
        # That means simulated time should appear EARLIER → offset increases.
        self._snooze_offset += timedelta(minutes=minutes)
        await self.async_request_refresh()
