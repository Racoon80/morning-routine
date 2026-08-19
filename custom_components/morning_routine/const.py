"""Constants for Morning Routine."""
from __future__ import annotations

DOMAIN = "morning_routine"

CONF_STEPS = "steps"
CONF_NAME = "name"
CONF_NAME_LB = "name_lb"
CONF_START = "start"
CONF_DURATION = "duration"
CONF_IMAGE = "image"
CONF_TTS_TARGET = "tts_target"
CONF_TTS_ENABLED = "tts_enabled"
CONF_CHIME_ENABLED = "chime_enabled"
CONF_DAYS = "days"
CONF_LANGUAGE = "language"
CONF_PREWARN_SECONDS = "prewarn_seconds"
CONF_HIGH_CONTRAST = "high_contrast"
# Per-step: how the step behaves while the routine is in "holiday" mode.
CONF_HOLIDAY_MODE = "holiday_mode"
# Integration-wide holiday sources (either one is enough to make today a holiday)
# Stored shape stays a list of {"start", "end"} ISO dates; the options form
# edits a single period through two date pickers.
CONF_HOLIDAY_RANGES = "holiday_ranges"
CONF_HOLIDAY_ENTITY = "holiday_entity"
# Form-only field names for that single period.
CONF_HOLIDAY_FROM = "holiday_from"
CONF_HOLIDAY_TO = "holiday_to"

# Holiday behaviour per step:
#   always       — runs on school days AND during holidays (e.g. shower)
#   skip_holiday — does not run during holidays (e.g. catch the bus)
#   only_holiday — runs ONLY during holidays (e.g. late breakfast, swimming)
HOLIDAY_MODE_ALWAYS = "always"
HOLIDAY_MODE_SKIP = "skip_holiday"
HOLIDAY_MODE_ONLY = "only_holiday"
HOLIDAY_MODES = [HOLIDAY_MODE_ALWAYS, HOLIDAY_MODE_SKIP, HOLIDAY_MODE_ONLY]
DEFAULT_HOLIDAY_MODE = HOLIDAY_MODE_ALWAYS

DEFAULT_DURATION_MIN = 15
DEFAULT_LANGUAGE = "de"
DEFAULT_PREWARN_SECONDS = 60

EVENT_STEP_STARTED = f"{DOMAIN}_step_started"
EVENT_STEP_FINISHED = f"{DOMAIN}_step_finished"
EVENT_ROUTINE_FINISHED = f"{DOMAIN}_routine_finished"
EVENT_STEP_PREWARN = f"{DOMAIN}_step_prewarn"

SERVICE_SKIP_STEP = "skip_step"
SERVICE_START_NOW = "start_now"
SERVICE_SNOOZE = "snooze"
SERVICE_SET_STEPS = "set_steps"
SERVICE_RESET_SNOOZE = "reset_snooze"
SERVICE_SET_HOLIDAY = "set_holiday"

ATTR_ACTIVE_STEP = "active_step"
ATTR_PROGRESS = "progress"
ATTR_TIME_LEFT = "time_left"
ATTR_IMAGE = "image"
ATTR_NAME = "name"
ATTR_NAME_LB = "name_lb"
ATTR_NEXT_STEP = "next_step"
ATTR_HOLIDAY = "holiday"

DAYS_ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
