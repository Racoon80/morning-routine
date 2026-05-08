# Screenshot key

All four images are 1920×1080 PNGs rendered from the HTML mockups in
`tools/screenshots/` via headless Chrome (`bash tools/screenshots/render.sh`).
Re-run that script after changing the card's CSS to keep these in sync.

| File | What it shows |
|---|---|
| `overlay-normal.png` | Active step "Get dressed" at 60% progress — full-screen overlay with the green→red bar (mid-orange/yellow at 60%), large 3D Fluent emoji, top-left clock, top-right cancel ✕. |
| `overlay-hc.png` | Same step in **high-contrast mode**: pure black background, white text, colourblind-safe yellow bar with a thick white outline. |
| `idle-normal.png` | Idle schedule view (default styling) — Up-next banner, one done step, one active step (blue), two upcoming, one skipped (overlapped). |
| `idle-hc.png` | Same schedule in **high-contrast mode** — heavier borders, active row inverts to white-on-black, done/skipped use strikethrough instead of fade. |

The Fluent 3D emoji assets used by the mockups live in
`tools/screenshots/assets/` (fetched once from the upstream
`microsoft/fluentui-emoji` repo, MIT licence).
