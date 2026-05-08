<p align="center">
  <img src="https://raw.githubusercontent.com/Racoon80/morning-routine/main/icon.png" alt="Morning Routine" width="160" height="160">
</p>

# Morning Routine for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Racoon80&repository=morning-routine&category=integration)
[![release](https://img.shields.io/github/v/release/Racoon80/morning-routine)](https://github.com/Racoon80/morning-routine/releases)
[![license](https://img.shields.io/github/license/Racoon80/morning-routine)](LICENSE)

A visual morning routine for Home Assistant — designed for kids (or anyone) who can't read a clock yet. Each step takes over the dashboard full-screen with a large 3D image and a green→red countdown bar. The image and the bar share the same dynamic color, so the time pressure is obvious without any numbers.

When idle, the card shows the day's full schedule with status indicators. You can add, edit and remove steps directly from the dashboard — no YAML, no settings panel hopping.

![Active step — full-screen overlay](https://raw.githubusercontent.com/Racoon80/morning-routine/main/images/overlay-normal.png)
![Idle schedule with active step](https://raw.githubusercontent.com/Racoon80/morning-routine/main/images/idle-normal.png)

> **Why this exists:** built for my son, who has a handicap and can't read a clock. He needed a way to know "do this now, you have this much time left, then this thing next" without numbers. Sharing it openly in case it helps another family.

---

## Features

- **Visual-only countdown** — huge picture + colour-shifting bar, no clock-reading required
- **Live wall clock** in the top-left of the overlay (HH:MM, updates every second)
- **Cancel button** in the top-right of the overlay — circular ✕ that calls `skip_step` so a parent can move the routine on with one tap
- **Microsoft Fluent 3D emojis by default** — 1500+ emoji renders served from CDN, gorgeous on any device. Twemoji and native fallbacks available
- **In-card editor** — add / edit / remove steps via a modal in the card itself, including a 72-emoji picker rendered with the same 3D PNGs (or paste any URL)
- **Day schedule view** when idle — see today's whole routine with active / upcoming / done / skipped status
- **Last-15-second pulse + 2 beeps** — bar, image and step name pulse; two escalating-pitch beeps fire at 10 s and 5 s remaining (synthesised via Web Audio, no audio file needed). Toggleable per-card.
- **High-contrast mode** for visual impairments — pure black/white palette with a colourblind-safe yellow (→ orange-red) progress bar, heavier borders and bold weights. Toggle integration-wide under **Configure → Display & accessibility**, per-card in the card editor, or let it auto-activate when the OS reports `prefers-contrast: more`.
- **60 fps smoothness** — client-side `requestAnimationFrame` loop drives the bar; server ticks every second
- **Auto-discovery** — the card finds its sensor automatically, works in any HA language
- **Self-closing overlay** — full-screen during a step, idle card otherwise; no Browser Mod needed
- **Optional TTS** with pre-step warning (60 s default) — works with Luxembourgish TTS, Cloud TTS, etc.
- **Optional chime** on step start via any `media_player`
- **Multi-language** — Deutsch · Lëtzebuergesch · English
- **Per-step day selection** — Mon / Tue / … / Sun
- **Smart overlap handling** — when two windows overlap, the later-starting step takes focus; earlier one is marked `skipped`
- **Snooze auto-reset** — `start_now` and `snooze` only shift the current routine; the schedule snaps back to wall-clock once it finishes
- **Single install** — Lovelace card and resource registration are bundled with the integration; no separate setup

---

## Screenshots

**Default look — active step + idle schedule**

| Active overlay | Idle schedule |
|---|---|
| ![Active step — Get dressed at 60% progress](https://raw.githubusercontent.com/Racoon80/morning-routine/main/images/overlay-normal.png) | ![Idle schedule view](https://raw.githubusercontent.com/Racoon80/morning-routine/main/images/idle-normal.png) |

**High-contrast mode** — pure black/white palette, colourblind-safe yellow bar, heavier borders. Three ways to turn it on (any one is enough):

1. **HA-wide:** Settings → Devices & Services → Morning Routine → **Configure** → *Display & accessibility* → **High-contrast mode**
2. **Per-card:** card editor → *High-contrast mode* checkbox (or `high_contrast: true` in YAML)
3. **System:** OS-level `prefers-contrast: more` is auto-detected

The integration setting flows to every card via the `ui_high_contrast` sensor attribute, so flipping it once covers all dashboards.

| Active overlay (HC) | Idle schedule (HC) |
|---|---|
| ![High-contrast active step](https://raw.githubusercontent.com/Racoon80/morning-routine/main/images/overlay-hc.png) | ![High-contrast idle schedule](https://raw.githubusercontent.com/Racoon80/morning-routine/main/images/idle-hc.png) |

---

## Install

### Via HACS (recommended)

1. HACS → Integrations → ⋮ → **Custom repositories**
2. Add `https://github.com/Racoon80/morning-routine` as **Integration**
3. Install **Morning Routine**, then **restart Home Assistant**
4. Settings → Devices & Services → Add Integration → **Morning Routine**

### Manual

1. Copy `custom_components/morning_routine/` into your HA `config/custom_components/`
2. Restart HA
3. Add the integration via Settings → Devices & Services

The Lovelace card is auto-loaded and auto-registered as a Lovelace resource — no extra setup, no `?v=...` URL to paste anywhere.

---

## Configure steps

Two paths — pick whichever feels natural:

### A. From the dashboard (recommended)

When the card is on a dashboard:

- Tap the **✏️ pencil** on any schedule row to edit that step
- Tap **＋ Add step** at the bottom of the schedule to add a new one
- The modal lets you set name, start time, duration, picture (emoji grid + custom URL field) and active days
- **Delete** is in the modal when editing

### B. From HA settings

Settings → Devices & Services → **Morning Routine** → **Configure**

Menu options:
- Add a step / Edit a step / Remove a step
- **Sound, voice & language** — TTS service/target, chime, language, pre-warn seconds

---

## Pictures

Three sources — the same `image` field on a step accepts all three.

### 1. Emojis (default — recommended)

Type or pick any emoji (☕, 👕, 🪥, 🚌 …). Rendered as one of:

- **`fluent`** (default) — Microsoft Fluent Emoji 3D PNGs from jsDelivr, 256×256, gorgeous
- **`twemoji`** — Twitter SVG emoji, flat 2D
- **`native`** — system font, fully offline

Switch in the card editor → *Emoji style*.

### 2. Bundled SVG silhouettes

Eight monochrome icons ship with the integration at `/morning_routine_frontend/images/`:

`coffee.svg` · `breakfast.svg` · `teeth.svg` · `clothes.svg` · `shoes.svg` · `backpack.svg` · `shower.svg` · `done.svg`

These get tinted with the current bar colour via CSS `mask`, so the silhouette glows from green to red as time runs out.

### 3. Your own files

Drop PNG/JPG/WebP/SVG into `config/www/morning/` on your HA host. They appear automatically in the picker dropdown when you edit a step in the HA settings flow, and you can also reference them by URL anywhere — `/local/morning/<file>.png`.

For colour-shift to work on photos, set `tint_mode: filter` (hue-rotate) or `tint_mode: none` (no tinting) in the card editor.

---

## Add the card to a dashboard

```yaml
type: custom:morning-routine-card
emoji_style: fluent     # fluent | twemoji | native
tint_mode: mask         # mask | filter | none  (only for SVG/PNG)
language: de            # de | lb | en  (omit to follow HA user language)
urgent_beep: true       # 2 beeps at 10s and 5s remaining (default true)
beep_volume: 0.35       # 0..1, default 0.35
high_contrast: false    # pure b/w palette + colourblind-safe yellow bar.
                        # Per-card override; if you want it for ALL cards,
                        # turn it on once in HA Settings → Configure →
                        # Display & accessibility. The OS-level
                        # `prefers-contrast: more` setting is respected
                        # too, even when this and the HA flag are both off.
# active_step_entity is optional — auto-discovered via the _mr_role
# marker attribute, so the card works regardless of UI language.
```

**Note:** browsers gate audio behind a user gesture. The first time the dashboard loads, the beep may be silent until the kid (or you) taps anywhere on the screen — after that the AudioContext stays unlocked. Most kiosk apps (Fully Kiosk, HA Companion) whitelist auto-play.

Or just add it from the dashboard card picker — `Morning Routine Card`.

The card displays a compact daily schedule when no step is active and takes over the full screen when one is. Add it to whatever dashboard the tablet shows by default; the overlay handles itself.

---

## Services

| Service | What it does |
|---|---|
| `morning_routine.start_now` | Begin the routine right now, regardless of clock time. Auto-clears the offset when the (shifted) last step finishes. |
| `morning_routine.skip_step` | End the currently active step immediately. |
| `morning_routine.snooze` | Push the routine forward by `minutes` minutes (default 5). Auto-clears when finished. |
| `morning_routine.reset_snooze` | Manually clear any `start_now` / `snooze` time-shift and snap back to wall-clock. |
| `morning_routine.set_steps` | Replace the entire step list. Used internally by the in-card editor; you can call it from automations to switch between routine variants. |

---

## Events

| Event | Payload |
|---|---|
| `morning_routine_step_prewarn` | `index, name, name_lb, image, in_seconds` |
| `morning_routine_step_started` | `index, name, name_lb, image, duration` |
| `morning_routine_step_finished` | `index, name` |
| `morning_routine_routine_finished` | `{}` |

Wire these to lights, music, blinds, anything.

---

## Sensors

| Entity | State | Useful attributes |
|---|---|---|
| `sensor.<active_step>` | step name (or `unknown`) | `image`, `progress`, `time_left`, `next_step`, `schedule`, `all_steps`, `_mr_role` |
| `sensor.<progress>` | 0–100 % | — |
| `sensor.<time_left>` | seconds | — |

Entity slugs depend on your HA UI language (e.g. `sensor.aktiver_schritt` in DE). The card auto-discovers them via the `_mr_role` marker, so you never need to hard-code the entity ID.

---

## Schedule overlap

When two step windows overlap (e.g. `07:30–07:45` Coffee and `07:35–07:50` Get-dressed), the **step with the later start time wins** — Get-dressed takes the overlay at 07:35, and Coffee shows in the schedule as `skipped` (struck through, amber badge). This makes more sense for sequential routines than waiting for the older step to finish.

If you don't want overlap at all, just keep your start times spaced out further than each step's duration.

---

## Tablet setup tip

Mount a wall tablet (Fire HD, iPad, old phone …) with **Fully Kiosk Browser** or the HA Companion App, point it at a dashboard that contains the card. The card stays as a small schedule when idle and goes full-screen during steps — perfect ambient morning helper.

---

## Local development

The integration is two parts that can be tweaked independently:

- **Backend** — `custom_components/morning_routine/` (Python, no build step)
- **Card** — `custom_components/morning_routine/frontend/morning-routine-card.js` (vanilla Web Component, no build step, no Lit import)

Edit, copy into `<HA config>/custom_components/morning_routine/`, restart HA. The card is registered with a `?v=<manifest-version>` query string so cache busts automatically on integration updates.

The Fluent emoji map (`frontend/fluent_map.json`, ~95 KB) is generated from [microsoft/fluentui-emoji](https://github.com/microsoft/fluentui-emoji) — see commit history for the build approach.

---

## Roadmap / ideas

Not promised, just open. PRs welcome.

- Drag-and-drop reorder of steps in the modal
- Per-step custom sound (bundled or URL)
- Reward screen at the end of the routine ("3 stars!")
- Donetick / chore-tracker integration on `routine_finished`
- Lottie-based animated step icons

## Contributing

Issues and PRs are welcome. The codebase is tiny (~1500 lines JS, ~500 lines Python, no build step) and the "feedback → ship" loop is fast — it took ~3 hours from "an idea for my son" to v0.9 with most of these features.

## Credits

- 3D emoji renders by [Microsoft Fluent Emoji](https://github.com/microsoft/fluentui-emoji) (MIT).
- Twemoji fallback by [jdecked/twemoji](https://github.com/jdecked/twemoji) (CC-BY 4.0).
- Hosted by [jsDelivr](https://www.jsdelivr.com/).
- Initial scaffolding and iterative development by [Claude Code](https://claude.com/claude-code).
