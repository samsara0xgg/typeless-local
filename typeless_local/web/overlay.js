/* The capsule. Python owns the state machine and calls show()/hide(); this page
   draws the state, animates every shape with springs, and reports each frame's
   rectangles back so the native glass under the page and the click-through
   regions of the panel follow exactly. */
(() => {
'use strict';
const { I, esc, $, post, on, env, reduceMotion, Value } = kit;

const stage = $('#stage'), capEl = $('#cap'), budsEl = $('#buds'), handleEl = $('#handle'), hbEl = $('#hb');
const MARGIN = 14;          // gap between the capsule and the bottom of the visible frame
const GAP = 8;
const PILL_H = 40, BUD_H = 36;
const QUIET_MS = 3000;      // "没有检测到声音" after this long without voice
const VOICE = 0.08;         // analyzer level that counts as voice
const NB = 13;
const PROF = [1, .92, .8, .66, .52, .4, .3, .22];

const S = {
  st: 'hidden', d: {}, kind: 'pill', hidden: true, layer: null,
  mode: 'click', recAt: 0, max: 900, cd: false, quiet: false, lastVoice: 0,
  level: 0, levelAt: 0, tmrText: '', say: '',
  anchor: { mode: 'bottom', x: null, y: null }, last: null,
  handleOn: false, handleHover: false, hover: false, hovBtn: null, native: false, lastGeo: '',
};
let seq = 0;

/* ---------------- shapes ---------------- */
class Shape {
  constructor(id, el, glass = true) {
    this.id = id; this.el = el; this.glass = glass; this.gone = false;
    this.x = new Value(0); this.y = new Value(0); this.w = new Value(40); this.h = new Value(40); this.r = new Value(20);
    this.o = new Value(0); this.s = new Value(1); this.tx = new Value(0); this.ty = new Value(0);
  }
  vals() { return [this.x, this.y, this.w, this.h, this.r, this.o, this.s, this.tx, this.ty]; }
  busy() { return this.vals().some(v => v.busy()); }
  place(r) { this.x.set(r.x); this.y.set(r.y); this.w.set(r.w); this.h.set(r.h); if (r.r != null) this.r.set(r.r); }
  go(r, spring, now, delay = 0) {
    this.x.animate(r.x, spring, now, delay); this.y.animate(r.y, spring, now, delay);
    this.w.animate(r.w, spring, now, delay); this.h.animate(r.h, spring, now, delay);
    if (r.r != null) this.r.animate(r.r, spring === 'morph' ? 'card' : spring, now, delay);
  }
  apply(now) {
    const f = {
      x: this.x.value(now), y: this.y.value(now), w: Math.max(0, this.w.value(now)), h: Math.max(0, this.h.value(now)),
      r: Math.max(0, this.r.value(now)), o: Math.min(1, Math.max(0, this.o.value(now))), s: Math.max(0, this.s.value(now)),
      tx: this.tx.value(now), ty: this.ty.value(now),
    };
    const st = this.el.style;
    st.width = f.w.toFixed(2) + 'px'; st.height = f.h.toFixed(2) + 'px';
    st.borderRadius = f.r.toFixed(2) + 'px'; st.opacity = f.o.toFixed(3);
    st.transform = `translate(${(f.x + f.tx).toFixed(2)}px, ${(f.y + f.ty).toFixed(2)}px) scale(${f.s.toFixed(4)})`;
    return f;
  }
  geo(f) {
    const w = f.w * f.s, h = f.h * f.s;
    const cx = f.x + f.tx + f.w / 2, cy = f.y + f.ty + f.h / 2;
    return { id: this.id, x: +(cx - w / 2).toFixed(2), y: +(cy - h / 2).toFixed(2), w: +w.toFixed(2), h: +h.toFixed(2), r: +(f.r * f.s).toFixed(2), a: +f.o.toFixed(3), glass: this.glass, hit: !this.gone && f.o > .05 };
  }
}
const cap = new Shape('cap', capEl);
const hb = new Shape('hb', hbEl);
hb.place({ x: 0, y: 0, w: 40, h: 40, r: 20 });
let buds = [];

/* ---------------- views ---------------- */
const tail = s => { const t = Array.from(String(s || '')); return t.length > 24 ? '…' + t.slice(-24).join('') : t.join(''); };
const fmt = (sec, up) => { const s = Math.max(0, up ? Math.ceil(sec - 1e-4) : Math.floor(sec)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const waveHTML = idle => `<span class="wave${idle ? ' idle' : ''}">${'<i></i>'.repeat(NB)}</span>`;
const CHECK = `<span class="lead ok"><svg class="i draw" viewBox="0 0 24 24" aria-hidden="true" style="stroke-width:2.4"><path d="M5 12.5l4.3 4.3L19 7.2"/></svg></span>`;
const BUD = {
  undo: `<button data-act="undo">${I('undo')}<span>撤销</span></button>`,
  edit: `<button data-act="edit">${I('pencil')}<span>修改</span></button>`,
  rerefine: `<button class="pri" data-act="rerefine">${I('refresh')}<span>重新润色</span></button>`,
  setkey: `<button class="pri" data-act="setkey">${I('key')}<span>设置 API Key…</span></button>`,
  input: `<button data-act="input">${I('mic')}<span>选择输入…</span></button>`,
  micperm: `<button class="pri" data-act="micperm">${I('mic')}<span>打开设置…</span></button>`,
  perm: `<button class="pri" data-act="perm">${I('a11y')}<span>打开设置…</span></button>`,
  log: `<button data-act="log">${I('doc')}<span>显示日志</span></button>`,
};
const WHY = { timeout: '润色超时', error: '润色失败', truncated: '润色被截断', empty: '润色没有返回' };
const etaText = eta => eta ? ` · ${esc(eta)}` : '';
// Announced in steps of ten, not on every progress report.
const downloadSay = p => `语音模型下载中，${Math.floor(p * 10) * 10}%`;
const btnCancel = `<button class="ib" data-act="cancel" aria-label="取消">${I('xmark')}</button>`;
const btnFinish = `<button class="ib pri" data-act="finish" aria-label="完成">${I('check')}</button>`;

function cardHTML(title, sub, text, btns) {
  return `<div class="card-in"><div class="card-h">${I('doc')}<span class="t">${esc(title)}<small>${esc(sub)}</small></span><button class="ib sm" data-act="close" aria-label="关闭">${I('xmark')}</button></div>`
    + `<textarea class="card-field" id="cardField" rows="3" spellcheck="false" aria-label="听写文字">${esc(text || '')}</textarea>`
    + `<div class="card-f"><span class="kh">⏎ ${btns.length > 1 ? '替换' : '完成'} · ⇧⏎ 换行 · esc 取消</span><span class="sp"></span>`
    + btns.map(([a, l, p]) => `<button class="pbtn${p ? ' pri' : ''}" data-act="${a}">${esc(l)}</button>`).join('') + `</div></div>`;
}

function recHTML() {
  const o = S.d;
  const sel = o.sel ? `<span class="chip">${I('cursor')}改写所选</span>` : '';
  const duck = o.ducked ? `<span class="lockg" aria-label="已静音其他声音">${I('speaker-slash')}</span>` : '';
  const lock = `<span class="lockg">${I('lock')}</span>`;
  const t = (performance.now() - S.recAt) / 1000;
  if (S.cd) {
    const rem = S.max - t, p = Math.max(0, Math.min(1, rem / 60));
    S.tmrText = fmt(rem, true);
    return [`${btnCancel}${waveHTML()}<span class="tmr warn">${S.tmrText}</span><span class="ringwrap"><svg class="ring" viewBox="0 0 36 36" aria-hidden="true"><circle class="bg" cx="18" cy="18" r="16.5"/><circle class="fg" cx="18" cy="18" r="16.5" stroke-dasharray="103.7" stroke-dashoffset="${(103.7 * (1 - p)).toFixed(1)}"/></svg>${btnFinish}</span>`,
      `还剩 ${Math.ceil(rem)} 秒，到点会自动结束`];
  }
  S.tmrText = fmt(t);
  if (S.quiet && S.mode !== 'hold') {
    return [`${btnCancel}${S.mode === 'latch' ? lock : ''}${waveHTML(true)}<span class="hint warn">没有检测到声音</span>${btnFinish}`, '没有检测到声音，检查一下麦克风'];
  }
  const selSay = o.sel ? '，将改写所选文字' : '';
  switch (S.mode) {
    case 'hold': return [`<span class="recdot"></span>${sel}${waveHTML()}<span class="hint">松开完成</span>`, '录音中，松开按键完成' + selSay];
    case 'latch': return [`${btnCancel}${lock}${sel}${duck}${waveHTML()}<span class="tmr">${S.tmrText}</span>${btnFinish}`, '已锁定录音，再按一次 F5 完成' + selSay];
    default: return [`${btnCancel}${sel}${duck}${waveHTML()}<span class="tmr">${S.tmrText}</span>${btnFinish}`, '录音中，再按一次 F5 完成' + selSay];
  }
}

// [html, kind, buds, what VoiceOver says]
function view(st, o) {
  switch (st) {
    case 'starting': return [`<span class="solo">${I('mic', 'breathe')}</span>`, 'circle', [], '正在打开麦克风'];
    case 'rec': { const [h, say] = recHTML(); return [h, 'pill', [], say]; }
    case 'transcribing': return [`<span class="dots"><i></i><i></i><i></i></span><span class="lbl">转写中</span>`, 'pill', [], '转写中'];
    case 'refining': return [`<span class="spark">${I('sparkles')}</span><span class="raw shimmer">${esc(tail(o.raw))}</span>`, 'pill', [], '润色中'];
    case 'inserted': return [`${CHECK}<span class="lbl">${o.replaced ? '已替换所选' : '已插入'} · ${o.n | 0} 字</span>`, 'pill', [BUD.undo, BUD.edit], `${o.replaced ? '已替换所选' : '已插入'} ${o.n | 0} 字`];
    case 'inserted-raw-net': return [`<span class="lead warn wiggle">${I('warn')}</span><span class="lbl">已插入原始转写 <span class="sub">· ${WHY[o.why] || WHY.error}</span></span>`, 'pill', [BUD.rerefine, BUD.undo], `已插入原始转写，${WHY[o.why] || WHY.error}`];
    case 'inserted-raw-key': return [`<span class="lead warn">${I('key')}</span><span class="lbl">已插入原始转写 <span class="sub">· 缺少 API Key</span></span>`, 'pill', [BUD.setkey], '已插入原始转写，还没有设置 API Key'];
    case 'edit-notarget': return [cardHTML('没有可插入的位置', '已复制到剪贴板。改完按 ⏎ 再复制一次。', o.text, [['done', '完成', true]]), 'card', [], '没有可插入的位置，结果已复制到剪贴板，可以直接修改'];
    case 'edit-modify': return [cardHTML('修改刚插入的文字', '替换 = 在原 App 里撤销那次粘贴，再粘贴新文字', o.text, [['close', '取消'], ['replace', '替换', true]]), 'card', [], '修改刚插入的文字，回车替换，esc 取消'];
    case 'empty': return [`<span class="lead">${I('mic-slash')}</span><span class="lbl">没有听到声音${o.device ? ` <span class="sub">· ${esc(o.device)}</span>` : ''}</span>`, 'pill', [], '没有听到声音'];
    case 'mic': return o.why === 'denied'
      ? [`<span class="lead err wiggle">${I('mic-slash')}</span><span class="lbl">没有麦克风权限 <span class="sub">· 在系统设置里打开</span></span>`, 'pill', [BUD.micperm], '没有麦克风权限']
      : [`<span class="lead err wiggle">${I('warn')}</span><span class="lbl">麦克风不可用 <span class="sub">· 可能被其他 App 占用</span></span>`, 'pill', [BUD.input], '麦克风不可用'];
    case 'download': {
      const p = Math.max(0, Math.min(1, +o.p || 0));
      return [`<span class="pring" style="--p:${p.toFixed(3)}"></span><span class="lbl">语音模型下载中 · <span class="pct">${Math.round(p * 100)}%</span><span class="sub eta">${etaText(o.eta)}</span></span>`, 'pill', [], downloadSay(p)];
    }
    case 'cancelled': return [`<span class="lead">${I('xmark')}</span><span class="lbl">已取消</span>`, 'pill', [], '已取消'];
    case 'undone': return [`<span class="lead">${I('undo')}</span><span class="lbl">已撤销</span>`, 'pill', [], '已撤销'];
    case 'replaced': return [`${CHECK}<span class="lbl">已替换 · ${o.n | 0} 字</span>`, 'pill', [], `已替换 ${o.n | 0} 字`];
    case 'copied': return [`${CHECK}<span class="lbl">已复制到剪贴板</span>`, 'pill', [], '已复制到剪贴板'];
    case 'perm': return [`<span class="lead warn">${I('a11y')}</span><span class="lbl">需要辅助功能权限 <span class="sub">· 否则按键传不到言字</span></span>`, 'pill', [BUD.perm], '需要辅助功能权限'];
    case 'notice': return [`<span class="lead">${I('info')}</span><span class="lbl">${esc(o.msg || '')}</span>`, 'pill', [], o.msg || ''];
    case 'error': return [`<span class="lead err wiggle">${I('warn')}</span><span class="lbl">出错了${o.msg ? ` <span class="sub">· ${esc(o.msg)}</span>` : ''}</span>`, 'pill', o.log === false ? [] : [BUD.log], '出错了' + (o.msg ? '，' + o.msg : '')];
  }
  return ['', 'pill', [], ''];
}

/* ---------------- layout ---------------- */
function anchorPoint() {
  const W = innerWidth, H = innerHeight, a = S.anchor;
  return { x: a.x == null ? W / 2 : a.x, y: a.y == null ? (a.mode === 'top' ? MARGIN : H - MARGIN) : a.y, top: a.mode === 'top' };
}
function layout(capW, capH, budWs) {
  const W = innerWidth, ap = anchorPoint();
  const total = capW + budWs.reduce((sum, w) => sum + GAP + w, 0);
  const left = Math.max(8, Math.min(W - 8 - total, ap.x - total / 2));
  const top = ap.top ? ap.y : ap.y - capH;
  const out = { cap: { x: left, y: top, w: capW, h: capH, r: capH > PILL_H ? 24 : 20 }, buds: [] };
  let x = left + capW + GAP;
  for (const w of budWs) { out.buds.push({ x, y: top + (PILL_H - BUD_H) / 2, w, h: BUD_H, r: BUD_H / 2 }); x += w + GAP; }
  return out;
}

/* ---------------- render ---------------- */
function measureLayer(html, kind) {
  const el = document.createElement('div');
  el.className = `layer ${kind === 'card' ? 'card ' : ''}measure enter`;
  if (kind === 'card') el.style.width = Math.min(400, innerWidth - 16) + 'px';
  el.innerHTML = html;
  capEl.appendChild(el);
  const w = Math.ceil(el.offsetWidth), h = Math.ceil(el.offsetHeight);
  el.classList.remove('measure');
  return { el, w, h };
}
function makeBuds(list) {
  return list.map(html => {
    const t = document.createElement('div');
    t.innerHTML = html;
    const b = t.firstElementChild;
    b.classList.add('bud', 'gl', 'measure');
    budsEl.appendChild(b);
    const w = Math.ceil(b.offsetWidth);
    b.classList.remove('measure');
    return { el: b, w };
  });
}
function dropBuds(now) {
  for (const b of buds) {
    if (b.gone) continue;
    b.gone = true;
    b.el.style.pointerEvents = 'none';
    b.o.animate(0, 'dismiss', now); b.s.animate(.7, 'dismiss', now); b.tx.animate(-18, 'dismiss', now);
  }
}

function render(st, d) {
  const now = performance.now();
  const [html, kind, budList, say] = view(st, d);
  const fromNothing = S.hidden && cap.o.value(now) < .05;
  const { el, w, h } = measureLayer(html, kind);
  const capW = kind === 'circle' ? 40 : Math.max(40, w);
  const capH = kind === 'card' ? h : PILL_H;
  const made = makeBuds(budList);
  const L = layout(capW, capH, made.map(b => b.w));
  const spring = (kind === 'card') !== (S.kind === 'card') ? 'card' : 'morph';

  if (fromNothing) {
    cap.place({ x: L.cap.x + L.cap.w / 2 - 20, y: anchorPoint().top ? L.cap.y : L.cap.y + L.cap.h - PILL_H, w: 40, h: PILL_H, r: 20 });
    cap.s.set(.82); cap.o.set(0); cap.ty.set(10); cap.tx.set(0);
  }
  cap.go(L.cap, spring, now);
  cap.s.animate(1, 'appear', now); cap.o.animate(1, 'appear', now); cap.ty.animate(0, 'appear', now);
  cap.gone = false;
  capEl.style.pointerEvents = '';

  void el.offsetWidth;
  el.classList.remove('enter');
  if (S.layer) { const old = S.layer; old.classList.add('leave'); setTimeout(() => old.remove(), 220); }
  S.layer = el;

  dropBuds(now);
  made.forEach((m, i) => {
    const b = new Shape('b' + (++seq), m.el);
    const r = L.buds[i];
    b.place(r);
    b.o.set(0); b.s.set(.55); b.tx.set(-26);
    const delay = (fromNothing ? .2 : .09) + i * .06;
    b.o.animate(1, 'bud', now, delay); b.s.animate(1, 'bud', now, delay); b.tx.animate(0, 'bud', now, delay);
    buds.push(b);
  });

  S.st = st; S.kind = kind; S.hidden = false;
  handleEl.classList.add('away');
  S.last = { capW, capH, budWs: made.map(m => m.w) };
  capEl.setAttribute('aria-hidden', 'false');
  if (say && say !== S.say) { S.say = say; post({ t: 'say', text: say }); }
  if (kind === 'card') setTimeout(focusField, 60);
  kick();
}

// Progress arrives every half second; redrawing the whole capsule each time
// would cross-fade it constantly, so only the numbers change.
function updateDownload(d) {
  S.d = d;
  const p = Math.max(0, Math.min(1, +d.p || 0));
  const ring = S.layer.querySelector('.pring'), pct = S.layer.querySelector('.pct'), eta = S.layer.querySelector('.eta');
  if (ring) ring.style.setProperty('--p', p.toFixed(3));
  if (pct) pct.textContent = Math.round(p * 100) + '%';
  if (eta) eta.textContent = d.eta ? ` · ${d.eta}` : '';
  const w = Math.max(40, Math.ceil(S.layer.offsetWidth));
  if (S.last && Math.abs(w - S.last.capW) > 1) { S.last.capW = w; relayout(); }
  const say = downloadSay(p);
  if (say !== S.say) { S.say = say; post({ t: 'say', text: say }); }
}

function relayout() {
  if (S.hidden || !S.last) return;
  const now = performance.now();
  const L = layout(S.last.capW, S.last.capH, S.last.budWs);
  cap.go(L.cap, 'morph', now);
  buds.filter(b => !b.gone).forEach((b, i) => { if (L.buds[i]) b.go(L.buds[i], 'morph', now); });
  kick();
}

function hide() {
  const now = performance.now();
  S.hidden = true; S.st = 'hidden'; S.say = '';
  handleEl.classList.remove('away');
  cap.s.animate(.82, 'dismiss', now); cap.o.animate(0, 'dismiss', now); cap.ty.animate(10, 'dismiss', now);
  cap.gone = true;
  capEl.style.pointerEvents = 'none';
  capEl.setAttribute('aria-hidden', 'true');
  dropBuds(now);
  const field = $('#cardField');
  if (field) field.blur();
  kick();
}

function focusField() {
  const f = $('#cardField');
  if (!f || S.kind !== 'card') return;
  f.focus();
  f.setSelectionRange(f.value.length, f.value.length);
}

/* ---------------- the recording view: timer, countdown, quiet, wave ---------------- */
const hist = new Array(8).fill(0), bh = new Array(NB).fill(3);
function rerenderRec() { if (S.st === 'rec') render('rec', S.d); }
function tickRec(now) {
  if (S.st !== 'rec' || !S.layer) return;
  const t = (now - S.recAt) / 1000;
  const rem = S.max - t;
  if (S.max > 0 && rem <= 60 && !S.cd) { S.cd = true; rerenderRec(); return; }
  if (S.mode !== 'hold' && !S.cd) {
    const quiet = now - S.lastVoice > QUIET_MS;
    if (quiet !== S.quiet) { S.quiet = quiet; rerenderRec(); return; }
  }
  const txt = S.cd ? fmt(rem, true) : fmt(t);
  if (txt !== S.tmrText) {
    S.tmrText = txt;
    const el = S.layer.querySelector('.tmr');
    if (el) el.textContent = txt;
  }
  if (S.cd) {
    const fg = S.layer.querySelector('.ring .fg');
    if (fg) fg.setAttribute('stroke-dashoffset', (103.7 * (1 - Math.max(0, Math.min(1, rem / 60)))).toFixed(1));
  }
  if (now - S.levelAt > 150) S.level *= .85;
  hist.unshift(S.level); hist.length = 8;
  const c = (NB - 1) / 2, still = reduceMotion();
  S.layer.querySelectorAll('.wave i').forEach((b, i) => {
    const dist = Math.min(7, Math.round(Math.abs(i - c)));
    const target = 3 + 21 * hist[dist] * PROF[dist] * (still ? .9 : (.72 + Math.random() * .4));
    bh[i] += (target - bh[i]) * (target > bh[i] ? .55 : .2);
    b.style.height = Math.max(3, Math.min(24, bh[i])).toFixed(1) + 'px';
  });
}

/* ---------------- idle handle ---------------- */
function handleRects() {
  const ap = anchorPoint();
  const bottom = ap.top ? innerHeight - MARGIN : ap.y;
  return { line: { x: ap.x - 22, y: bottom - 18, w: 44, h: 18 }, button: { x: ap.x - 20, y: bottom - 40, w: 40, h: 40, r: 20 } };
}
function setHandle(onOff) {
  S.handleOn = !!onOff;
  handleEl.hidden = !S.handleOn;
  hbEl.hidden = !S.handleOn;
  if (!S.handleOn) setHandleHover(false);
  placeHandle();
  kick();
}
function placeHandle() {
  const R = handleRects();
  handleEl.style.transform = `translate(${R.line.x}px, ${R.line.y}px)`;
  hb.place(R.button);
}
function setHandleHover(v) {
  if (v === S.handleHover) return;
  S.handleHover = v;
  handleEl.classList.toggle('hov', v);
  hbEl.style.pointerEvents = v ? 'auto' : 'none';
  hbEl.innerHTML = v ? I('mic') : '';
  const now = performance.now();
  if (v) { hb.s.set(.4); hb.o.animate(1, 'appear', now); hb.s.animate(1, 'appear', now); }
  else { hb.o.animate(0, 'dismiss', now); hb.s.animate(.4, 'dismiss', now); }
  kick();
}

/* ---------------- frame loop ---------------- */
let raf = 0;
function kick() { if (!raf) raf = requestAnimationFrame(loop); }
function loop(now) {
  raf = 0;
  const out = [];
  let busy = false;
  const cf = cap.apply(now);
  if (cf.o > .001 || cap.busy()) out.push(cap.geo(cf));
  busy = busy || cap.busy();
  buds = buds.filter(b => {
    const f = b.apply(now);
    const moving = b.busy();
    if (b.gone && !moving) { b.el.remove(); return false; }
    out.push(b.geo(f));
    busy = busy || moving;
    return true;
  });
  if (S.handleOn) {
    const R = handleRects();
    out.push({ id: 'handle', x: R.line.x, y: R.line.y, w: R.line.w, h: R.line.h, r: 0, a: S.hidden ? 1 : 0, glass: false, hit: S.hidden });
    const hf = hb.apply(now);
    if (hf.o > .001) out.push(hb.geo(hf));
    busy = busy || hb.busy();
  }
  if (S.hidden && !cap.busy() && S.layer) { S.layer.remove(); S.layer = null; }
  const g = JSON.stringify(out);
  if (g !== S.lastGeo) { S.lastGeo = g; post({ t: 'geo', s: out }); }
  tickRec(now);
  if (busy || S.st === 'rec') kick();
}

/* ---------------- input ---------------- */
function act(a) {
  const msg = { t: 'act', a };
  if (a === 'done' || a === 'replace') { const f = $('#cardField'); msg.text = f ? f.value : ''; }
  post(msg);
}
stage.addEventListener('click', e => {
  const b = e.target.closest('[data-act]');
  if (b) act(b.dataset.act);
});
capEl.addEventListener('keydown', e => {
  if (e.target.id !== 'cardField') return;
  if (e.isComposing || e.keyCode === 229) return;
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    const b = capEl.querySelector('.layer:not(.leave) [data-act="replace"], .layer:not(.leave) [data-act="done"]');
    if (b) act(b.dataset.act);
  } else if (e.key === 'Escape') { e.preventDefault(); act('close'); }
});
let liveT = 0;
capEl.addEventListener('input', e => {
  if (e.target.id !== 'cardField') return;
  clearTimeout(liveT);
  const v = e.target.value;
  liveT = setTimeout(() => post({ t: 'edit', text: v }), 250);
});
capEl.addEventListener('focusin', e => { if (e.target.id === 'cardField') post({ t: 'field', focus: true }); });
capEl.addEventListener('focusout', e => { if (e.target.id === 'cardField') post({ t: 'field', focus: false }); });

// The panel never becomes key for plain clicks, so WebKit gets no hover;
// Python polls the pointer and hands it over.
function pointer(x, y) {
  let over = null;
  if (x != null) over = document.elementFromPoint(x, y);
  const btn = over ? over.closest('button') : null;
  if (btn !== S.hovBtn) {
    if (S.hovBtn) S.hovBtn.classList.remove('hov');
    if (btn) btn.classList.add('hov');
    S.hovBtn = btn;
  }
  const onCap = !!(over && !S.hidden && (over.closest('#cap') || over.closest('.bud')));
  if (onCap !== S.hover) { S.hover = onCap; post({ t: 'hover', on: onCap }); }
  if (S.handleOn) setHandleHover(!!(over && (over.closest('#handle') || over.closest('#hb'))) && S.hidden);
}

/* ---------------- messages from Python ---------------- */
on('show', m => {
  const d = m.d || {};
  if (m.st === 'rec') {
    const now = performance.now();
    const entering = S.st !== 'rec';
    if (d.elapsed != null) S.recAt = now - (+d.elapsed) * 1000;
    else if (entering) S.recAt = now;
    if (entering) { S.lastVoice = now; S.quiet = false; S.cd = false; }
    S.mode = d.mode || 'click';
    if (d.max != null) S.max = +d.max;
  }
  if (m.st === 'download' && S.st === 'download' && !S.hidden && S.layer) { updateDownload(d); return; }
  S.d = d;
  render(m.st, d);
});
on('hide', hide);
on('level', m => {
  S.level = Math.max(0, Math.min(1, +m.v || 0));
  S.levelAt = performance.now();
  if (S.level > VOICE) {
    S.lastVoice = S.levelAt;
    if (S.quiet && S.st === 'rec') { S.quiet = false; rerenderRec(); }
  }
});
on('pointer', m => pointer(m.x, m.y));
on('env', m => { env(m); S.native = !!m.native; document.documentElement.classList.toggle('native', S.native); });
on('anchor', m => { S.anchor = { mode: m.mode || 'bottom', x: m.x == null ? null : +m.x, y: m.y == null ? null : +m.y }; placeHandle(); relayout(); });
on('handle', m => setHandle(m.on));
on('focus', focusField);
addEventListener('resize', () => { placeHandle(); relayout(); });

window.app.debug = { S, view, render, hide, layout };
post({ t: 'ready' });
})();
