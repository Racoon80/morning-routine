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

ATTR_ACTIVE_STEP = "active_step"
ATTR_PROGRESS = "progress"
ATTR_TIME_LEFT = "time_left"
ATTR_IMAGE = "image"
ATTR_NAME = "name"
ATTR_NAME_LB = "name_lb"
ATTR_NEXT_STEP = "next_step"

DAYS_ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
