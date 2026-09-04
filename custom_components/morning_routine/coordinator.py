"""Time tracker for Morning Routine.

Ticks once per second while a step is active to update progress.
Falls back to a slower polling interval when idle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
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
    CONF_HOLIDAY_ENTITY,
    CONF_HOLIDAY_MODE,
    CONF_HOLIDAY_RANGES,
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
    DEFAULT_HOLIDAY_MODE,
    DEFAULT_PREWARN_SECONDS,
    DOMAIN,
    EVENT_ROUTINE_FINISHED,
    EVENT_STEP_FINISHED,
    EVENT_STEP_PREWARN,
    EVENT_STEP_STARTED,
    HOLIDAY_MODE_ONLY,
    HOLIDAY_MODE_SKIP,
    HOLIDAY_MODES,
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
    holiday_mode: str = DEFAULT_HOLIDAY_MODE

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
            holiday_mode=(
                data.get(CONF_HOLIDAY_MODE, DEFAULT_HOLIDAY_MODE)
                if data.get(CONF_HOLIDAY_MODE) in HOLIDAY_MODES
                else DEFAULT_HOLIDAY_MODE
            ),
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

    def runs_on_weekday(self, now: datetime) -> bool:
        weekday = DAYS_ALL[now.weekday()]
        return weekday in self.days

    def holiday_allows(self, is_holiday: bool) -> bool:
        """Whether this step may run given today's holiday state.

        Steps default to HOLIDAY_MODE_ALWAYS, so installs that never touch
        the holiday settings keep behaving exactly as before.
        """
        if is_holiday:
            return self.holiday_mode != HOLIDAY_MODE_SKIP
        return self.holiday_mode != HOLIDAY_MODE_ONLY

    def runs_today(self, now: datetime, is_holiday: bool = False) -> bool:
        return self.holiday_allows(is_holiday) and self.runs_on_weekday(now)


class MorningRoutineCoordinator(DataUpdateCoordinator):
    """Tracks the active step and progress, fires events on transitions."""

    def __init__(self, hass: HomeAssistant, entry: MorningRoutineConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=TICK_IDLE)
        self.entry = entry
        self._unsub_tick = None
        self._steps: list[Step] = []
        self._active_idx: int | None = None
        self._snooze_offset = timedelta(0)
        self._prewarned: set[tuple[date, int]] = set()
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

    # ── holidays ─────────────────────────────────────────────────────────────
    def _is_holiday(self, now: datetime) -> bool:
        """True when today counts as a holiday.

        Two independent sources, either is enough:
          1. Date ranges stored in the options (school holidays, typed once)
          2. An HA entity (input_boolean, binary_sensor, calendar, schedule)
             that is "on" — lets the user flip a sick day / day off manually
             or drive it from a school-holiday calendar.
        """
        today = now.date()
        for rng in self.entry.options.get(CONF_HOLIDAY_RANGES, []) or []:
            if not isinstance(rng, dict):
                continue
            try:
                start = date.fromisoformat(str(rng.get("start")))
                end = date.fromisoformat(str(rng.get("end", rng.get("start"))))
            except (TypeError, ValueError):
                continue
            if start > end:
                start, end = end, start
            if start <= today <= end:
                return True

        entity_id = self.entry.options.get(CONF_HOLIDAY_ENTITY)
        if entity_id:
            state = self.hass.states.get(entity_id)
            # calendar/binary_sensor/input_boolean/schedule all use on/off.
            if state is not None and state.state == "on":
                return True
        return False

    async def _maybe_expire_holiday(self) -> None:
        """Drop a manual holiday period once its last day has passed.

        The date check alone already stops an old period from being active,
        but leaving it stored means the options form and the card's holiday
        dialog keep showing dates that read as "holiday still set" weeks
        later. Unreadable entries are dropped in the same pass.
        """
        ranges = self.entry.options.get(CONF_HOLIDAY_RANGES) or []
        if not ranges:
            return
        today = dt_util.now().date()
        kept: list[dict] = []
        for rng in ranges:
            if not isinstance(rng, dict):
                continue
            try:
                end = date.fromisoformat(str(rng.get("end", rng.get("start"))))
            except (TypeError, ValueError):
                continue
            if end >= today:
                kept.append(rng)
        if len(kept) == len(ranges):
            return
        _LOGGER.info("Holiday period is over — clearing it")
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, CONF_HOLIDAY_RANGES: kept},
        )

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
        await self._maybe_expire_holiday()
        is_holiday = self._is_holiday(now)

        new_idx = self._compute_active(now, is_holiday)
        prev_idx = self._active_idx

        # Auto-reset snooze offset once the (shifted) routine has completed
        # its last step of the day. Without this, calling start_now or snooze
        # leaves the routine permanently shifted, and the next morning the
        # real-time schedule is off by however much was offset.
        if (
            self._snooze_offset != timedelta(0)
            and prev_idx is not None
            and new_idx is None
            and self._was_last_step_today(prev_idx, now, is_holiday)
        ):
            _LOGGER.info("Routine finished — clearing snooze offset (was %s)", self._snooze_offset)
            self._snooze_offset = timedelta(0)
            now = dt_util.now()
            # Recompute: dropping the offset can move `now` to another date,
            # and with it into or out of a holiday range.
            is_holiday = self._is_holiday(now)
            new_idx = self._compute_active(now, is_holiday)

        await self._maybe_prewarn(now, is_holiday)

        if new_idx != prev_idx:
            await self._fire_transitions(prev_idx, new_idx, now, is_holiday)
            self._active_idx = new_idx

        if new_idx is None:
            return {
                "active": None,
                "progress": 0.0,
                "time_left": 0,
                "next": self._next_step_today(now, is_holiday),
                "schedule": self._today_schedule(now, is_holiday),
                "holiday": is_holiday,
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
            "next": self._next_step_today(now, is_holiday, after_idx=new_idx),
            "schedule": self._today_schedule(now, is_holiday),
            "holiday": is_holiday,
        }

    def _compute_active(self, now: datetime, is_holiday: bool = False) -> int | None:
        """Return the index of the active step.

        When step time-windows overlap, the step with the LATEST start time
        wins — a newer step takes focus over an older one that's still
        running. The overridden step appears as 'skipped' in the schedule.
        """
        in_window: list[tuple[datetime, int]] = []
        for idx, step in enumerate(self._steps):
            if not step.runs_today(now, is_holiday):
                continue
            start_dt = step.start_dt(now)
            end_dt = start_dt + step.duration
            if start_dt <= now < end_dt:
                in_window.append((start_dt, idx))
        if not in_window:
            return None
        in_window.sort(reverse=True)
        return in_window[0][1]

    def _today_schedule(self, now: datetime, is_holiday: bool = False) -> list[dict]:
        """Return all configured steps with status flags for the card.

        Status:
          done     — step's end time is in the past
          active   — step is currently the chosen active step
          skipped  — step's window contains 'now' but a later-starting step
                     supersedes it (overlap handling)
          upcoming — step's start time is in the future
          inactive — step is configured but does not run today (e.g. weekend
                     and the step is Mon–Fri only). Kept in the schedule so
                     the card remains useful on off-days as a reference.
          holiday  — step is muted by the holiday rules: either it is a
                     skip-on-holiday step during a holiday, or a
                     holiday-only step on a normal day.
        """
        active_idx = self._compute_active(now, is_holiday)
        sched: list[dict] = []
        for idx, step in enumerate(self._steps):
            if not step.holiday_allows(is_holiday):
                status = "holiday"
            elif not step.runs_on_weekday(now):
                status = "inactive"
            else:
                start_dt = step.start_dt(now)
                end_dt = start_dt + step.duration
                if now >= end_dt:
                    status = "done"
                elif start_dt <= now < end_dt:
                    status = "active" if idx == active_idx else "skipped"
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
                "holiday_mode": step.holiday_mode,
            })
        return sched

    def _next_step_today(
        self, now: datetime, is_holiday: bool = False, after_idx: int | None = None
    ) -> dict | None:
        for idx, step in enumerate(self._steps):
            if after_idx is not None and idx <= after_idx:
                continue
            if not step.runs_today(now, is_holiday):
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
        self,
        prev_idx: int | None,
        new_idx: int | None,
        now: datetime,
        is_holiday: bool = False,
    ) -> None:
        prev_step = self._step_at(prev_idx)
        if prev_step is not None:
            self.hass.bus.async_fire(
                EVENT_STEP_FINISHED,
                {"index": prev_idx, "name": prev_step.name},
            )
        step = self._step_at(new_idx)
        if step is not None:
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
        elif prev_step is not None:
            # Only a step that actually ran to its end finishes the routine.
            # Without the end check, muting the last step mid-run (parent
            # flips the holiday switch at 07:45) would fire routine_finished
            # and trigger reward/TV automations for a routine nobody did.
            reached_end = now >= prev_step.end(now)
            if reached_end and self._was_last_step_today(prev_idx, now, is_holiday):
                self.hass.bus.async_fire(EVENT_ROUTINE_FINISHED, {})

    def _step_at(self, idx: int | None) -> Step | None:
        """Safe lookup — the in-card editor can shrink the list between ticks,
        and an IndexError inside the tick is swallowed, freezing the card."""
        if idx is None or not 0 <= idx < len(self._steps):
            return None
        return self._steps[idx]

    def _was_last_step_today(
        self, idx: int, now: datetime, is_holiday: bool = False
    ) -> bool:
        for later_idx in range(idx + 1, len(self._steps)):
            if self._steps[later_idx].runs_today(now, is_holiday):
                return False
        return True

    async def _maybe_prewarn(self, now: datetime, is_holiday: bool = False) -> None:
        """Fire a one-shot pre-warning event N seconds before each step."""
        prewarn = int(self.entry.options.get(CONF_PREWARN_SECONDS, DEFAULT_PREWARN_SECONDS))
        if prewarn <= 0:
            return
        for idx, step in enumerate(self._steps):
            if not step.runs_today(now, is_holiday):
                continue
            start_dt = step.start_dt(now)
            delta = (start_dt - now).total_seconds()
            key = (now.date(), idx)
            if 0 < delta <= prewarn and key not in self._prewarned:
                self._prewarned.add(key)
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
        # Drop yesterday's markers so the set cannot grow without bound.
        # A single marker used to be reused for every step, which made two
        # steps inside the same warning window re-fire each other every tick.
        today = now.date()
        if any(day != today for day, _ in self._prewarned):
            self._prewarned = {k for k in self._prewarned if k[0] == today}

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
        now = dt_util.now()
        is_holiday = self._is_holiday(now)
        # Skip over steps that are muted today (weekday filter or holiday
        # rules) — otherwise "start now" would silently do nothing when the
        # first configured step is, say, a holiday-only step.
        first = next((s for s in self._steps if s.runs_today(now, is_holiday)), None)
        if first is None:
            # Nothing runs today (weekday filter or holiday rules). Bail out
            # instead of shifting the clock onto a muted step: it would never
            # activate, so the auto-reset below would never fire either and
            # the offset would survive into the next real morning.
            _LOGGER.info("start_now ignored — no step runs today")
            return
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


# The coordinator lives on the entry itself (HA 2024.6+ `runtime_data`), so the
# entry type carries it. Declared here rather than in __init__.py because both
# __init__.py and sensor.py need it and coordinator.py imports neither.
MorningRoutineConfigEntry = ConfigEntry[MorningRoutineCoordinator]
