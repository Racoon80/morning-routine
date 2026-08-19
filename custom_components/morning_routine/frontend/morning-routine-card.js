/**
 * Morning Routine Card v0.6.0
 *
 * - Fullscreen overlay during active step (huge emoji/image + green→red bar)
 * - Idle preview shows the day's full schedule with status indicators
 * - Inline edit modal: add / edit / delete steps without leaving the dashboard
 * - Last 15 seconds: pulsing animation on bar + image
 * - Emoji or image URL — both supported in the same `image` field
 *
 * Configuration:
 *   type: custom:morning-routine-card
 *   tint_mode: mask | filter | none   (only used for SVG/PNG, default: mask)
 *   language: de | lb | en            (omit to follow HA user language)
 *   active_step_entity: sensor.xxx    (optional — auto-discovered)
 */

const VERSION = "0.11.2";

const isEmoji = (val) => typeof val === "string" && val && !val.includes("/");

function emojiCodepoints(emoji) {
  if (!emoji || typeof emoji !== "string") return [];
  const cps = [];
  for (const ch of emoji) {
    const cp = ch.codePointAt(0);
    if (cp === 0xfe0f) continue;          // variation selector
    cps.push(cp.toString(16));
  }
  return cps;
}

// Twemoji — Twitter's SVG emoji set on jsDelivr.
const TWEMOJI_BASE = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/svg";
function emojiToTwemojiUrl(emoji) {
  const cps = emojiCodepoints(emoji);
  if (!cps.length) return null;
  return `${TWEMOJI_BASE}/${cps.join("-")}.svg`;
}

// Microsoft Fluent Emoji 3D — real PNG renders that look like little 3D
// figurines. Map is loaded async on first use from the integration's static
// frontend path (~70KB). Until it arrives, render falls back to Twemoji.
const FLUENT_BASE = "https://cdn.jsdelivr.net/gh/microsoft/fluentui-emoji@latest/assets";
const FLUENT_MAP_URL = "/morning_routine_frontend/fluent_map.json";
let FLUENT_MAP = null;
let FLUENT_MAP_LOAD = null;
function ensureFluentMap() {
  if (FLUENT_MAP || FLUENT_MAP_LOAD) return FLUENT_MAP_LOAD;
  FLUENT_MAP_LOAD = fetch(FLUENT_MAP_URL)
    .then((r) => (r.ok ? r.json() : null))
    .then((m) => {
      FLUENT_MAP = m || {};
      return FLUENT_MAP;
    })
    .catch(() => {
      FLUENT_MAP = {};
      return FLUENT_MAP;
    });
  return FLUENT_MAP_LOAD;
}
function emojiToFluentUrl(emoji) {
  if (!FLUENT_MAP) return null;
  const cps = emojiCodepoints(emoji);
  if (!cps.length) return null;
  // Try full sequence first (covers ZWJ joiners), then shorter prefixes,
  // then base codepoint. Skin tones fall back to base via this chain.
  for (let i = cps.length; i > 0; i--) {
    const key = cps.slice(0, i).join("-");
    const entry = FLUENT_MAP[key];
    if (entry) {
      const folderEnc = entry.f.split("/").map(encodeURIComponent).join("/");
      return `${FLUENT_BASE}${folderEnc}/3D/${entry.p}`;
    }
  }
  return null;
}

const fireEvent = (node, type, detail = {}) => {
  const evt = new Event(type, { bubbles: true, composed: true, cancelable: false });
  Object.assign(evt, { detail });
  node.dispatchEvent(evt);
  return evt;
};

class MorningRoutineCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = null;
    this._lastStepName = null;
    this._renderedOnce = false;
    // Client-side smooth animation state
    this._anim = null;          // rAF handle
    this._stepAnchor = null;    // { stepKey, perfNow, serverTimeLeft, duration }
    this._beeped = new Set();   // thresholds already played for current step
    this._audioCtx = null;
  }

  disconnectedCallback() {
    if (this._anim) {
      cancelAnimationFrame(this._anim);
      this._anim = null;
    }
  }

  static getConfigElement() {
    return document.createElement("morning-routine-card-editor");
  }

  static getStubConfig() {
    return { tint_mode: "mask", emoji_style: "fluent" };
  }

  setConfig(config) {
    this._config = {
      tint_mode: "mask",
      language: null,
      active_step_entity: null,
      emoji_style: "fluent",   // fluent | twemoji | native
      urgent_beep: true,        // 2 beeps near end (10s, 5s)
      beep_volume: 0.35,        // 0..1
      // High-contrast palette for users with visual impairments. When false,
      // the OS-level `prefers-contrast: more` setting is still respected via
      // matchMedia in _isHighContrast(), so accessibility prefs propagate.
      high_contrast: false,
      ...(config || {}),
    };
    if (this._config.emoji_style === "fluent") {
      // Fire-and-forget; once it lands, the next render uses the map.
      try {
        const p = ensureFluentMap();
        if (p && typeof p.then === "function") {
          p.then(() => this._render()).catch(() => {});
        }
      } catch (_) { /* never let this break setConfig */ }
    }
    this._renderPlaceholder();
    this._render();
  }

  connectedCallback() {
    this._renderPlaceholder();
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    try {
      const data = this._readData();
      if (data && data.schedule && data.schedule.length) return Math.min(8, 1 + data.schedule.length);
    } catch (_) { /* never block HA over a card-size estimate */ }
    return 2;
  }

  /** Resolution order:
   *    1. card config — `high_contrast: true` overrides everything
   *    2. integration-wide setting — exposed via `ui_high_contrast` on the
   *       active_step sensor; lets users opt in once for all dashboards
   *    3. OS-level `prefers-contrast: more` media query
   *  Any of those true ⇒ HC mode is on. */
  _isHighContrast(data) {
    if (this._config?.high_contrast) return true;
    const d = data || this._readData();
    if (d && d.ui_high_contrast === true) return true;
    try {
      return !!(window.matchMedia && window.matchMedia("(prefers-contrast: more)").matches);
    } catch (_) {
      return false;
    }
  }

  _resolveEntity() {
    if (this._config?.active_step_entity) return this._config.active_step_entity;
    if (!this._hass) return null;
    for (const [eid, st] of Object.entries(this._hass.states)) {
      if (!eid.startsWith("sensor.")) continue;
      if (st && st.attributes && st.attributes._mr_role === "active_step") return eid;
    }
    return null;
  }

  _readData() {
    if (!this._hass) return null;
    const eid = this._resolveEntity();
    if (!eid) return null;
    const st = this._hass.states[eid];
    if (!st) return null;
    return {
      state: st.state,
      ...st.attributes,
      _entity: eid,
      _entryId: st.attributes.entry_id,
    };
  }

  // ── render ────────────────────────────────────────────────────────────────
  _renderPlaceholder() {
    if (this._renderedOnce) return;
    this._renderedOnce = true;
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ${BASE_CSS}
      </style>
      <ha-card class="mr-host" id="mr-host">
        <div class="idle-loading">Morning Routine</div>
      </ha-card>
      <div id="overlay-mount"></div>
    `;
  }

  _render() {
    if (!this._renderedOnce) this._renderPlaceholder();
    if (!this._hass || !this._config) return;
    const data = this._readData();
    if (!data) return;

    const language = this._config.language || (this._hass.language || "en").slice(0, 2);
    const active = (data.state && data.state !== "unknown" && data.state !== "unavailable" && data.state !== "None") ? data.state : null;

    if (active) {
      this._renderHostIdle(data, language, /*minimized*/ true);
      this._renderOverlay(data, language);
      this._startAnimLoop(data, language);
    } else {
      this._stopAnimLoop();
      this._removeOverlay();
      this._renderHostIdle(data, language, false);
    }

    if (active !== this._lastStepName) {
      this._lastStepName = active;
      if (active) this._flashIn();
    }
  }

  // ── client-side smooth animation ──────────────────────────────────────────
  _startAnimLoop(data, language) {
    const stepKey = `${data.name}|${data.image}`;
    const progress = data.progress || 0;
    const tl = data.time_left || 0;
    // Reconstruct total step duration: total = time_left / (1 - progress).
    // Falls back to time_left when progress is essentially complete.
    const totalSec = progress >= 0.999 ? Math.max(1, tl) : tl / Math.max(0.001, 1 - progress);

    // Resync anchor when step changes OR when server drifted by >2s.
    const now = performance.now();
    const anchor = this._stepAnchor;
    const computedClientTl = anchor && anchor.stepKey === stepKey
      ? Math.max(0, anchor.serverTimeLeft - (now - anchor.perfNow) / 1000)
      : null;
    const drift = computedClientTl == null ? Infinity : Math.abs(computedClientTl - tl);

    if (!anchor || anchor.stepKey !== stepKey || drift > 2) {
      this._stepAnchor = {
        stepKey,
        perfNow: now,
        serverTimeLeft: tl,
        duration: totalSec,
      };
      // New step → reset beep tracking. If anchor only resynced (same step),
      // keep beeped state so we don't re-trigger for the same threshold.
      if (!anchor || anchor.stepKey !== stepKey) {
        this._beeped = new Set();
      }
    }

    if (this._anim) cancelAnimationFrame(this._anim);
    const tick = () => {
      const a = this._stepAnchor;
      if (!a) return;
      const elapsed = (performance.now() - a.perfNow) / 1000;
      const remaining = Math.max(0, a.serverTimeLeft - elapsed);
      const prog = a.duration > 0 ? Math.max(0, Math.min(1, 1 - remaining / a.duration)) : 1;
      this._paintProgress(prog, remaining, language);
      this._maybeBeep(remaining);
      this._anim = requestAnimationFrame(tick);
    };
    this._anim = requestAnimationFrame(tick);
  }

  /** 2 short beeps in the last 10 seconds: at 10 and 5 seconds remaining.
   *  Synthesised via Web Audio — no asset to host, works offline. */
  _maybeBeep(remainingSec) {
    if (this._config?.urgent_beep === false) return;
    const sec = Math.ceil(remainingSec);
    if (sec !== 10 && sec !== 5) return;
    if (this._beeped.has(sec)) return;
    this._beeped.add(sec);
    // Higher pitch on the second beep so the urgency is audibly increasing.
    const freq = sec === 10 ? 880 : 1100;
    this._playBeep(freq);
  }

  _playBeep(freq) {
    try {
      if (!this._audioCtx) {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return;
        this._audioCtx = new Ctx();
      }
      const ctx = this._audioCtx;
      // Resume if browser suspended it (autoplay policy).
      if (ctx.state === "suspended") ctx.resume().catch(() => {});
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, ctx.currentTime);
      const v = Math.max(0, Math.min(1, this._config?.beep_volume ?? 0.35));
      const t0 = ctx.currentTime;
      gain.gain.setValueAtTime(0, t0);
      gain.gain.linearRampToValueAtTime(v, t0 + 0.02);
      gain.gain.linearRampToValueAtTime(0, t0 + 0.22);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t0);
      osc.stop(t0 + 0.25);
    } catch (_) { /* silently swallow autoplay/permission errors */ }
  }

  _stopAnimLoop() {
    if (this._anim) {
      cancelAnimationFrame(this._anim);
      this._anim = null;
    }
    this._stepAnchor = null;
  }

  _paintProgress(progress, remainingSec, language) {
    const overlay = this.shadowRoot.querySelector("#overlay");
    if (!overlay) return;
    const hue = Math.round(120 * (1 - progress));
    const color = `hsl(${hue}, 80%, 55%)`;
    const colorSoft = `hsla(${hue}, 80%, 55%, 0.32)`;
    overlay.style.setProperty("--mr-color", color);
    overlay.style.setProperty("--mr-color-soft", colorSoft);
    overlay.style.setProperty("--mr-hue", `${hue - 120}deg`);
    const fill = overlay.querySelector("#fill");
    const pct = overlay.querySelector("#pct");
    const left = overlay.querySelector("#left");
    const clock = overlay.querySelector("#clock");
    if (fill) fill.style.width = `${progress * 100}%`;
    if (pct) pct.textContent = `${Math.round(progress * 100)}%`;
    if (left) left.textContent = formatTime(Math.ceil(remainingSec), language);
    if (clock) {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, "0");
      const mm = String(now.getMinutes()).padStart(2, "0");
      clock.textContent = `${hh}:${mm}`;
    }
    overlay.classList.toggle("urgent", remainingSec > 0 && remainingSec <= 15);
  }

  // ── idle ha-card body ─────────────────────────────────────────────────────
  _renderHostIdle(data, language, minimized) {
    const host = this.shadowRoot.getElementById("mr-host");
    if (!host) return;
    host.classList.toggle("hc", this._isHighContrast(data));
    const L = LABELS[language] || LABELS.en;
    const schedule = data.schedule || [];
    const next = data.next_step || null;

    if (minimized) {
      // While overlay is showing, the underlying card is hidden behind it,
      // but we still keep something simple here.
      host.innerHTML = `
        <div class="idle-mini">
          <div class="idle-emoji-mini">${this._iconHTML(data.image, "small")}</div>
          <div class="idle-text">
            <div class="idle-title">${L.title}</div>
            <div class="idle-sub">${escapeHtml(this._stepLabel(data, language))}</div>
          </div>
        </div>
      `;
      return;
    }

    // Build schedule rows with edit pencils
    const rows = schedule.length ? schedule.map((s) => {
      const statusClass = s.status; // active | upcoming | done | skipped | inactive
      const name = (language === "lb" ? s.name_lb : s.name) || s.name;
      const icon = this._iconHTML(s.image, "row");
      return `
        <div class="row ${statusClass}" data-idx="${s.index}">
          <div class="row-icon">${icon}</div>
          <div class="row-name">${escapeHtml(name)}</div>
          <div class="row-time">${escapeHtml(s.start)}</div>
          <div class="row-status">${L.status[s.status]}</div>
          <button class="row-edit" data-idx="${s.index}" title="${L.edit}">✏️</button>
        </div>
      `;
    }).join("") : `<div class="row empty">${L.noSteps}</div>`;

    const nextHint = next
      ? `<div class="next-hint"><span class="dot"></span>${L.nextLabel}: <strong>${escapeHtml((language==="lb"?next.name_lb:next.name) || next.name)}</strong> · ${escapeHtml(next.start)}</div>`
      : `<div class="next-hint done"><span class="dot done"></span>${L.allDone}</div>`;

    host.innerHTML = `
      <div class="idle">
        <div class="idle-header">
          <div class="title">🌅 ${L.title}${data.holiday ? `<span class="holiday-badge">🏖️ ${L.holidayBadge}</span>` : ""}</div>
          <div class="idle-actions">
            <button class="edit-btn ${data.holiday ? "on" : ""}" id="holiday-btn" title="${L.holidayBtn}">🏖️</button>
            <button class="edit-btn" id="open-options-btn" title="${L.optionsLabel}">⚙️</button>
          </div>
        </div>
        ${nextHint}
        <div class="schedule">${rows}</div>
        <div class="schedule-foot">
          <button class="add-btn" id="add-btn">＋ ${L.addStep}</button>
        </div>
      </div>
    `;
    const optBtn = this.shadowRoot.getElementById("open-options-btn");
    if (optBtn) optBtn.addEventListener("click", () => this._openOptions(data));
    const holBtn = this.shadowRoot.getElementById("holiday-btn");
    if (holBtn) holBtn.addEventListener("click", () => this._openHolidayModal(data, language));
    const addBtn = this.shadowRoot.getElementById("add-btn");
    if (addBtn) addBtn.addEventListener("click", () => this._openModal(null, data, language));
    this.shadowRoot.querySelectorAll(".row-edit").forEach((b) => {
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        const idx = parseInt(b.dataset.idx, 10);
        this._openModal(idx, data, language);
      });
    });
  }

  // ── modal editor ──────────────────────────────────────────────────────────
  async _openModal(editIndex, data, language) {
    const L = LABELS[language] || LABELS.en;
    // Snapshot current step list from coordinator data (fall back to empty).
    const currentSteps = await this._fetchSteps();
    const editing = editIndex != null && currentSteps[editIndex];
    const formState = editing
      ? { ...editing }
      : { name: "", name_lb: "", start: "07:30", duration: 15, image: "☕", days: ["mon","tue","wed","thu","fri"], holiday_mode: "always" };

    this._injectModal(MODAL_HTML);
    const modal = this.shadowRoot.getElementById("mr-modal");

    // Populate form
    const $ = (id) => modal.querySelector(`#${id}`);
    $("modal-title").textContent = editing ? L.editStep : L.addStep;
    $("f-name").value = formState.name || "";
    $("f-start").value = (formState.start || "07:30").slice(0,5);
    $("f-duration").value = formState.duration || 15;
    $("f-image").value = formState.image || "☕";
    $("emoji-preview").textContent = isEmoji(formState.image) ? formState.image : "🖼️";
    if (!editing) $("delete-btn").style.display = "none";

    // Days chips
    const daysWrap = $("f-days");
    const dayLabels = L.dayShort;
    daysWrap.innerHTML = ["mon","tue","wed","thu","fri","sat","sun"].map((d, i) => `
      <button type="button" class="day-chip ${formState.days?.includes(d) ? "on" : ""}" data-day="${d}">${dayLabels[i]}</button>
    `).join("");
    daysWrap.querySelectorAll(".day-chip").forEach((c) => {
      c.addEventListener("click", () => c.classList.toggle("on"));
    });

    // Holiday behaviour — exactly one of the three modes is selected.
    const holWrap = $("f-holiday");
    const holMode = HOLIDAY_MODES.includes(formState.holiday_mode)
      ? formState.holiday_mode
      : "always";
    holWrap.innerHTML = HOLIDAY_MODES.map((m) => `
      <button type="button" class="mode-chip ${m === holMode ? "on" : ""}" data-mode="${m}">${escapeHtml(L.holidayModes[m])}</button>
    `).join("");
    holWrap.querySelectorAll(".mode-chip").forEach((c) => {
      c.addEventListener("click", () => {
        holWrap.querySelectorAll(".mode-chip.on").forEach((x) => x.classList.remove("on"));
        c.classList.add("on");
      });
    });

    // Emoji grid — render each option using the same fluent/twemoji style as
    // the rest of the card. Falls back to the raw emoji char if no URL is
    // available (e.g. emoji_style: native or codepoint missing in fluent map).
    const emojiGrid = $("emoji-grid");
    emojiGrid.innerHTML = COMMON_EMOJIS.map((e) => {
      const url = this._resolveEmojiUrl(e);
      const inner = url
        ? `<span class="emoji-glyph" style="background-image:url('${url.href}')"></span>`
        : `<span class="emoji-glyph emoji-native">${e}</span>`;
      return `<button type="button" class="emoji-pick ${e === formState.image ? "on" : ""}" data-emoji="${e}">${inner}</button>`;
    }).join("");
    emojiGrid.querySelectorAll(".emoji-pick").forEach((b) => {
      b.addEventListener("click", () => {
        emojiGrid.querySelectorAll(".emoji-pick.on").forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        const em = b.dataset.emoji;
        $("f-image").value = em;
        this._updateEmojiPreview(em);
      });
    });
    $("f-image").addEventListener("input", () => this._updateEmojiPreview($("f-image").value));
    this._updateEmojiPreview(formState.image);

    // Translate field labels and buttons
    $("modal-title").textContent = editing ? L.editStep : L.addStep;
    modal.querySelector('label[for="f-name"]').textContent = L.fieldName;
    modal.querySelector('label[for="f-start"]').textContent = L.fieldStart;
    modal.querySelector('label[for="f-duration"]').textContent = L.fieldDuration;
    modal.querySelector('label[for="f-image"]').textContent = L.fieldImage;
    $("lbl-days").textContent = L.fieldDays;
    $("lbl-holiday").textContent = L.fieldHoliday;
    $("save-btn").textContent = L.save;
    $("cancel-btn-2").textContent = L.cancel;
    $("delete-btn").innerHTML = "🗑️ " + L.delete;

    // Buttons
    $("cancel-btn").addEventListener("click", () => modal.close());
    $("cancel-btn-2").addEventListener("click", () => modal.close());
    $("modal-backdrop").addEventListener("click", () => modal.close());
    $("delete-btn").addEventListener("click", async () => {
      if (!confirm(L.confirmDelete)) return;
      const newSteps = currentSteps.filter((_, i) => i !== editIndex);
      await this._callSetSteps(newSteps);
      modal.close();
    });
    $("save-btn").addEventListener("click", async () => {
      const days = Array.from(daysWrap.querySelectorAll(".day-chip.on")).map((c) => c.dataset.day);
      const name = $("f-name").value.trim() || "Step";
      const newStep = {
        id: editing?.id,
        name,
        // Keep name_lb in sync with name so existing data shape stays valid;
        // the LB-specific field was removed from the form per user request.
        name_lb: editing?.name_lb || name,
        start: $("f-start").value || "07:30",
        duration: parseInt($("f-duration").value, 10) || 15,
        image: $("f-image").value || "☕",
        days: days.length ? days : ["mon","tue","wed","thu","fri","sat","sun"],
        holiday_mode: holWrap.querySelector(".mode-chip.on")?.dataset.mode || "always",
      };
      const newSteps = [...currentSteps];
      if (editing) {
        newSteps[editIndex] = { ...newSteps[editIndex], ...newStep };
      } else {
        newSteps.push(newStep);
      }
      // Sort by start time so the schedule stays ordered.
      newSteps.sort((a,b) => (a.start||"").localeCompare(b.start||""));
      await this._callSetSteps(newSteps);
      modal.close();
    });

    modal.showModal();
  }

  // ── holiday dialog ────────────────────────────────────────────────────────
  _injectModal(html) {
    // Both dialogs share one stylesheet, so clear whichever is mounted before
    // injecting — otherwise a leftover dialog would sit there unstyled.
    ["mr-modal", "mr-holiday-modal"].forEach((id) => {
      const old = this.shadowRoot.getElementById(id);
      if (old) old.remove();
    });
    this.shadowRoot.querySelectorAll("style[data-mr-modal]").forEach((s) => s.remove());
    const tpl = document.createElement("template");
    tpl.innerHTML = html;
    Array.from(tpl.content.children).forEach((node) => {
      if (node.tagName === "STYLE") node.setAttribute("data-mr-modal", "1");
      this.shadowRoot.appendChild(node);
    });
  }

  _openHolidayModal(data, language) {
    const L = LABELS[language] || LABELS.en;
    this._injectModal(HOLIDAY_MODAL_HTML);
    const modal = this.shadowRoot.getElementById("mr-holiday-modal");
    const $ = (id) => modal.querySelector(`#${id}`);

    const period = data.holiday_period || {};
    $("h-from").value = period.start || "";
    $("h-to").value = period.end || "";

    $("h-title").textContent = L.holidayTitle;
    $("h-lbl-from").textContent = L.holidayFrom;
    $("h-lbl-to").textContent = L.holidayTo;
    $("h-hint").textContent = L.holidayHint;
    $("h-clear").innerHTML = "🗑️ " + L.holidayClear;
    $("h-cancel").textContent = L.cancel;
    $("h-save").textContent = L.save;

    const close = () => modal.close();
    $("h-close").addEventListener("click", close);
    $("h-cancel").addEventListener("click", close);
    $("h-backdrop").addEventListener("click", close);
    $("h-clear").addEventListener("click", async () => {
      await this._callSetHoliday("", "");
      close();
    });
    $("h-save").addEventListener("click", async () => {
      await this._callSetHoliday($("h-from").value, $("h-to").value);
      close();
    });
    modal.showModal();
  }

  async _callSetHoliday(start, end) {
    try {
      await this._hass.callService("morning_routine", "set_holiday", { start, end });
    } catch (e) {
      alert("Could not save the holiday period: " + (e.message || e));
    }
  }

  async _fetchSteps() {
    // The active_step sensor exposes the raw step list as `all_steps`.
    if (!this._hass) return [];
    const eid = this._resolveEntity();
    if (!eid) return [];
    const st = this._hass.states[eid];
    return st?.attributes?.all_steps || [];
  }

  async _callSetSteps(steps) {
    try {
      await this._hass.callService("morning_routine", "set_steps", { steps });
    } catch (e) {
      alert("Could not save steps: " + (e.message || e));
    }
  }

  _stepLabel(data, language) {
    const name = (language === "lb" ? data.name_lb : data.name) || data.name || "";
    const m = Math.floor((data.time_left || 0) / 60);
    const s = (data.time_left || 0) % 60;
    return `${name} · ${m}:${String(s).padStart(2,"0")}`;
  }

  _openOptions(data) {
    // Navigate to the integration's options page in HA UI.
    const path = "/config/integrations/integration/morning_routine";
    window.history.pushState(null, "", path);
    fireEvent(window, "location-changed", { replace: false });
  }

  // ── fullscreen overlay ────────────────────────────────────────────────────
  _renderOverlay(data, language) {
    const mount = this.shadowRoot.getElementById("overlay-mount");
    if (!mount) return;
    let overlay = mount.querySelector("#overlay");
    if (!overlay) {
      mount.innerHTML = OVERLAY_HTML;
      overlay = mount.querySelector("#overlay");
      // Wire the cancel button once on first mount.
      const cancelBtn = overlay.querySelector("#cancel-overlay");
      if (cancelBtn) {
        cancelBtn.addEventListener("click", () => {
          if (!this._hass) return;
          this._hass.callService("morning_routine", "skip_step", {})
            .catch(() => {});
        });
      }
    }

    const progress = Math.max(0, Math.min(1, data.progress || 0));
    const timeLeft = data.time_left || 0;
    const hue = Math.round(120 * (1 - progress));
    const color = `hsl(${hue}, 80%, 55%)`;
    const colorSoft = `hsla(${hue}, 80%, 55%, 0.25)`;

    overlay.style.setProperty("--mr-color", color);
    overlay.style.setProperty("--mr-color-soft", colorSoft);
    overlay.style.setProperty("--mr-hue", `${hue - 120}deg`);
    overlay.classList.toggle("hc", this._isHighContrast(data));

    const name = (language === "lb" ? data.name_lb : data.name) || "";
    const next = data.next_step;
    overlay.querySelector(".name").textContent = name;
    overlay.querySelector("#fill").style.width = `${progress * 100}%`;
    overlay.querySelector("#pct").textContent = `${Math.round(progress * 100)}%`;
    overlay.querySelector("#left").textContent = formatTime(timeLeft, language);
    const clockEl = overlay.querySelector("#clock");
    if (clockEl) {
      const now = new Date();
      clockEl.textContent = `${String(now.getHours()).padStart(2,"0")}:${String(now.getMinutes()).padStart(2,"0")}`;
    }

    const nextEl = overlay.querySelector("#next");
    if (next) {
      const nextName = (language === "lb" ? next.name_lb : next.name) || next.name;
      const labels = { de: "Danach", lb: "Duerno", en: "Next" };
      nextEl.textContent = `${labels[language] || "Next"}: ${nextName} · ${next.start}`;
    } else {
      nextEl.textContent = "";
    }

    // Render image / emoji
    const img = overlay.querySelector(".image");
    img.classList.remove("emoji", "twemoji", "fluent", "filter", "plain", "mask");
    if (isEmoji(data.image)) {
      const url = this._resolveEmojiUrl(data.image);
      if (url) {
        img.classList.add(url.cls);
        img.style.setProperty("--mr-img", `url("${url.href}")`);
        img.textContent = "";
      } else {
        img.classList.add("emoji");
        img.textContent = data.image || "";
        img.style.removeProperty("--mr-img");
      }
    } else {
      img.textContent = "";
      img.style.setProperty("--mr-img", `url("${data.image}")`);
      const mode = this._config.tint_mode || "mask";
      img.classList.add(mode);
    }

    // Last-15s pulse
    overlay.classList.toggle("urgent", timeLeft > 0 && timeLeft <= 15);

    requestAnimationFrame(() => overlay.classList.add("shown"));
  }

  _removeOverlay() {
    const mount = this.shadowRoot.getElementById("overlay-mount");
    if (mount) mount.innerHTML = "";
  }

  _flashIn() {
    const overlay = this.shadowRoot.querySelector("#overlay");
    if (!overlay) return;
    overlay.animate(
      [{ transform: "scale(0.92)", opacity: 0 }, { transform: "scale(1)", opacity: 1 }],
      { duration: 400, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" }
    );
  }

  _iconHTML(value, size) {
    const cls = size === "small" ? "icon-small" : (size === "row" ? "icon-row" : "icon");
    if (isEmoji(value)) {
      const url = this._resolveEmojiUrl(value);
      if (url) {
        return `<span class="${cls} bg-img" style="--mr-row-img:url('${url.href}')"></span>`;
      }
      return `<span class="${cls} emoji">${value}</span>`;
    }
    if (value) {
      return `<span class="${cls} bg-img" style="--mr-row-img:url('${value}')"></span>`;
    }
    return `<span class="${cls}">·</span>`;
  }

  /** Update the emoji-preview swatch in the modal. Renders the same way
   *  the actual card will: as a Fluent/Twemoji image when possible,
   *  as native text otherwise (or 🖼️ for non-emoji image URLs). */
  _updateEmojiPreview(value) {
    const el = this.shadowRoot.getElementById("emoji-preview");
    if (!el) return;
    if (!isEmoji(value)) {
      el.style.backgroundImage = "";
      el.textContent = value ? "🖼️" : "·";
      return;
    }
    const url = this._resolveEmojiUrl(value);
    if (url) {
      el.style.backgroundImage = `url("${url.href}")`;
      el.textContent = "";
    } else {
      el.style.backgroundImage = "";
      el.textContent = value;
    }
  }

  /** Resolve an emoji to a URL according to emoji_style preference.
   *  Returns { href, cls } or null for native rendering. */
  _resolveEmojiUrl(emoji) {
    const style = this._config?.emoji_style || "fluent";
    if (style === "native") return null;
    if (style === "fluent") {
      const u = emojiToFluentUrl(emoji);
      if (u) return { href: u, cls: "fluent" };
      // Map not yet loaded or codepoint missing — fall through to twemoji.
    }
    const t = emojiToTwemojiUrl(emoji);
    return t ? { href: t, cls: "twemoji" } : null;
  }
}

// Editor (config UI in dashboard) — minimal, since auto-discovery handles defaults
class MorningRoutineCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) { this._hass = hass; }
  _render() {
    if (this.shadowRoot) return;
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        .row { display: flex; flex-direction: column; gap: 4px; padding: 8px 0; }
        label { font-size: 13px; opacity: 0.8; }
        input, select { padding: 8px; border-radius: 6px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
        .hint { font-size: 12px; opacity: 0.6; }
      </style>
      <div class="row">
        <label>Active step entity</label>
        <input id="entity" value="${this._config.active_step_entity || ""}" placeholder="auto-discover" />
        <span class="hint">Leave blank to auto-find the integration sensor.</span>
      </div>
      <div class="row">
        <label>Emoji style</label>
        <select id="emoji-style">
          <option value="fluent"${this._config.emoji_style === "fluent" || !this._config.emoji_style ? " selected" : ""}>Microsoft Fluent 3D (PNG, prettiest)</option>
          <option value="twemoji"${this._config.emoji_style === "twemoji" ? " selected" : ""}>Twemoji (Twitter SVG, flat)</option>
          <option value="native"${this._config.emoji_style === "native" ? " selected" : ""}>Native (system font, offline)</option>
        </select>
      </div>
      <div class="row">
        <label>Tint mode (only for SVG/PNG, ignored for emojis)</label>
        <select id="tint">
          <option value="mask"${this._config.tint_mode === "mask" ? " selected" : ""}>mask (color-synced)</option>
          <option value="filter"${this._config.tint_mode === "filter" ? " selected" : ""}>filter (hue-rotate)</option>
          <option value="none"${this._config.tint_mode === "none" ? " selected" : ""}>none</option>
        </select>
      </div>
      <div class="row">
        <label>Language override</label>
        <input id="lang" value="${this._config.language || ""}" placeholder="de | lb | en (blank = HA default)" />
      </div>
      <div class="row">
        <label><input type="checkbox" id="urgent-beep" ${this._config.urgent_beep === false ? "" : "checked"} /> Beep 2× near end (10s, 5s)</label>
      </div>
      <div class="row">
        <label>Beep volume (0–1)</label>
        <input id="beep-volume" type="number" min="0" max="1" step="0.05" value="${this._config.beep_volume ?? 0.35}" />
      </div>
      <div class="row">
        <label><input type="checkbox" id="high-contrast" ${this._config.high_contrast ? "checked" : ""} /> High-contrast mode (better for visual impairments)</label>
        <span class="hint">Pure black/white palette, yellow accent (colorblind-safe), heavier borders. The OS setting <em>prefers-contrast: more</em> is always respected even when this is off.</span>
      </div>
    `;
    const fire = () => {
      const entityVal = this.shadowRoot.getElementById("entity").value.trim();
      const event = new CustomEvent("config-changed", {
        detail: {
          config: {
            type: "custom:morning-routine-card",
            ...(entityVal && { active_step_entity: entityVal }),
            emoji_style: this.shadowRoot.getElementById("emoji-style").value,
            tint_mode: this.shadowRoot.getElementById("tint").value,
            language: this.shadowRoot.getElementById("lang").value || null,
            urgent_beep: this.shadowRoot.getElementById("urgent-beep").checked,
            beep_volume: parseFloat(this.shadowRoot.getElementById("beep-volume").value) || 0.35,
            high_contrast: this.shadowRoot.getElementById("high-contrast").checked,
          },
        },
        bubbles: true, composed: true,
      });
      this.dispatchEvent(event);
    };
    this.shadowRoot.getElementById("entity").addEventListener("change", fire);
    this.shadowRoot.getElementById("emoji-style").addEventListener("change", fire);
    this.shadowRoot.getElementById("tint").addEventListener("change", fire);
    this.shadowRoot.getElementById("lang").addEventListener("change", fire);
    this.shadowRoot.getElementById("urgent-beep").addEventListener("change", fire);
    this.shadowRoot.getElementById("beep-volume").addEventListener("change", fire);
    this.shadowRoot.getElementById("high-contrast").addEventListener("change", fire);
  }
}

// ── helpers ──────────────────────────────────────────────────────────────────
function escapeHtml(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatTime(seconds, language) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m > 0) return `${m}:${String(s).padStart(2, "0")} min`;
  return `${s}s`;
}

const LABELS = {
  de: {
    title: "Morgenroutine",
    nextLabel: "Als Nächstes",
    allDone: "Heute alles erledigt!",
    noSteps: "Noch keine Schritte konfiguriert",
    edit: "Bearbeiten",
    optionsLabel: "Optionen öffnen",
    addStep: "Schritt hinzufügen",
    editStep: "Schritt bearbeiten",
    confirmDelete: "Diesen Schritt wirklich löschen?",
    save: "Speichern",
    cancel: "Abbrechen",
    delete: "Löschen",
    fieldName: "Name",
    fieldNameLb: "Name (Lëtzebuergesch)",
    fieldStart: "Startzeit",
    fieldDuration: "Dauer (min)",
    fieldImage: "Bild / Emoji",
    fieldDays: "Aktive Tage",
    fieldHoliday: "In den Ferien",
    holidayModes: { always: "läuft auch", skip_holiday: "pausiert", only_holiday: "nur Ferien" },
    holidayBadge: "Ferien",
    holidayBtn: "Ferien setzen",
    holidayTitle: "Ferien",
    holidayFrom: "Ferien von",
    holidayTo: "Ferien bis",
    holidayHint: "Beide Felder leer = keine Ferien. Nur ein Datum = dieser eine Tag. Der Zeitraum schaltet sich nach dem letzten Tag von selbst ab.",
    holidayClear: "Löschen",
    pickEmoji: "Emoji wählen oder URL eingeben",
    status: { active: "läuft", upcoming: "wartet", done: "fertig", skipped: "übersprungen", inactive: "frei", holiday: "Ferien" },
    dayShort: ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
  },
  lb: {
    title: "Moiesroutine",
    nextLabel: "Als Nächst",
    allDone: "Haut alles fäerdeg!",
    noSteps: "Nach keng Schrëtt konfiguréiert",
    edit: "Änneren",
    optionsLabel: "Optiounen opmaachen",
    addStep: "Schrëtt derbäisetzen",
    editStep: "Schrëtt änneren",
    confirmDelete: "Dëse Schrëtt wierklech läschen?",
    save: "Späicheren",
    cancel: "Ofbriechen",
    delete: "Läschen",
    fieldName: "Numm (Däitsch)",
    fieldNameLb: "Numm (Lëtzebuergesch)",
    fieldStart: "Startzäit",
    fieldDuration: "Dauer (min)",
    fieldImage: "Bild / Emoji",
    fieldDays: "Aktiv Deeg",
    fieldHoliday: "An der Vakanz",
    holidayModes: { always: "leeft och", skip_holiday: "Paus", only_holiday: "nëmme Vakanz" },
    holidayBadge: "Vakanz",
    holidayBtn: "Vakanz setzen",
    holidayTitle: "Vakanz",
    holidayFrom: "Vakanz vun",
    holidayTo: "Vakanz bis",
    holidayHint: "Béid Felder eidel = keng Vakanz. Nëmmen een Datum = deen een Dag. No dem leschten Dag schalt sech d'Period vun eleng of.",
    holidayClear: "Läschen",
    pickEmoji: "Emoji wielen oder URL erafügen",
    status: { active: "leeft", upcoming: "waart", done: "fäerdeg", skipped: "iwwersprongen", inactive: "fräi", holiday: "Vakanz" },
    dayShort: ["Méi", "Dën", "Mët", "Don", "Fre", "Sam", "Son"],
  },
  en: {
    title: "Morning Routine",
    nextLabel: "Up next",
    allDone: "All done for today!",
    noSteps: "No steps configured yet",
    edit: "Edit",
    optionsLabel: "Open options",
    addStep: "Add step",
    editStep: "Edit step",
    confirmDelete: "Really delete this step?",
    save: "Save",
    cancel: "Cancel",
    delete: "Delete",
    fieldName: "Name",
    fieldNameLb: "Name (Lëtzebuergesch)",
    fieldStart: "Start time",
    fieldDuration: "Duration (min)",
    fieldImage: "Picture / emoji",
    fieldDays: "Active days",
    fieldHoliday: "During holidays",
    holidayModes: { always: "still runs", skip_holiday: "paused", only_holiday: "holidays only" },
    holidayBadge: "Holiday",
    holidayBtn: "Set holidays",
    holidayTitle: "Holidays",
    holidayFrom: "Holiday from",
    holidayTo: "Holiday until",
    holidayHint: "Both empty = no holiday. A single date = that one day. The period switches itself off after its last day.",
    holidayClear: "Clear",
    pickEmoji: "Pick an emoji or paste a URL",
    status: { active: "active", upcoming: "upcoming", done: "done", skipped: "skipped", inactive: "off today", holiday: "holiday" },
    dayShort: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
  },
};

// Keep in sync with HOLIDAY_MODES in const.py
const HOLIDAY_MODES = ["always", "skip_holiday", "only_holiday"];

const COMMON_EMOJIS = [
  "☕","🍵","🥛","🥣","🥐","🍞","🥚","🥞",
  "🍎","🍌","🥪","🧇","🥨","🥯","🍇","🍓",
  "🪥","🧼","🚿","🛁","💧","🧴","🧻","💊",
  "👕","👖","🧥","🧦","👟","🥾","🧤","🧢",
  "🎒","📚","✏️","📝","🎨","🎮","🧸","🖍️",
  "🚗","🚌","🚐","🚎","🚏","🚲","🛴","🚂",
  "🛵","🚪","🏫","🚍","🛻","🚖","🛹","✈️",
  "🌞","🌙","⭐","🌈","🔔","✅","🎉","💪",
  "🛏️","😴","🧴","🪞","🦷","👓","💼","🎵",
];

// ── styles ───────────────────────────────────────────────────────────────────
const BASE_CSS = `
  ha-card.mr-host {
    padding: 16px;
    border-radius: 14px;
    overflow: hidden;
  }
  .idle-loading {
    padding: 4px;
    font-size: 14px;
    opacity: 0.7;
    color: var(--primary-text-color);
  }
  .idle-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 10px;
  }
  .idle-header .title {
    font-size: 17px; font-weight: 700;
    color: var(--primary-text-color);
    letter-spacing: -0.01em;
  }
  .edit-btn {
    background: transparent; border: none;
    cursor: pointer;
    font-size: 18px;
    padding: 4px 8px;
    border-radius: 6px;
    color: var(--primary-text-color);
    opacity: 0.6;
    transition: opacity 0.15s, background 0.15s;
  }
  .edit-btn:hover { opacity: 1; background: var(--secondary-background-color); }
  .idle-actions { display: flex; align-items: center; gap: 2px; }
  /* The holiday button lights up only while a holiday is actually running —
     a period whose last day has passed clears itself, so the button goes
     back to neutral on its own. */
  .edit-btn.on {
    opacity: 1;
    background: color-mix(in srgb, #f59e0b 20%, transparent);
  }
  .next-hint {
    display: flex; align-items: center; gap: 8px;
    font-size: 13px;
    color: var(--primary-text-color);
    opacity: 0.85;
    padding: 8px 10px;
    background: var(--primary-color, #03a9f4);
    background: linear-gradient(90deg, var(--primary-color, #03a9f4), var(--primary-color, #03a9f4));
    background-color: color-mix(in srgb, var(--primary-color, #03a9f4) 12%, transparent);
    border-radius: 8px;
    margin-bottom: 10px;
  }
  .next-hint.done {
    background-color: color-mix(in srgb, #4ade80 14%, transparent);
  }
  .next-hint .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--primary-color, #03a9f4);
    box-shadow: 0 0 0 4px color-mix(in srgb, var(--primary-color, #03a9f4) 24%, transparent);
    animation: pulse-soft 2s ease-in-out infinite;
  }
  .next-hint .dot.done { background: #4ade80; box-shadow: 0 0 0 4px rgba(74,222,128,0.25); animation: none; }
  .schedule { display: flex; flex-direction: column; gap: 4px; }
  .row {
    display: grid;
    grid-template-columns: 36px 1fr auto auto auto;
    gap: 10px;
    align-items: center;
    padding: 8px 10px;
    border-radius: 8px;
    transition: background 0.2s;
  }
  .row-edit {
    background: transparent; border: none;
    cursor: pointer;
    font-size: 14px;
    padding: 4px 6px;
    border-radius: 6px;
    opacity: 0.5;
    transition: opacity 0.15s, background 0.15s;
  }
  .row-edit:hover { opacity: 1; background: var(--secondary-background-color); }
  .schedule-foot {
    margin-top: 10px;
    display: flex;
    justify-content: center;
  }
  .add-btn {
    background: color-mix(in srgb, var(--primary-color, #03a9f4) 16%, transparent);
    color: var(--primary-color, #03a9f4);
    border: 1px dashed color-mix(in srgb, var(--primary-color, #03a9f4) 50%, transparent);
    border-radius: 8px;
    padding: 8px 16px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 600;
    transition: background 0.15s;
  }
  .add-btn:hover {
    background: color-mix(in srgb, var(--primary-color, #03a9f4) 26%, transparent);
  }
  .row:hover { background: var(--secondary-background-color); }
  .row.active {
    background: color-mix(in srgb, var(--primary-color, #03a9f4) 16%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--primary-color, #03a9f4) 40%, transparent);
  }
  .row.done { opacity: 0.45; }
  .row.skipped {
    opacity: 0.5;
    text-decoration: line-through;
    text-decoration-color: color-mix(in srgb, currentColor 35%, transparent);
  }
  .row.skipped .row-status {
    background: color-mix(in srgb, #f59e0b 20%, transparent);
    color: #f59e0b;
    opacity: 1;
  }
  /* Step is configured but does not run today (e.g. weekend day-filter).
     Kept visible so the schedule remains a stable reference, dimmed to
     signal "not for today". No strikethrough so it doesn't look like a
     historic skip. */
  .row.inactive { opacity: 0.4; }
  .row.inactive .row-status {
    background: color-mix(in srgb, currentColor 12%, transparent);
    opacity: 1;
  }
  /* Muted by the holiday rules (skip-on-holiday during a holiday, or a
     holiday-only step on a school day). Same "not today" dimming as
     .inactive, but with the holiday colour so the reason is obvious. */
  .row.holiday { opacity: 0.4; }
  .row.holiday .row-status {
    background: color-mix(in srgb, #f59e0b 18%, transparent);
    color: #f59e0b;
    opacity: 1;
  }
  .holiday-badge {
    font-size: 11px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.05em;
    padding: 3px 10px; border-radius: 999px;
    background: color-mix(in srgb, #f59e0b 20%, transparent);
    color: #f59e0b;
  }
  .idle-header .title { display: flex; align-items: center; gap: 8px; }
  .row.empty { opacity: 0.6; font-size: 13px; padding: 14px; justify-content: center; display: flex; }
  .row-icon { font-size: 22px; line-height: 1; display: flex; align-items: center; justify-content: center; }
  .row-name { font-size: 14px; color: var(--primary-text-color); overflow: hidden; text-overflow: ellipsis; }
  .row-time { font-size: 13px; color: var(--primary-text-color); opacity: 0.7; font-variant-numeric: tabular-nums; }
  .row-status {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
    padding: 2px 8px; border-radius: 999px;
    background: var(--secondary-background-color);
    color: var(--primary-text-color); opacity: 0.65;
  }
  .row.active .row-status {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
    opacity: 1;
  }
  .row.done .row-status {
    background: rgba(74,222,128,0.2);
    color: #4ade80;
    opacity: 1;
  }
  .icon-row.bg-img {
    width: 26px; height: 26px;
    background-image: var(--mr-row-img);
    background-size: contain; background-repeat: no-repeat; background-position: center;
    display: inline-block;
  }
  .idle-mini { display: flex; align-items: center; gap: 12px; }
  .idle-emoji-mini { font-size: 28px; }
  .idle-text { display: flex; flex-direction: column; }
  .idle-title { font-size: 14px; font-weight: 600; color: var(--primary-text-color); }
  .idle-sub { font-size: 12px; opacity: 0.7; color: var(--primary-text-color); }
  @keyframes pulse-soft {
    0%, 100% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.2); opacity: 0.7; }
  }

  /* ── High contrast (idle card) ──────────────────────────────────────────
     Replaces opacity-based "done/upcoming" cues with explicit borders + bold
     weights, and forces full-strength colors for status pills. */
  ha-card.mr-host.hc {
    border: 2px solid var(--primary-text-color);
  }
  ha-card.mr-host.hc .idle-header .title { font-weight: 900; }
  ha-card.mr-host.hc .next-hint {
    background-color: var(--primary-text-color);
    color: var(--card-background-color);
    opacity: 1;
    font-weight: 700;
  }
  ha-card.mr-host.hc .next-hint .dot {
    background: var(--card-background-color);
    box-shadow: 0 0 0 3px var(--primary-text-color);
  }
  ha-card.mr-host.hc .row {
    border: 2px solid transparent;
  }
  ha-card.mr-host.hc .row.upcoming {
    border-color: var(--primary-text-color);
  }
  ha-card.mr-host.hc .row.active {
    background: var(--primary-text-color);
    color: var(--card-background-color);
    border-color: var(--primary-text-color);
    box-shadow: none;
  }
  ha-card.mr-host.hc .row.active .row-name,
  ha-card.mr-host.hc .row.active .row-time {
    color: var(--card-background-color);
    opacity: 1;
    font-weight: 800;
  }
  ha-card.mr-host.hc .row.active .row-status {
    background: var(--card-background-color);
    color: var(--primary-text-color);
    border: 2px solid var(--card-background-color);
    font-weight: 800;
  }
  ha-card.mr-host.hc .row.done {
    opacity: 1;
    border-color: var(--primary-text-color);
    text-decoration: line-through;
    text-decoration-thickness: 2px;
  }
  ha-card.mr-host.hc .row.done .row-name,
  ha-card.mr-host.hc .row.done .row-time {
    opacity: 1;
  }
  ha-card.mr-host.hc .row.skipped {
    opacity: 1;
    border-color: #f59e0b;
    text-decoration-thickness: 2px;
    text-decoration-color: currentColor;
  }
  /* Holiday-muted rows keep full opacity in high contrast; the dashed
     border carries the "not today" meaning instead of the dimming. */
  ha-card.mr-host.hc .row.holiday {
    opacity: 1;
    border-style: dashed;
    border-color: var(--primary-text-color);
  }
  ha-card.mr-host.hc .holiday-badge {
    background: var(--primary-text-color);
    color: var(--card-background-color);
    border: 2px solid var(--primary-text-color);
  }
  ha-card.mr-host.hc .row-status {
    border: 2px solid currentColor;
    opacity: 1;
    font-weight: 800;
  }
  ha-card.mr-host.hc .add-btn {
    border-style: solid;
    border-width: 2px;
    font-weight: 800;
  }
`;

const OVERLAY_HTML = `
<style>
  #overlay {
    position: fixed; inset: 0; z-index: 9999;
    background-color: #0a0b0f;
    background-image: radial-gradient(circle at 50% 35%, var(--mr-color-soft), transparent 65%);
    color: #fff;
    display: flex; flex-direction: column; align-items: center;
    justify-content: flex-start;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    opacity: 0; transition: opacity 250ms ease;
    padding: 5vh 4vw 7vh 4vw;
    box-sizing: border-box;
  }
  #overlay.shown { opacity: 1; }
  .clock {
    position: absolute;
    top: 3vh; left: 3vw;
    font-size: clamp(24px, 4vw, 56px);
    font-weight: 700;
    letter-spacing: 0.02em;
    color: rgba(255, 255, 255, 0.85);
    font-variant-numeric: tabular-nums;
    text-shadow: 0 2px 12px rgba(0, 0, 0, 0.4);
    pointer-events: none;
  }
  .cancel-btn {
    position: absolute;
    z-index: 10;            /* above the (z-index:1, oversized) image box so taps land on the button */
    top: 3vh; right: 3vw;
    width: clamp(48px, 6vw, 72px);
    height: clamp(48px, 6vw, 72px);
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.10);
    border: 2px solid rgba(255, 255, 255, 0.35);
    color: #fff;
    font-size: clamp(22px, 3vw, 32px);
    font-weight: 700;
    line-height: 1;
    cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: background 0.15s, border-color 0.15s, transform 0.1s;
    -webkit-tap-highlight-color: transparent;
  }
  .cancel-btn:hover {
    background: rgba(255, 255, 255, 0.18);
    border-color: rgba(255, 255, 255, 0.6);
  }
  .cancel-btn:active { transform: scale(0.92); }
  .name {
    font-size: clamp(28px, 6vw, 96px);
    font-weight: 800;
    letter-spacing: -0.02em;
    margin-top: 2vh;
    margin-bottom: 2vh;
    text-align: center;
    color: var(--mr-color, #4ade80);
    transition: color 800ms ease;
    text-shadow: 0 4px 30px var(--mr-color-soft);
  }
  .image-wrap {
    flex: 1 1 auto;
    width: 100%;
    pointer-events: none;   /* purely decorative — must never intercept the cancel-button tap */
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 2vh;
    position: relative;
    min-height: 0;
  }
  .image-wrap::before {
    content: "";
    position: absolute;
    width: clamp(220px, 50vw, 600px);
    height: clamp(220px, 50vw, 600px);
    border-radius: 50%;
    background: radial-gradient(circle, var(--mr-color-soft), transparent 65%);
    z-index: 0;
    transition: background 800ms ease;
  }
  .image {
    position: relative; z-index: 1;
    transition: background-color 800ms ease, transform 250ms ease, font-size 250ms ease;
  }
  .image.emoji {
    font-size: clamp(140px, 32vw, 360px);
    line-height: 1;
    filter: drop-shadow(0 8px 30px var(--mr-color-soft));
    animation: gentle-float 4s ease-in-out infinite;
  }
  .image.twemoji {
    width: clamp(220px, 45vw, 520px);
    height: clamp(220px, 45vw, 520px);
    background-image: var(--mr-img);
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    filter: drop-shadow(0 8px 30px var(--mr-color-soft));
    animation: gentle-float 4s ease-in-out infinite;
  }
  .image.fluent {
    width: clamp(240px, 50vw, 600px);
    height: clamp(240px, 50vw, 600px);
    background-image: var(--mr-img);
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    /* The 3D PNGs already include lighting — keep filter subtle. */
    filter: drop-shadow(0 12px 40px var(--mr-color-soft));
    animation: gentle-float 4s ease-in-out infinite;
  }
  .image.mask {
    width: clamp(180px, 40vw, 480px);
    height: clamp(180px, 40vw, 480px);
    background-color: var(--mr-color, #4ade80);
    -webkit-mask-image: var(--mr-img); mask-image: var(--mr-img);
    -webkit-mask-size: contain; mask-size: contain;
    -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
    -webkit-mask-position: center; mask-position: center;
  }
  .image.filter, .image.plain {
    width: clamp(180px, 40vw, 480px);
    height: clamp(180px, 40vw, 480px);
    background-image: var(--mr-img);
    background-size: contain; background-repeat: no-repeat; background-position: center;
  }
  .image.filter { filter: hue-rotate(var(--mr-hue, 0deg)) saturate(1.2) drop-shadow(0 8px 30px var(--mr-color-soft)); }

  @keyframes gentle-float {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-8px); }
  }

  .bar-wrap {
    width: 100%;
    max-width: 1100px;
    display: flex; flex-direction: column; gap: 1.4vh;
    margin-top: auto;  /* push to bottom */
    flex-shrink: 0;
  }
  .bar {
    height: clamp(28px, 5vh, 56px);
    background: rgba(255,255,255,0.10);
    border-radius: 999px;
    overflow: hidden;
    position: relative;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.3);
  }
  .bar-fill {
    height: 100%; width: 0%;
    background: linear-gradient(90deg, var(--mr-color), color-mix(in srgb, var(--mr-color) 60%, white));
    border-radius: 999px;
    /* No CSS transition — JS rAF loop drives the width directly at 60fps. */
    box-shadow: 0 0 20px var(--mr-color);
  }
  .meta {
    display: flex; justify-content: space-between;
    font-size: clamp(16px, 2.4vw, 28px);
    opacity: 0.88;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
  }
  .next-line {
    margin-top: 3vh;
    font-size: clamp(14px, 2vw, 22px);
    opacity: 0.55;
    text-align: center;
  }

  /* Last 15 seconds: pulsing urgency */
  #overlay.urgent .bar-fill {
    animation: bar-pulse 0.6s ease-in-out infinite;
  }
  #overlay.urgent .image.emoji {
    animation: emoji-pulse 0.6s ease-in-out infinite;
  }
  #overlay.urgent .image.mask,
  #overlay.urgent .image.filter,
  #overlay.urgent .image.plain {
    animation: image-pulse 0.6s ease-in-out infinite;
  }
  #overlay.urgent .name {
    animation: name-pulse 0.6s ease-in-out infinite;
  }
  @keyframes bar-pulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 20px var(--mr-color); }
    50% { opacity: 0.55; box-shadow: 0 0 40px var(--mr-color); }
  }
  @keyframes emoji-pulse {
    0%, 100% { transform: scale(1) translateY(0); filter: drop-shadow(0 8px 30px var(--mr-color-soft)); }
    50% { transform: scale(1.08) translateY(-4px); filter: drop-shadow(0 12px 50px var(--mr-color)); }
  }
  @keyframes image-pulse {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.05); }
  }
  @keyframes name-pulse {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.04); }
  }

  /* ── High contrast mode ──────────────────────────────────────────────────
     Triggered by config.high_contrast=true OR @media (prefers-contrast: more).
     Goals: pure black/white palette, colorblind-safe yellow accent (instead
     of the green→red hue ramp), no opacity tricks, heavier borders, bolder
     text. The bar still encodes progress via its width + the % readout. */
  #overlay.hc {
    background-color: #000;
    background-image: none;
  }
  #overlay.hc .clock {
    color: #fff;
    text-shadow: none;
    font-weight: 900;
  }
  #overlay.hc .cancel-btn {
    background: #fff;
    border: 3px solid #fff;
    color: #000;
  }
  #overlay.hc .cancel-btn:hover {
    background: #ffeb3b;
    border-color: #ffeb3b;
  }
  #overlay.hc .name {
    color: #fff;
    text-shadow: none;
    font-weight: 900;
  }
  #overlay.hc .image-wrap::before { display: none; }
  #overlay.hc .image.emoji,
  #overlay.hc .image.twemoji,
  #overlay.hc .image.fluent {
    filter: drop-shadow(0 0 0 #fff) contrast(1.15);
  }
  #overlay.hc .image.mask { background-color: #fff; }
  #overlay.hc .image.filter { filter: contrast(1.4) brightness(1.15); }
  #overlay.hc .bar {
    background: #000;
    border: 3px solid #fff;
    box-shadow: none;
  }
  #overlay.hc .bar-fill {
    background: #ffeb3b;            /* yellow on black — WCAG AAA */
    box-shadow: none;
  }
  #overlay.hc.urgent .bar-fill {
    background: #ff5722;            /* orange-red, distinct from yellow */
  }
  #overlay.hc .meta,
  #overlay.hc .next-line {
    opacity: 1;
    color: #fff;
    font-weight: 800;
  }
</style>
<div id="overlay">
  <div class="clock" id="clock"></div>
  <button class="cancel-btn" id="cancel-overlay" title="Skip step" aria-label="Skip step">×</button>
  <div class="name"></div>
  <div class="image-wrap"><div class="image"></div></div>
  <div class="bar-wrap">
    <div class="bar"><div class="bar-fill" id="fill"></div></div>
    <div class="meta">
      <span id="left"></span>
      <span id="pct"></span>
    </div>
  </div>
  <div class="next-line" id="next"></div>
</div>
`;

// ── modal markup (one-shot template) ────────────────────────────────────────
const MODAL_CSS = `
<style>
  .mr-dialog {
    border: none;
    background: transparent;
    padding: 0;
    max-width: 100vw; max-height: 100vh;
    width: 100%; height: 100%;
    overflow: visible;
  }
  .mr-dialog::backdrop { background: transparent; }
  .mr-backdrop {
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.55);
    backdrop-filter: blur(4px);
    z-index: 0;
  }
  .mr-dialog-body {
    position: fixed;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    width: min(560px, 92vw);
    max-height: 90vh;
    background: var(--card-background-color, #1c1c1e);
    color: var(--primary-text-color, #fff);
    border-radius: 16px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
    display: flex; flex-direction: column;
    z-index: 1;
    overflow: hidden;
  }
  .mr-dialog-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 22px;
    border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));
  }
  .mr-dialog-header h3 { margin: 0; font-size: 18px; font-weight: 700; }
  .modal-close {
    background: transparent; border: none;
    cursor: pointer; font-size: 26px; line-height: 1;
    color: var(--primary-text-color); opacity: 0.6;
    width: 32px; height: 32px; border-radius: 6px;
  }
  .modal-close:hover { opacity: 1; background: var(--secondary-background-color); }
  .mr-form {
    padding: 18px 22px;
    overflow-y: auto;
    flex: 1;
    display: flex; flex-direction: column; gap: 14px;
  }
  .form-row { display: flex; flex-direction: column; gap: 6px; }
  .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .form-row label {
    font-size: 12px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.05em;
    opacity: 0.7;
  }
  .form-row input[type="text"],
  .form-row input[type="time"],
  .form-row input[type="date"],
  .form-row input[type="number"] {
    padding: 10px 12px;
    border-radius: 8px;
    border: 1px solid var(--divider-color, rgba(255,255,255,0.15));
    background: var(--secondary-background-color, rgba(255,255,255,0.05));
    color: var(--primary-text-color);
    font-size: 15px;
    font-family: inherit;
  }
  .form-row input:focus {
    outline: none;
    border-color: var(--primary-color, #03a9f4);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary-color, #03a9f4) 30%, transparent);
  }
  .image-input-wrap {
    display: flex; gap: 10px; align-items: center;
  }
  .emoji-preview {
    font-size: 32px;
    width: 50px; height: 50px;
    display: flex; align-items: center; justify-content: center;
    background-color: var(--secondary-background-color);
    background-size: 38px 38px;
    background-repeat: no-repeat;
    background-position: center;
    border-radius: 8px;
    flex: 0 0 50px;
  }
  .image-input-wrap input { flex: 1; }
  .emoji-grid {
    display: grid;
    grid-template-columns: repeat(8, 1fr);
    gap: 4px;
    max-height: 180px;
    overflow-y: auto;
    padding: 4px;
    background: var(--secondary-background-color);
    border-radius: 8px;
  }
  .emoji-pick {
    background: transparent; border: 2px solid transparent;
    cursor: pointer;
    padding: 4px; border-radius: 6px;
    transition: background 0.1s, border-color 0.1s;
    display: flex; align-items: center; justify-content: center;
    aspect-ratio: 1;
  }
  .emoji-pick:hover { background: rgba(255,255,255,0.08); }
  .emoji-pick.on {
    border-color: var(--primary-color, #03a9f4);
    background: color-mix(in srgb, var(--primary-color, #03a9f4) 20%, transparent);
  }
  .emoji-pick .emoji-glyph {
    width: 32px; height: 32px;
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    display: inline-block;
  }
  .emoji-pick .emoji-glyph.emoji-native {
    width: auto; height: auto;
    font-size: 22px; line-height: 1;
  }
  .day-chips {
    display: flex; gap: 6px; flex-wrap: wrap;
  }
  .day-chip {
    background: var(--secondary-background-color);
    border: 1px solid transparent;
    color: var(--primary-text-color);
    padding: 8px 14px;
    border-radius: 999px;
    cursor: pointer;
    font-size: 13px; font-weight: 600;
    opacity: 0.5;
    transition: all 0.15s;
  }
  .day-chip:hover { opacity: 0.8; }
  .day-chip.on {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
    opacity: 1;
    border-color: var(--primary-color, #03a9f4);
  }
  /* Holiday behaviour — single-choice chips, visually distinct from the
     multi-select day chips so it doesn't read as "pick several". */
  .mode-chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .mode-chip {
    background: var(--secondary-background-color);
    border: 1px solid transparent;
    color: var(--primary-text-color);
    padding: 8px 14px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 13px; font-weight: 600;
    opacity: 0.5;
    transition: all 0.15s;
  }
  .mode-chip:hover { opacity: 0.8; }
  .mode-chip.on {
    background: color-mix(in srgb, #f59e0b 28%, transparent);
    color: #f59e0b;
    opacity: 1;
    border-color: #f59e0b;
  }
  .h-hint { font-size: 13px; opacity: 0.7; line-height: 1.4; }
  .mr-dialog-footer {
    padding: 14px 22px;
    border-top: 1px solid var(--divider-color, rgba(255,255,255,0.1));
    display: flex; align-items: center; gap: 10px;
  }
  .btn {
    padding: 10px 18px;
    border-radius: 8px;
    border: none;
    cursor: pointer;
    font-size: 14px; font-weight: 600;
    font-family: inherit;
    transition: background 0.15s, opacity 0.15s;
  }
  .btn-primary {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
  }
  .btn-primary:hover { opacity: 0.85; }
  .btn-ghost {
    background: transparent;
    color: var(--primary-text-color);
    opacity: 0.7;
  }
  .btn-ghost:hover { opacity: 1; background: var(--secondary-background-color); }
  .btn-danger {
    background: color-mix(in srgb, #ef4444 20%, transparent);
    color: #ef4444;
  }
  .btn-danger:hover { background: color-mix(in srgb, #ef4444 35%, transparent); }
  @media (max-width: 480px) {
    .form-grid { grid-template-columns: 1fr; }
    .emoji-grid { grid-template-columns: repeat(7, 1fr); }
  }
</style>
`;

const MODAL_HTML = `
<dialog id="mr-modal" class="mr-dialog">
  <div id="modal-backdrop" class="mr-backdrop"></div>
  <div class="mr-dialog-body">
    <div class="mr-dialog-header">
      <h3 id="modal-title">Step</h3>
      <button class="modal-close" id="cancel-btn">×</button>
    </div>
    <div class="mr-form">
      <div class="form-row">
        <label for="f-name">Name</label>
        <input type="text" id="f-name" />
      </div>
      <div class="form-grid">
        <div class="form-row">
          <label for="f-start">Start</label>
          <input type="time" id="f-start" />
        </div>
        <div class="form-row">
          <label for="f-duration">Duration (min)</label>
          <input type="number" id="f-duration" min="1" max="600" />
        </div>
      </div>
      <div class="form-row">
        <label for="f-image">Picture / Emoji</label>
        <div class="image-input-wrap">
          <span id="emoji-preview" class="emoji-preview">☕</span>
          <input type="text" id="f-image" />
        </div>
        <div id="emoji-grid" class="emoji-grid"></div>
      </div>
      <div class="form-row">
        <label id="lbl-days">Active days</label>
        <div id="f-days" class="day-chips"></div>
      </div>
      <div class="form-row">
        <label id="lbl-holiday">During holidays</label>
        <div id="f-holiday" class="mode-chips"></div>
      </div>
    </div>
    <div class="mr-dialog-footer">
      <button class="btn btn-danger" id="delete-btn">🗑️ Delete</button>
      <div style="flex:1"></div>
      <button class="btn btn-ghost" id="cancel-btn-2">Cancel</button>
      <button class="btn btn-primary" id="save-btn">Save</button>
    </div>
  </div>
</dialog>` + MODAL_CSS;

// Same chrome as the step modal, so both dialogs share one stylesheet.
const HOLIDAY_MODAL_HTML = `
<dialog id="mr-holiday-modal" class="mr-dialog">
  <div id="h-backdrop" class="mr-backdrop"></div>
  <div class="mr-dialog-body">
    <div class="mr-dialog-header">
      <h3 id="h-title">Holidays</h3>
      <button class="modal-close" id="h-close">×</button>
    </div>
    <div class="mr-form">
      <div class="form-grid">
        <div class="form-row">
          <label id="h-lbl-from" for="h-from">From</label>
          <input type="date" id="h-from" />
        </div>
        <div class="form-row">
          <label id="h-lbl-to" for="h-to">Until</label>
          <input type="date" id="h-to" />
        </div>
      </div>
      <div id="h-hint" class="h-hint"></div>
    </div>
    <div class="mr-dialog-footer">
      <button class="btn btn-danger" id="h-clear">🗑️ Clear</button>
      <div style="flex:1"></div>
      <button class="btn btn-ghost" id="h-cancel">Cancel</button>
      <button class="btn btn-primary" id="h-save">Save</button>
    </div>
  </div>
</dialog>
` + MODAL_CSS;


customElements.define("morning-routine-card", MorningRoutineCard);
customElements.define("morning-routine-card-editor", MorningRoutineCardEditor);

window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === "morning-routine-card")) {
  window.customCards.push({
    type: "morning-routine-card",
    name: "Morning Routine Card",
    description: "Visual morning routine — full-screen overlay during steps, day schedule when idle.",
    preview: false,
    documentationURL: "https://github.com/Racoon80/morning-routine",
  });
}

console.info(
  `%c MORNING-ROUTINE-CARD %c v${VERSION} `,
  "color:white;background:#4ade80;font-weight:700;padding:2px 4px",
  "color:#4ade80;background:#0e0f12;padding:2px 4px"
);
