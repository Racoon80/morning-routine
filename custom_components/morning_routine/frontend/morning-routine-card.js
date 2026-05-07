/**
 * Morning Routine Card
 * Fullscreen overlay that takes over the dashboard when a step is active.
 * Image and progress bar share a synchronized green→red color.
 *
 * Usage in Lovelace:
 *   type: custom:morning-routine-card
 *   active_step_entity: sensor.morning_routine_active_step
 *   language: de   # de | lb | en   (optional, defaults to HA user lang)
 *   tint_mode: mask  # mask | filter | none
 */

const VERSION = "0.4.1";

class MorningRoutineCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = null;
    this._lastStepName = null;
  }

  static getConfigElement() {
    return document.createElement("morning-routine-card-editor");
  }

  static getStubConfig() {
    // No fixed entity — card auto-discovers via _mr_role marker.
    return { tint_mode: "mask" };
  }

  setConfig(config) {
    this._config = {
      tint_mode: "mask",
      language: null,
      active_step_entity: null,
      ...config,
    };
    this._render();
  }

  _resolveEntity() {
    if (this._config.active_step_entity) return this._config.active_step_entity;
    if (!this._hass) return null;
    for (const [eid, st] of Object.entries(this._hass.states)) {
      if (!eid.startsWith("sensor.")) continue;
      if (st && st.attributes && st.attributes._mr_role === "active_step") {
        return eid;
      }
    }
    return null;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 1;
  }

  // ── core ──────────────────────────────────────────────────────────────────
  _render() {
    if (!this._hass || !this._config) return;
    const entityId = this._resolveEntity();
    if (!entityId) {
      this._mountOverlay(false);
      return;
    }
    const stateObj = this._hass.states[entityId];

    const active = stateObj && stateObj.state && stateObj.state !== "unknown" && stateObj.state !== "unavailable" && stateObj.state !== "None"
      ? stateObj.state
      : null;
    const attrs = (stateObj && stateObj.attributes) || {};
    const progress = Math.max(0, Math.min(1, attrs.progress || 0));
    const timeLeft = attrs.time_left || 0;
    const image = attrs.image || "";
    const language = this._config.language || (this._hass.language || "en").slice(0, 2);
    const name = (language === "lb" ? attrs.name_lb : attrs.name) || active || "";
    const next = attrs.next_step || null;

    if (!active) {
      this._mountOverlay(false);
      this._mountIdle({ next, language });
      this._lastStepName = null;
      return;
    }

    this._mountIdle(null);
    this._mountOverlay(true);
    this._paint({ name, image, progress, timeLeft, next, language });

    if (active !== this._lastStepName) {
      this._lastStepName = active;
      this._flashIn();
    }
  }

  _mountIdle(state) {
    let idle = this.shadowRoot.getElementById("mr-idle");
    if (!state) {
      if (idle) idle.remove();
      return;
    }
    if (!idle) {
      const wrapper = document.createElement("div");
      wrapper.innerHTML = `
        <style>
          ha-card.mr-idle {
            padding: 16px 18px;
            display: flex;
            align-items: center;
            gap: 14px;
            border-radius: 12px;
          }
          ha-card.mr-idle .icon {
            width: 40px; height: 40px;
            background: var(--primary-color, #03a9f4);
            -webkit-mask: var(--mr-idle-img) center / contain no-repeat;
                    mask: var(--mr-idle-img) center / contain no-repeat;
            flex: 0 0 auto;
          }
          ha-card.mr-idle .text {
            display: flex; flex-direction: column; gap: 2px;
          }
          ha-card.mr-idle .title {
            font-size: 15px; font-weight: 600;
            color: var(--primary-text-color);
          }
          ha-card.mr-idle .sub {
            font-size: 13px; opacity: 0.7;
            color: var(--primary-text-color);
          }
        </style>
        <ha-card class="mr-idle" id="mr-idle">
          <div class="icon" id="mr-idle-icon"></div>
          <div class="text">
            <div class="title" id="mr-idle-title"></div>
            <div class="sub" id="mr-idle-sub"></div>
          </div>
        </ha-card>
      `;
      this.shadowRoot.appendChild(wrapper);
      idle = this.shadowRoot.getElementById("mr-idle");
    }
    const { next, language } = state;
    const labels = {
      de: { title: "Morning Routine", noNext: "Heute keine weiteren Schritte" },
      lb: { title: "Moiesroutine", noNext: "Haut keng weider Schrëtt" },
      en: { title: "Morning Routine", noNext: "No more steps today" },
    };
    const L = labels[language] || labels.en;
    if (next) {
      const nextName = (language === "lb" ? next.name_lb : next.name) || next.name;
      this.shadowRoot.getElementById("mr-idle-title").textContent = L.title;
      this.shadowRoot.getElementById("mr-idle-sub").textContent = `${nextName} · ${next.start}`;
      if (next.image) {
        idle.style.setProperty("--mr-idle-img", `url("${next.image}")`);
      }
    } else {
      this.shadowRoot.getElementById("mr-idle-title").textContent = L.title;
      this.shadowRoot.getElementById("mr-idle-sub").textContent = L.noNext;
      idle.style.setProperty("--mr-idle-img", `url("/morning_routine_frontend/images/done.svg")`);
    }
  }

  _mountOverlay(visible) {
    let overlay = this.shadowRoot.getElementById("overlay");
    if (!visible) {
      if (overlay) overlay.remove();
      return;
    }
    if (overlay) return;

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        #overlay {
          position: fixed;
          inset: 0;
          z-index: 9999;
          background: var(--mr-bg, #0e0f12);
          color: #fff;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          opacity: 0;
          transition: opacity 250ms ease;
          padding: 4vh 4vw;
          box-sizing: border-box;
        }
        #overlay.shown { opacity: 1; }
        .name {
          font-size: clamp(28px, 6vw, 96px);
          font-weight: 700;
          letter-spacing: -0.02em;
          margin-bottom: 4vh;
          text-align: center;
          color: var(--mr-color, #4ade80);
          transition: color 600ms ease;
        }
        .image-wrap {
          flex: 1;
          width: 100%;
          max-height: 60vh;
          display: flex;
          align-items: center;
          justify-content: center;
          margin-bottom: 4vh;
        }
        .image {
          width: clamp(180px, 40vw, 480px);
          height: clamp(180px, 40vw, 480px);
          background-color: var(--mr-color, #4ade80);
          -webkit-mask-image: var(--mr-img);
                  mask-image: var(--mr-img);
          -webkit-mask-size: contain;
                  mask-size: contain;
          -webkit-mask-repeat: no-repeat;
                  mask-repeat: no-repeat;
          -webkit-mask-position: center;
                  mask-position: center;
          transition: background-color 600ms ease;
        }
        .image.filter {
          background: none;
          background-image: var(--mr-img);
          background-size: contain;
          background-repeat: no-repeat;
          background-position: center;
          filter: hue-rotate(var(--mr-hue, 0deg)) saturate(1.2);
          -webkit-mask: none;
                  mask: none;
        }
        .image.plain {
          background: none;
          background-image: var(--mr-img);
          background-size: contain;
          background-repeat: no-repeat;
          background-position: center;
          -webkit-mask: none;
                  mask: none;
        }
        .bar-wrap {
          width: 100%;
          max-width: 900px;
          display: flex;
          flex-direction: column;
          gap: 1.2vh;
        }
        .bar {
          height: clamp(28px, 5vh, 56px);
          background: rgba(255,255,255,0.12);
          border-radius: 999px;
          overflow: hidden;
          position: relative;
        }
        .bar-fill {
          height: 100%;
          width: 0%;
          background: var(--mr-color, #4ade80);
          border-radius: 999px;
          transition: width 900ms linear, background-color 600ms ease;
        }
        .meta {
          display: flex;
          justify-content: space-between;
          font-size: clamp(16px, 2.4vw, 28px);
          opacity: 0.85;
        }
        .next {
          margin-top: 3vh;
          font-size: clamp(14px, 2vw, 22px);
          opacity: 0.5;
          text-align: center;
        }
      </style>
      <div id="overlay">
        <div class="name" id="name"></div>
        <div class="image-wrap"><div class="image" id="img"></div></div>
        <div class="bar-wrap">
          <div class="bar"><div class="bar-fill" id="fill"></div></div>
          <div class="meta">
            <span id="left"></span>
            <span id="pct"></span>
          </div>
        </div>
        <div class="next" id="next"></div>
      </div>
    `;
  }

  _paint({ name, image, progress, timeLeft, next, language }) {
    const overlay = this.shadowRoot.getElementById("overlay");
    if (!overlay) return;

    const hue = Math.round(120 * (1 - progress));
    const color = `hsl(${hue}, 75%, 55%)`;
    overlay.style.setProperty("--mr-color", color);
    overlay.style.setProperty("--mr-hue", `${hue - 120}deg`);
    if (image) overlay.style.setProperty("--mr-img", `url("${image}")`);

    const img = this.shadowRoot.getElementById("img");
    img.classList.remove("filter", "plain");
    if (this._config.tint_mode === "filter") img.classList.add("filter");
    else if (this._config.tint_mode === "none") img.classList.add("plain");

    this.shadowRoot.getElementById("name").textContent = name;
    this.shadowRoot.getElementById("fill").style.width = `${progress * 100}%`;
    this.shadowRoot.getElementById("pct").textContent = `${Math.round(progress * 100)}%`;
    this.shadowRoot.getElementById("left").textContent = this._formatTime(timeLeft, language);

    const nextEl = this.shadowRoot.getElementById("next");
    if (next) {
      const nextLabel = (language === "lb" ? next.name_lb : next.name) || next.name;
      const labelPrefix = { de: "Danach", lb: "Duerno", en: "Next" }[language] || "Next";
      nextEl.textContent = `${labelPrefix}: ${nextLabel} · ${next.start}`;
    } else {
      nextEl.textContent = "";
    }

    requestAnimationFrame(() => overlay.classList.add("shown"));
  }

  _flashIn() {
    const overlay = this.shadowRoot.getElementById("overlay");
    if (!overlay) return;
    overlay.animate(
      [{ transform: "scale(0.96)", opacity: 0 }, { transform: "scale(1)", opacity: 1 }],
      { duration: 350, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" }
    );
  }

  _formatTime(seconds, language) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    const mLabel = { de: "min", lb: "min", en: "min" }[language] || "min";
    const sLabel = { de: "s", lb: "s", en: "s" }[language] || "s";
    if (m > 0) return `${m}${mLabel} ${s.toString().padStart(2, "0")}${sLabel}`;
    return `${s}${sLabel}`;
  }
}

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
      </style>
      <div class="row">
        <label>Active step entity (leave blank for auto-discovery)</label>
        <input id="entity" value="${this._config.active_step_entity || ""}" placeholder="auto" />
      </div>
      <div class="row">
        <label>Tint mode (mask works best for monochrome icons)</label>
        <select id="tint">
          <option value="mask"${this._config.tint_mode === "mask" ? " selected" : ""}>mask</option>
          <option value="filter"${this._config.tint_mode === "filter" ? " selected" : ""}>filter</option>
          <option value="none"${this._config.tint_mode === "none" ? " selected" : ""}>none</option>
        </select>
      </div>
      <div class="row">
        <label>Language override (blank = follow HA)</label>
        <input id="lang" value="${this._config.language || ""}" placeholder="de | lb | en" />
      </div>
    `;
    const fire = () => {
      const entityVal = this.shadowRoot.getElementById("entity").value.trim();
      const event = new CustomEvent("config-changed", {
        detail: {
          config: {
            type: "custom:morning-routine-card",
            ...(entityVal && { active_step_entity: entityVal }),
            tint_mode: this.shadowRoot.getElementById("tint").value,
            language: this.shadowRoot.getElementById("lang").value || null,
          },
        },
        bubbles: true, composed: true,
      });
      this.dispatchEvent(event);
    };
    this.shadowRoot.getElementById("entity").addEventListener("change", fire);
    this.shadowRoot.getElementById("tint").addEventListener("change", fire);
    this.shadowRoot.getElementById("lang").addEventListener("change", fire);
  }
}

customElements.define("morning-routine-card", MorningRoutineCard);
customElements.define("morning-routine-card-editor", MorningRoutineCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "morning-routine-card",
  name: "Morning Routine Card",
  description: "Full-screen morning routine takeover with countdown and color-synced image.",
  preview: false,
  documentationURL: "https://github.com/racoon80/morning-routine",
});

console.info(
  `%c MORNING-ROUTINE-CARD %c v${VERSION} `,
  "color:white;background:#4ade80;font-weight:700",
  "color:#4ade80;background:#0e0f12"
);
