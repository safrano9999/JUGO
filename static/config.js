/**
 * config.js — Collapsible config panel for JUGO.
 * Fetches config-panel.html, injects it, manages open/close state,
 * and keeps the header's backend pill in sync.
 */

const ConfigPanel = {
  _el: null,
  _btn: null,
  _open: false,

  /* ── Lifecycle ── */

  async init() {
    this._el = document.getElementById('config-panel');
    this._btn = document.getElementById('config-toggle-btn');
    if (!this._el) return;

    // Fetch and inject partial HTML
    try {
      const r = await fetch('/static/config-panel.html');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      this._el.innerHTML = await r.text();
    } catch (e) {
      console.error('[ConfigPanel] failed to load:', e);
      this._el.innerHTML = '<div style="padding:12px;color:var(--warn)">Config panel failed to load.</div>';
      return;
    }

    this._attachListeners();

    // First visit: auto-open when no backend has been chosen yet
    if (!localStorage.getItem('ct_backend')) {
      this.open();
    }
  },

  /* ── Toggle ── */

  toggle() {
    this._open ? this.close() : this.open();
  },

  open() {
    this._open = true;
    if (this._el) this._el.classList.add('open');
    if (this._btn) this._btn.classList.add('open');
  },

  close() {
    this._open = false;
    if (this._el) this._el.classList.remove('open');
    if (this._btn) this._btn.classList.remove('open');
  },

  /* ── Backend pill ── */

  updatePill() {
    const pill = document.getElementById('backend-pill');
    if (!pill) return;
    const sel = document.getElementById('backend-select');
    const target = document.getElementById('backend-target');
    const backend = sel?.value || '';

    if (!backend) {
      pill.textContent = 'no backend';
      pill.classList.remove('active');
      return;
    }

    const label = sel.selectedOptions[0]?.textContent || backend;
    const model = target?.selectedOptions[0]?.textContent || '';
    pill.textContent = model ? `${label} \u00b7 ${model}` : label;
    pill.classList.add('active');
  },

  /* ── Internal: wire up event listeners on injected elements ── */

  _attachListeners() {
    const tgtLang = document.getElementById('tgt-lang');
    const srcLang = document.getElementById('src-lang');

    if (tgtLang) {
      tgtLang.addEventListener('change', () => {
        lastTranslation = '';
        updateQuadrantTitles();
        saveSettings();
        retranslateDirectives();
      });
    }
    if (srcLang) {
      srcLang.addEventListener('change', () => {
        lastTranslation = '';
        updateQuadrantTitles();
        saveSettings();
      });
    }

    const autoRefresh = document.getElementById('auto-refresh');
    if (autoRefresh) {
      autoRefresh.addEventListener('change', e => {
        setAutoRefresh(e.target.checked);
        saveSettings();
      });
    }

    const backendTarget = document.getElementById('backend-target');
    if (backendTarget) {
      backendTarget.addEventListener('change', updateButtonStates);
    }

    // Blanket save on any change inside the panel
    if (this._el) {
      this._el.querySelectorAll('input, select').forEach(el => {
        el.addEventListener('change', () => {
          saveSettings();
          updateQuadrantTitles();
        });
      });
    }
  }
};

function toggleConfigPanel() {
  ConfigPanel.toggle();
}
