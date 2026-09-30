/* Shared helpers for the app's pages: icons, the bridge to Python, springs.
   Every page talks to Python only through kit.post() and window.app.receive(). */
(function (root) {
  'use strict';

  const SYMBOLS = {
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/>',
    'mic-slash': '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7M4 4l16 16"/>',
    xmark: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    check: '<path d="M5 12.5l4.3 4.3L19 7.2"/>',
    lock: '<rect x="5.5" y="10.5" width="13" height="10" rx="2.6"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    undo: '<path d="M9 5.5L4.5 10 9 14.5"/><path d="M4.5 10H14a5 5 0 0 1 0 10h-3"/>',
    pencil: '<path d="M15.2 4.8l4 4L8.5 19.5H4.5v-4z"/><path d="M13 7l4 4"/>',
    warn: '<path d="M12 4 21 19.5H3z"/><path d="M12 10v4.2M12 17v.01"/>',
    key: '<circle cx="8" cy="12" r="3.6"/><path d="M11.6 12H20.5M17.5 12v3M14.8 12v2.2"/>',
    sparkles: '<path d="M11 3.5l1.6 4.4L17 9.5l-4.4 1.6L11 15.5l-1.6-4.4L5 9.5l4.4-1.6z"/><path d="M18 14.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    cursor: '<path d="M8.5 4.5c2 0 3.5.5 3.5 2v11c0 1.5-1.5 2-3.5 2M15.5 4.5c-2 0-3.5.5-3.5 2M15.5 19.5c-2 0-3.5-.5-3.5-2M10 12h4"/>',
    copy: '<rect x="8.5" y="8.5" width="11" height="12" rx="2.2"/><path d="M15.5 8.5V6a2 2 0 0 0-2-2H6.5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h2"/>',
    doc: '<path d="M7 3.5h7l4.5 4.5v11a1.5 1.5 0 0 1-1.5 1.5H7A1.5 1.5 0 0 1 5.5 19V5A1.5 1.5 0 0 1 7 3.5z"/><path d="M13.5 3.5V8.5h5M8.5 13h7M8.5 16.5h5"/>',
    gear: '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="7"/><path d="M12 2.5V5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/>',
    chart: '<path d="M4 20h16"/><path d="M7 16.5V11"/><path d="M12 16.5V6"/><path d="M17 16.5v-4"/>',
    wave: '<path d="M4 10v4M7.5 7v10M11 4.5v15M14.5 8v8M18 6v12M21 10.5v3"/>',
    keyboard: '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6 9.8h.01M9 9.8h.01M12 9.8h.01M15 9.8h.01M18 9.8h.01M7.5 14.3h9"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    book: '<path d="M4.5 5.5c2.5-1.2 5-1.2 7.5 0v14c-2.5-1.2-5-1.2-7.5 0z"/><path d="M12 5.5c2.5-1.2 5-1.2 7.5 0v14c-2.5-1.2-5-1.2-7.5 0"/>',
    speaker: '<path d="M4.5 9.5h3l4-3.5v12l-4-3.5h-3z"/><path d="M15 9a4 4 0 0 1 0 6M17.5 6.5a7.5 7.5 0 0 1 0 11"/>',
    'speaker-slash': '<path d="M4.5 9.5h3l4-3.5v12l-4-3.5h-3z"/><path d="M15.5 9.5l5 5M20.5 9.5l-5 5"/>',
    shield: '<path d="M12 3.2l7 2.8v5.6c0 4.3-2.9 7.4-7 9.2-4.1-1.8-7-4.9-7-9.2V6z"/>',
    info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8v.01"/>',
    down: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v8.5M8.5 12.8L12 16.3l3.5-3.5"/>',
    refresh: '<path d="M19 12.5A7 7 0 1 1 16.9 7"/><path d="M17.5 3.5V7.5h-4"/>',
    chev: '<path d="M9.5 6l6 6-6 6"/>',
    chevdown: '<path d="M6 9.5l6 6 6-6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    search: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
    power: '<path d="M12 3.5v8"/><path d="M7 6.5a7.5 7.5 0 1 0 10 0"/>',
    trash: '<path d="M5 7h14M9.5 7V5h5v2M7 7l1 12.5h8L17 7"/>',
    a11y: '<circle cx="12" cy="5" r="1.8"/><path d="M5 8.5c2.3.7 4.6 1 7 1s4.7-.3 7-1M12 9.5v4.5M12 14l-3 6M12 14l3 6"/>',
    'return': '<path d="M19 5.5v6a3 3 0 0 1-3 3H6"/><path d="M9.5 11L6 14.5 9.5 18"/>',
    play: '<path d="M8 5.5v13l10.5-6.5z"/>',
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.5 2.6 3.5 5.3 3.5 8.5s-1 5.9-3.5 8.5c-2.5-2.6-3.5-5.3-3.5-8.5s1-5.9 3.5-8.5z"/>',
    folder: '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  };

  function sprite() {
    if (document.getElementById('kit-sprite')) return;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('id', 'kit-sprite');
    svg.setAttribute('aria-hidden', 'true');
    svg.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
    svg.innerHTML = Object.entries(SYMBOLS)
      .map(([k, d]) => `<symbol id="i-${k}" viewBox="0 0 24 24">${d}</symbol>`).join('');
    document.body.prepend(svg);
  }

  const I = (n, c = '') => `<svg class="i ${c}" aria-hidden="true"><use href="#i-${n}"></use></svg>`;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  /* ---------- bridge ---------- */
  function post(msg) {
    try {
      const h = root.webkit && root.webkit.messageHandlers && root.webkit.messageHandlers.bridge;
      // A JSON string rather than an object: Python parses it with json.loads
      // instead of walking NSDictionary/NSNumber conversions.
      if (h) h.postMessage(JSON.stringify(msg));
      else if (root.__bridgeLog) root.__bridgeLog.push(msg);
    } catch (e) { /* the page must keep working without Python */ }
  }
  const handlers = {};
  function on(type, fn) { handlers[type] = fn; }
  function receive(msg) {
    if (typeof msg === 'string') { try { msg = JSON.parse(msg); } catch (e) { return; } }
    const fn = msg && handlers[msg.t];
    if (fn) fn(msg);
  }

  /* ---------- environment: accessibility classes pushed by Python ---------- */
  function env(e) {
    const h = document.documentElement;
    h.classList.toggle('rm', !!e.rm);
    h.classList.toggle('rt', !!e.rt);
    h.classList.toggle('hc', !!e.hc);
  }
  const reduceMotion = () => document.documentElement.classList.contains('rm')
    || (root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);

  /* ---------- springs (SwiftUI duration/bounce: w = 2pi/duration, damping = 1 - bounce) ---------- */
  const SPRINGS = {
    appear: { d: .34, b: .22 }, morph: { d: .40, b: .16 }, card: { d: .46, b: .12 },
    bud: { d: .36, b: .30 }, press: { d: .22, b: .35 }, dismiss: { d: .26, b: 0 },
  };
  // One channel: value(t) and velocity(t) from a start value, start velocity
  // and target, solved in closed form so a retarget keeps its momentum.
  function channel(from, to, v0, spec, delay = 0) {
    const w = 2 * Math.PI / spec.d;
    const z = 1 - Math.min(Math.max(spec.b, 0), .95);
    const A = from - to;
    let f;
    if (z < 1) {
      const wd = w * Math.sqrt(1 - z * z);
      const B = (v0 + z * w * A) / wd;
      f = t => {
        const e = Math.exp(-z * w * t), c = Math.cos(wd * t), s = Math.sin(wd * t);
        return [to + e * (A * c + B * s), e * ((B * wd - z * w * A) * c - (A * wd + z * w * B) * s)];
      };
    } else {
      const B = v0 + w * A;
      f = t => { const e = Math.exp(-w * t); return [to + (A + B * t) * e, (B - w * (A + B * t)) * e]; };
    }
    return { to, delay, settle: spec.d * 3, f };
  }
  function tween(from, to, dur = .18, delay = 0) {
    const ease = x => x < .5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2;
    return { to, delay, settle: dur, f: t => { const x = Math.min(1, t / dur); return [from + (to - from) * ease(x), 0]; } };
  }
  // An animated value; animate() retargets from wherever it is right now.
  class Value {
    constructor(v) { this.v = v; this.c = null; this.t0 = 0; }
    get(now) {
      if (!this.c) return [this.v, 0];
      const t = (now - this.t0) / 1000 - this.c.delay;
      if (t <= 0) return [this.c.f(0)[0], 0];
      if (t >= this.c.settle * 2.2) { this.v = this.c.to; this.c = null; return [this.v, 0]; }
      const [x, vel] = this.c.f(t);
      if (t > this.c.settle && Math.abs(x - this.c.to) < .05 && Math.abs(vel) < .5) { this.v = this.c.to; this.c = null; return [this.v, 0]; }
      return [x, vel];
    }
    value(now) { return this.get(now)[0]; }
    busy() { return !!this.c; }
    set(v) { this.v = v; this.c = null; }
    animate(to, name, now, delay = 0) {
      const [x, vel] = this.get(now);
      if (!this.c && Math.abs(x - to) < .01) { this.v = to; return; }
      const spec = SPRINGS[name] || SPRINGS.morph;
      this.c = reduceMotion() ? tween(x, to, .18, delay) : channel(x, to, vel, spec, delay);
      this.t0 = now;
      this.v = x;
    }
  }

  // Page errors go to the app's log instead of vanishing inside WebKit.
  root.addEventListener('error', e => post({ t: 'jserror', msg: String(e.message || e.error || 'error'), src: String(e.filename || '').split('/').pop(), line: e.lineno || 0 }));
  root.addEventListener('unhandledrejection', e => post({ t: 'jserror', msg: String(e.reason && (e.reason.stack || e.reason.message) || e.reason), src: 'promise', line: 0 }));

  function setup() { sprite(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setup); else setup();

  root.kit = { I, esc, $, $$, post, on, receive, env, reduceMotion, SPRINGS, Value, sprite };
  root.app = root.app || {};
  root.app.receive = receive;
})(window);
