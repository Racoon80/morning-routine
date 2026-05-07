# Morning Routine for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Racoon80&repository=morning-routine&category=integration)
[![release](https://img.shields.io/github/v/release/Racoon80/morning-routine)](https://github.com/Racoon80/morning-routine/releases)
[![license](https://img.shields.io/github/license/Racoon80/morning-routine)](LICENSE)

A visual morning routine designed for kids (or anyone) who can't read a clock. Each step takes over the dashboard full-screen with a large picture and a single green→red countdown bar. The picture and the bar share the same dynamic color, so the urgency is obvious without numbers.

When the routine is finished, the overlay disappears and the normal dashboard returns automatically.

---

## Features

- **Visual-only** — picture + colored countdown, no clock reading required
- **Color-synced image** — the image is tinted with the same color as the bar (CSS `mask`)
- **Self-closing overlay** — fullscreen during a step, invisible otherwise; no Browser Mod needed
- **UI-configurable steps** — add / edit / remove via Home Assistant Settings → Devices & Services → Configure
- **TTS announcement (optional)** — works with Luxembourgish TTS, Cloud TTS, etc.
- **Chime (optional)** — plays a sound on step start via any media_player
- **Multi-language** — Deutsch · Lëtzebuergesch · English
- **Per-step day selection** — Mon/Tue/.../Sun
- **Single install** — the Lovelace card is bundled, no separate install
- **Sensors** — `active_step`, `progress`, `time_left` for automations

---

## Install

### Via HACS (recommended once published)

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/racoon80/morning-routine` as **Integration**
3. Install **Morning Routine**, then restart Home Assistant
4. Settings → Devices & Services → Add Integration → **Morning Routine**

### Manual

1. Copy `custom_components/morning_routine/` into your HA `config/custom_components/`
2. Restart HA
3. Add the integration via Settings → Devices & Services

The Lovelace card auto-loads — no need to register a resource manually.

---

## Configure steps

Settings → Devices & Services → **Morning Routine** → **Configure**

Menu options:
- **Add a step** — name (DE), Lëtzebuergesch name, start time, duration, image URL, days
- **Edit a step**
- **Remove a step**
- **Sound, voice & language** — TTS service/target, chime, default language

### Bundled images (no extra setup)

The integration ships with a default silhouette set served at `/morning_routine_frontend/images/`:

`coffee.svg` · `breakfast.svg` · `teeth.svg` · `clothes.svg` · `shoes.svg` · `backpack.svg` · `shower.svg` · `done.svg`

The default routine uses these out of the box.

### Custom images

Drop your own files into `config/www/morning/` on your HA host and reference them as `/local/morning/<file>.png`.

For best look use **monochrome silhouettes** (PNG with transparency or SVG) — the integration tints them dynamically. Photos work too via `tint_mode: filter` or `tint_mode: none` on the card.

---

## Add the card to a dashboard

```yaml
type: custom:morning-routine-card
active_step_entity: sensor.morning_routine_active_step
tint_mode: mask        # mask | filter | none
language: de           # de | lb | en  (omit to follow HA user language)
```

The card renders **nothing** when no step is active. When a step starts, it overlays the entire screen. Add it to whatever dashboard the tablet shows by default — the overlay handles everything.

---

## Services

| Service | Description |
|---|---|
| `morning_routine.skip_step` | End current step early |
| `morning_routine.start_now` | Start routine right now (independent of clock) |
| `morning_routine.snooze` | Push everything forward by N minutes |

---

## Events

| Event | Payload |
|---|---|
| `morning_routine_step_prewarn` | `index, name, name_lb, image, in_seconds` |
| `morning_routine_step_started` | `index, name, name_lb, image, duration` |
| `morning_routine_step_finished` | `index, name` |
| `morning_routine_routine_finished` | `{}` |

Use these to trigger lights, music, etc.

---

## Tablet setup tip

Mount a wall tablet with `Fully Kiosk Browser` or the HA Companion App pointed at a dashboard that contains the card. No further configuration is needed — the overlay shows up only during routine steps and steps aside otherwise.

---

## Credits

Built for a kid in Kayl 🇱🇺 who needed a clock he could understand.
