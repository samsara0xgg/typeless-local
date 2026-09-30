/* History: every dictation the trace kept, newest first, grouped by day, with
   what the model changed and where the time went. Python sends the rows
   ({t:'items'}); copying, deleting and adding a word go back to it. */
(() => {
'use strict';
const { I, esc, $, $$, post, on, env } = kit;

const COLORS = ['#007AFF', '#34C759', '#FF9500', '#AF52DE', '#FF2D55', '#5856D6', '#30B0C7', '#A2845E'];
const FALLBACK = {
  timeout: '润色超时，插入的是原始转写',
  error: '润色出错，插入的是原始转写',
  key: '没有 API Key，插入的是原始转写',
  truncated: '润色结果不完整，插入的是原始转写',
  empty: '模型没有返回内容，插入的是原始转写',
};
const FALLBACK_SHORT = { timeout: '超时', error: '出错', key: '没有 Key', truncated: '不完整', empty: '没有返回' };

let D = { enabled: true, items: [], vocab: [] };
let sel = null;           // id of the selected row
let query = '';
let armedDelete = 0;      // id waiting for a second click on 删除
let selection = '';       // text selected in the detail
let ready = false;

/* ---------------- formatting ---------------- */
const pad = n => String(n).padStart(2, '0');
const hhmm = d => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const secs = ms => (ms / 1000).toFixed(1);
function dayLabel(d) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const that = new Date(d); that.setHours(0, 0, 0, 0);
  const days = Math.round((today - that) / 86400000);
  if (days === 0) return '今天';
  if (days === 1) return '昨天';
  const week = '日一二三四五六'[d.getDay()];
  return d.getFullYear() === today.getFullYear()
    ? `${d.getMonth() + 1}月${d.getDate()}日 星期${week}`
    : `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
}
function appTile(name) {
  const letter = (name || '').trim().charAt(0).toUpperCase() || '·';
  let h = 0;
  for (const ch of name || '') h = (h * 31 + ch.codePointAt(0)) >>> 0;
  const color = name ? COLORS[h % COLORS.length] : '#8E8E93';
  return `<span class="appico" style="background:${color}" aria-hidden="true">${esc(letter)}</span>`;
}
const shown = it => it.text || it.raw;

/* ---------------- diff (raw transcript -> what was inserted) ---------------- */
const tok = s => String(s).match(/[A-Za-z0-9][A-Za-z0-9._\-'+#]*|\s+|[^\sA-Za-z0-9]/gu) || [];
function diff(a, b) {
  const A = tok(a), B = tok(b), n = A.length, m = B.length;
  if (n * m > 250000) return [['-', a], ['+', b]];
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = [];
  const push = (o, t) => { const l = out[out.length - 1]; if (l && l[0] === o) l[1] += t; else out.push([o, t]); };
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { push('=', A[i]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { push('-', A[i]); i++; }
    else { push('+', B[j]); j++; }
  }
  while (i < n) push('-', A[i++]);
  while (j < m) push('+', B[j++]);
  return out;
}
const diffHTML = (a, b) => diff(a, b).map(([o, t]) => o === '=' ? esc(t) : `<span class="${o === '-' ? 'del' : 'ins'}">${esc(t)}</span>`).join('');

// Whether the text went out different from how it was pasted.
const norm = t => (t || '').split(/\s+/).join(' ').trim();
const edited = it => !!it.sent && !!it.text && norm(it.sent) !== norm(it.text);

// A term worth offering for the vocabulary: one he typed in by hand before
// sending, or one the model put in that the recognizer did not hear.
function suggestion(it) {
  if (!it.text || it.fallback) return '';
  const known = new Set((D.vocab || []).map(t => t.toLowerCase()));
  const word = w => /^[A-Za-z][A-Za-z0-9._\-+#]{2,}$/.test(w) && !known.has(w.toLowerCase());
  if (edited(it)) {
    const had = new Set(tok(it.text).map(t => t.toLowerCase()));
    for (const [o, t] of diff(it.text, it.sent)) {
      if (o === '+') for (const w of tok(t)) if (word(w) && !had.has(w.toLowerCase())) return w;
    }
  }
  if (!it.raw) return '';
  const heard = new Set(tok(it.raw).map(t => t.toLowerCase()));
  for (const [o, t] of diff(it.raw, it.text)) {
    if (o !== '+') continue;
    for (const w of tok(t)) {
      if (/^[A-Za-z][A-Za-z0-9._\-+#]{2,}$/.test(w) && !heard.has(w.toLowerCase()) && !known.has(w.toLowerCase())) return w;
    }
  }
  return '';
}

/* ---------------- drawing ---------------- */
function visible() {
  const q = query.trim().toLowerCase();
  if (!q) return D.items;
  return D.items.filter(it => [it.text, it.raw, it.sent, it.app, it.window].some(v => (v || '').toLowerCase().includes(q)));
}

function listHTML(items) {
  let out = `<label class="hsearch">${I('search')}<input id="q" type="search" placeholder="搜索" aria-label="搜索历史记录" value="${esc(query)}"></label>`;
  if (!D.enabled) out += '<div class="hday">历史记录已关闭，新的听写不会保存</div>';
  if (!items.length) return out + `<div class="hday">${query ? '没有找到' : ''}</div>`;
  let day = '';
  for (const it of items) {
    const d = new Date(it.at * 1000), label = dayLabel(d);
    if (label !== day) { day = label; out += `<div class="hday">${esc(label)}</div>`; }
    const meta = [hhmm(d), it.app || '未知 App', `${it.audio_s.toFixed(1)} 秒`];
    if (it.dropped) meta.push('没有插入');
    else if (it.fallback) meta.push('未润色');
    if (edited(it)) meta.push('发送前改过');
    out += `<button class="hitem" role="option" id="h${it.id}" aria-selected="${it.id === sel}" data-h="${it.id}">${appTile(it.app)}<span class="ht">${esc(shown(it))}</span><span class="hm">${esc(meta.join(' · '))}</span></button>`;
  }
  return out;
}

function detailHTML(it) {
  if (!it) return '';
  const d = new Date(it.at * 1000);
  const where = [it.app || '未知 App', it.window, `${dayLabel(d)} ${hhmm(d)}`].filter(Boolean).join(' · ');
  let box;
  if (it.dropped) box = `<span class="l">像是噪音里的幻听，没有插入</span>${esc(it.raw)}`;
  else if (it.fallback) box = `<span class="l">${esc(FALLBACK[it.fallback] || FALLBACK.error)}</span>${esc(it.raw)}`;
  else if (it.raw && it.raw !== it.text) box = `<span class="l">原始转写 → 润色</span>${diffHTML(it.raw, it.text)}`;
  else box = '<span class="l">原始转写</span>和润色结果一样';
  const sentBox = edited(it) ? `<div class="rawbox selectable"><span class="l">发送前你改成了</span>${diffHTML(it.text, it.sent)}</div>` : '';

  const metrics = [`录音 ${it.audio_s.toFixed(1)} 秒`];
  if (it.asr_ms) metrics.push(`转写 ${secs(it.asr_ms)} 秒`);
  if (it.fallback) metrics.push(`润色${FALLBACK_SHORT[it.fallback] || '出错'}`);
  else if (it.refine_ms) metrics.push(`润色 ${secs(it.refine_ms)} 秒`);
  if (it.total_ms) metrics.push(`总共 ${secs(it.total_ms)} 秒`);
  if (it.model) metrics.push(it.model);
  if (!it.dropped) metrics.push(it.pasted ? '已插入' : '在剪贴板里');

  let lat = '';
  if (it.total_ms > 0) {
    const asr = Math.min(it.asr_ms, it.total_ms), ref = Math.min(it.refine_ms, it.total_ms - asr);
    const pct = v => (v / it.total_ms * 100).toFixed(1);
    const rc = it.fallback ? 'var(--orange)' : 'var(--accent)';
    lat = `<div class="latbar" aria-hidden="true"><i style="width:${pct(asr)}%; background:#AF52DE"></i><i style="width:${pct(ref)}%; background:${rc}"></i><i style="flex:1; background:var(--win-fg-3)"></i></div>`
      + `<div class="latlegend"><span><b style="background:#AF52DE"></b>转写</span><span><b style="background:${rc}"></b>润色</span><span><b style="background:var(--win-fg-3)"></b>其余</span></div>`;
  }

  const word = selection || suggestion(it);
  const acts = [`<button class="mbtn" data-a="copy">${I('copy')} 复制</button>`];
  if (word) acts.push(`<button class="mbtn pri" data-a="vocab" data-term="${esc(word)}">${I('book')} 把“${esc(word)}”加入词库</button>`);
  acts.push(armedDelete === it.id
    ? `<button class="mbtn danger" data-a="delete">${I('trash')} 确认删除</button>`
    : `<button class="mbtn" data-a="delete">${I('trash')} 删除</button>`);

  return `<div class="appcell">${appTile(it.app)}<span>${esc(where)}</span></div>
<p class="big selectable">${esc(shown(it))}</p>
<div class="rawbox selectable">${box}</div>
${sentBox}<div class="metrics">${metrics.map(m => `<span>${esc(m)}</span>`).join('')}</div>
${lat}<div class="hact">${acts.join('')}</div>`;
}

function emptyHTML() {
  if (!D.enabled) {
    return `<div class="hempty">${I('clock')}<b>历史记录已关闭</b><span>打开后，每次听写的原文、润色结果和耗时都会保存在这台 Mac 上。</span><button class="mbtn pri" data-a="settings">打开设置</button></div>`;
  }
  return `<div class="hempty">${I('wave')}<b>还没有听写</b><span>按 F5 说一句话，它会出现在这里。</span></div>`;
}

function draw() {
  const root = $('#root');
  if (!D.items.length) { root.innerHTML = emptyHTML(); reportGlass(); return; }
  const items = visible();
  if (!items.some(it => it.id === sel)) sel = items.length ? items[0].id : null;
  const it = D.items.find(x => x.id === sel);
  const typing = document.activeElement?.id === 'q';
  const caret = typing ? $('#q').selectionStart : 0;
  const scroll = $('#hlist')?.scrollTop || 0;
  root.innerHTML = `<div class="hist"><nav class="hlist" id="hlist" role="listbox" aria-label="听写历史" tabindex="-1">${listHTML(items)}</nav><main class="hdet" id="hdet">${detailHTML(it)}</main></div>`;
  $('#hlist').scrollTop = scroll;
  if (typing) { const q = $('#q'); q.focus(); q.setSelectionRange(caret, caret); }
  reportGlass();
}

function drawDetail() {
  const it = D.items.find(x => x.id === sel);
  const det = $('#hdet');
  if (det) det.innerHTML = detailHTML(it);
}

function select(id, focus = false) {
  sel = id;
  armedDelete = 0;
  selection = '';
  $$('.hitem').forEach(b => b.setAttribute('aria-selected', String(+b.dataset.h === id)));
  drawDetail();
  const row = document.getElementById(`h${id}`);
  if (row) { row.scrollIntoView({ block: 'nearest' }); if (focus) row.focus(); }
}

/* ---------------- native glass under the list ---------------- */
let lastGeo = '';
function reportGlass() {
  const list = $('#hlist');
  const s = [];
  if (list) {
    const r = list.getBoundingClientRect();
    s.push({ id: 'list', x: r.left, y: r.top, w: r.width, h: r.height, r: parseFloat(getComputedStyle(list).borderTopLeftRadius) || 18, a: 1, glass: true, hit: false });
  }
  const key = JSON.stringify(s);
  if (key !== lastGeo) { lastGeo = key; post({ t: 'geo', s }); }
}
window.addEventListener('resize', reportGlass);

let toastTimer = 0;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('on'), 1600);
}

/* ---------------- input ---------------- */
document.addEventListener('click', e => {
  const row = e.target.closest('[data-h]');
  if (row) { select(+row.dataset.h); return; }
  const a = e.target.closest('[data-a]')?.dataset.a;
  if (!a) return;
  const it = D.items.find(x => x.id === sel);
  if (a === 'settings') post({ t: 'open', what: 'settings' });
  if (!it) return;
  if (a === 'copy') post({ t: 'copy', text: shown(it) });
  else if (a === 'vocab') { post({ t: 'vocab', term: e.target.closest('[data-a]').dataset.term }); selection = ''; }
  else if (a === 'delete') {
    if (armedDelete === it.id) { armedDelete = 0; post({ t: 'delete', id: it.id }); }
    else { armedDelete = it.id; drawDetail(); }
  }
});

document.addEventListener('input', e => {
  if (e.target.id === 'q') { query = e.target.value; draw(); }
});

document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'f') { e.preventDefault(); $('#q')?.focus(); return; }
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
  if (e.target.tagName === 'INPUT' && e.target.id !== 'q') return;
  const items = visible();
  const i = items.findIndex(it => it.id === sel);
  const next = items[Math.max(0, Math.min(items.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)))];
  if (next) { e.preventDefault(); select(next.id, e.target.id !== 'q'); }
});

// Selecting a word in the detail offers it for the vocabulary.
document.addEventListener('selectionchange', () => {
  const s = window.getSelection();
  const det = $('#hdet');
  let text = '';
  if (s && !s.isCollapsed && det && det.contains(s.anchorNode) && det.contains(s.focusNode)) {
    text = s.toString().trim();
    if (text.length > 24 || /\n/.test(text)) text = '';
  }
  if (text === selection) return;
  selection = text;
  const acts = $('#hdet .hact');
  const it = D.items.find(x => x.id === sel);
  if (!acts || !it) return;
  // Only the button row changes, so the selection itself survives.
  const tmp = document.createElement('div');
  tmp.innerHTML = detailHTML(it);
  acts.innerHTML = tmp.querySelector('.hact').innerHTML;
});

/* ---------------- from Python ---------------- */
on('env', m => { env(m); document.body.classList.toggle('has-glass', !!m.native); });
on('items', m => {
  D = { enabled: !!m.enabled, items: m.items || [], vocab: m.vocab || [] };
  if (!ready && D.items.length) sel = D.items[0].id;
  ready = true;
  armedDelete = 0;
  draw();
});
on('toast', m => toast(m.msg || ''));

post({ t: 'ready' });
})();
