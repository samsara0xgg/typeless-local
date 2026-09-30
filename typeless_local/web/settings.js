/* Settings. Python sends the whole state ({t:'state'}) whenever it changes;
   this page only draws it and reports what the user changed. Nothing is kept
   here that Python does not also know, except what is being typed. */
(() => {
'use strict';
const { I, esc, $, $$, post, on, env } = kit;

const PANES = [
  ['general', '通用', 'gear', '#8E8E93'],
  ['dictation', '听写', 'wave', '#007AFF'],
  ['keys', '快捷键', 'keyboard', '#636366'],
  ['model', '润色模型', 'sparkles', '#AF52DE'],
  ['vocab', '词库', 'book', '#FF9500'],
  ['audio', '音频', 'speaker', '#FF3B30'],
  ['privacy', '历史与隐私', 'shield', '#0A84FF'],
];
const DAYS = { 30: '30 天', 90: '90 天', 365: '1 年', 0: '永久' };
const LANGS = [['', '自动（中英混说）'], ['zh', '中文'], ['en', 'English']];

let S = null;            // the state Python sent
let pane = 'general';
// What is being edited here and not yet sent.
const UI = { keyEdit: '', keyBusy: '', keyMsg: {}, test: null, confirm: null, vocabMsg: '' };

/* ---------------- building blocks ---------------- */
const sw = (key, on_, label, disabled = false) =>
  `<button class="sw" role="switch" aria-checked="${!!on_}" aria-label="${esc(label)}" data-set="${key}"${disabled ? ' disabled' : ''}></button>`;
const select = (key, value, options, label) =>
  `<select class="pop" data-set="${key}" aria-label="${esc(label)}">${options.map(([v, t]) =>
    `<option value="${esc(v)}"${String(v) === String(value) ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select>`;
const seg = (key, value, options) =>
  `<span class="msg" role="radiogroup">${options.map(([v, t]) =>
    `<button role="radio" aria-checked="${String(v) === String(value)}" data-set="${key}" data-v="${esc(v)}">${esc(t)}</button>`).join('')}</span>`;
const row = (label, control, note = '', cls = '') =>
  `<div class="row ${cls}"><div class="rl">${label}${note ? `<small>${note}</small>` : ''}</div>${control}</div>`;
const grp = (rows, extra = '') => `<div class="grp">${rows.join('')}${extra}</div>`;
const head = t => `<div class="pane-h"><b>${esc(t)}</b></div>`;

/* ---------------- panes ---------------- */
function general() {
  const p = S.prefs, login = S.login;
  const loginNote = login === 'unavailable' ? '只有安装好的 App 才能设置，从源码运行时不可用。'
    : login === 'requires_approval' ? '需要在「系统设置 › 通用 › 登录项」里允许。' : '';
  const loginCtl = login === 'requires_approval'
    ? `<span class="inline">${sw('login', true, '登录时打开')}<button class="mbtn" data-act="open" data-what="login">打开登录项…</button></span>`
    : sw('login', login === 'enabled', '登录时打开', login === 'unavailable');
  return head('通用')
    + grp([
      row(`登录时打开${esc(S.name)}`, loginCtl, loginNote),
      row('胶囊位置', seg('capsule_position', p.capsule_position, [['bottom', '屏幕底部'], ['caret', '跟随光标']]), '跟随光标需要目标 App 提供光标位置；拿不到时回到屏幕底部。'),
      row('显示底部把手', sw('show_handle', p.show_handle, '显示底部把手'), '空闲时在 Dock 上方留一道细线，悬停变成麦克风按钮。'),
      row('结果停留', select('dismiss_seconds', p.dismiss_seconds, S.choices.dismiss_seconds.map(v => [v, `${v} 秒`]), '结果停留'), '指针停在胶囊上时不计时；接着打字会立刻收起。'),
    ])
    + grp([row('提示音', select('sounds', p.sounds, [['off', '关闭'], ['start_end', '仅开始和结束']], '提示音'))]);
}

function dictation() {
  const p = S.prefs;
  return head('听写')
    + grp([
      row('识别语言', select('language', S.language, LANGS, '识别语言'), '自动能识别中英混说；固定一种语言会快一点。'),
      row('语音模型', `<span class="val">${esc(S.asrModel || '—')} · 本地</span>`),
      row('单次最长录音', select('max_minutes', p.max_minutes, S.choices.max_minutes.map(v => [v, `${v} 分钟`]), '单次最长录音'), '最后 60 秒会倒计时。'),
    ])
    + grp([
      row('润色', sw('refine', p.refine, '润色'), '去掉口头禅、处理改口、补标点和分段。'),
      row('润色超时或失败时', '<span class="val">插入原始转写</span>', '胶囊里可以一键重新润色。'),
      row('改写所选文字', sw('rewrite_selection', p.rewrite_selection, '改写所选文字'), '先选中文字再按 F5，说出要求，例如“改得更正式”“翻成英文”。'),
      row('没有输入框时', '<span class="val">显示卡片并复制</span>', '结果放进可以修改的卡片，同时复制到剪贴板。'),
    ]);
}

function keys() {
  const top = ['esc', 'F1', 'F2', 'F3', 'F4', '', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12'];
  const kb = `<div class="kb" aria-hidden="true">${top.map(k => k ? `<i>${k}</i>` : `<i class="hot">${I('mic')}</i>`).join('')}<i class="w2"></i>`
    + `<i>fn</i><i>⌃</i><i>⌥</i><i class="w2">⌘</i><i class="w6">space</i><i class="w2 hot">⌘</i><i>⌥</i><i>←→</i></div>`;
  const conflict = S.f5 ? grp([row(`系统听写也在用 ${I('mic')} 键`, '<button class="mbtn" data-act="open" data-what="keyboard">打开键盘设置…</button>',
    'Apple 芯片键盘上 F5 就是听写键，两个都开会互相抢。在键盘设置里把系统听写的快捷键换掉或关闭。', 'warnrow')]) : '';
  return head('快捷键') + kb
    + grp([
      row('开始 / 结束', '<span class="kbd2"><kbd>F5</kbd><span class="arrow">或</span><kbd>右 ⌘</kbd><span class="arrow">轻点</span></span>'),
      row('按住说话', '<span class="kbd2"><span class="arrow">按住</span><kbd>F5</kbd></span>', '按住超过 0.6 秒，松开就完成。'),
      row('锁定（免手持）', '<span class="kbd2"><span class="arrow">连按两下</span><kbd>F5</kbd><span class="arrow">·</span><kbd>F5</kbd><kbd>Space</kbd><span class="arrow">·</span><kbd>右 ⌘</kbd><kbd>Space</kbd></span>'),
      row('取消', '<span class="kbd2"><kbd>esc</kbd></span>'),
    ])
    + conflict;
}

function model() {
  const rows = S.presets.map(m => `<tr data-preset="${esc(m.name)}" aria-selected="${m.name === S.active}">
    <td><span class="rad${m.name === S.active ? ' on' : ''}"></span></td><td>${esc(m.name)}<br><small class="arrow">${esc(m.model)}</small></td>
    <td>${esc(m.service)}</td><td class="${m.hasKey ? 'st-ok' : 'st-no'}">${m.hasKey ? '已设置' : '需要 Key'}</td>
    <td class="num">${m.median ? (m.median / 1000).toFixed(1) + ' 秒' : '—'}</td></tr>`).join('');
  const t = UI.test;
  const testLine = !t ? '' : t.busy ? `<span class="val"><span class="spin"></span> 正在发送一次测试请求…</span>`
    : t.ok ? `<span class="st-ok">已连接 · ${esc(t.preset)} · 往返 ${(t.ms / 1000).toFixed(1)} 秒</span>`
    : `<span class="st-err">${esc(t.msg || '连接失败')}</span>`;
  const table = S.presets.length
    ? `<table class="lst"><thead><tr><th></th><th>模型</th><th>服务</th><th>Key</th><th class="num">中位延迟</th></tr></thead><tbody>${rows}</tbody></table>`
    : '<div class="row"><span class="empty">配置里没有润色模型。</span></div>';
  const keyRows = S.keys.map(keyRow);
  const envKeys = S.keys.filter(k => k.where === 'env');
  const migrate = envKeys.length
    ? `<p class="note">${envKeys.map(k => esc(k.env)).join('、')} 还以明文存在 ~/.typlus/env 里。<button class="mbtn" data-act="migrate">移到钥匙串</button></p>` : '';
  return head('润色模型')
    + (S.prefs.refine ? '' : '<p class="note">润色已关闭，听写会直接插入原始转写。可以在「听写」里打开。</p>')
    + `<div class="grp">${table}<div class="btnrow">${testLine}<button class="mbtn" data-act="test"${t && t.busy ? ' disabled' : ''}>测试连接</button></div></div>`
    + `<div class="grp-l">API Key · 保存在钥匙串</div>` + grp(keyRows) + migrate
    + '<p class="note">中位延迟来自最近 50 次润色；关掉历史记录后不再统计。</p>';
}

function keyRow(k) {
  const where = { keychain: '已保存', env: '明文保存在 env 文件', environ: '来自环境变量', '': '未设置' }[k.where] || '';
  const hint = [k.env, k.hint || where].filter(Boolean).join(' · ');
  const msg = UI.keyMsg[k.env];
  const msgLine = msg ? `<small class="${msg.ok ? 'st-ok' : 'st-err'}">${esc(msg.text)}</small>` : '';
  if (UI.keyEdit === k.env) {
    const busy = UI.keyBusy === k.env;
    return `<div class="row"><div class="rl">${esc(k.service)}<small>${esc(k.env)}</small>${msgLine}</div>
      <span class="inline"><input class="field" id="key-${esc(k.env)}" type="password" placeholder="粘贴 API Key" autocomplete="off" spellcheck="false" style="width:220px" aria-label="${esc(k.service)} API Key">
      <button class="mbtn pri" data-act="savekey" data-env="${esc(k.env)}"${busy ? ' disabled' : ''}>${busy ? '<span class="spin"></span>' : '保存'}</button>
      <button class="mbtn" data-act="cancelkey">取消</button></span></div>`;
  }
  return `<div class="row"><div class="rl">${esc(k.service)}<small>${esc(hint)}</small>${msgLine}</div>
    <button class="mbtn${k.where ? '' : ' pri'}" data-act="editkey" data-env="${esc(k.env)}">${k.where ? '更换…' : '添加…'}</button></div>`;
}

function vocab() {
  const v = S.vocab;
  const mine = v.mine.map(w => `<span class="wchip">${esc(w)}<button data-act="unword" data-term="${esc(w)}" aria-label="删除 ${esc(w)}">${I('xmark')}</button></span>`).join('');
  const suggest = v.suggest.length ? v.suggest.map(s => row(`${esc(s.term)}`,
    `<span class="inline"><button class="mbtn" data-act="reject" data-term="${esc(s.term)}">忽略</button><button class="mbtn pri" data-act="word" data-term="${esc(s.term)}">加入</button></span>`,
    s.n ? `最近 30 天出现 ${s.n} 次` : '')) : [row('<span class="empty">暂时没有建议。多听写几天，这里会列出常被写错的词。</span>', '')];
  const fixes = v.fixes.length ? v.fixes.map(f => row(`${f.wrong ? `<span class="del">${esc(f.wrong)}</span> <span class="arrow">→</span> ` : ''}${esc(f.right)}`,
    v.mine.includes(f.right) ? '<span class="val">已在词库</span>' : `<button class="mbtn" data-act="word" data-term="${esc(f.right)}">加入词库</button>`, esc(f.at || ''))) : [row('<span class="empty">在胶囊的修改卡片里改过的词会出现在这里。</span>', '')];
  return head('词库')
    + '<div class="grp-l">我的词 · 同时提示给语音识别和润色模型</div>'
    + `<div class="grp"><div class="chipset">${mine}<input class="field" id="newword" placeholder="添加词，回车确认" aria-label="添加词"></div></div>`
    + (UI.vocabMsg ? `<p class="note">${esc(UI.vocabMsg)}</p>` : '')
    + '<div class="grp-l">建议加入 · 从最近的润色差异里找出</div>' + grp(suggest)
    + '<div class="grp-l">最近的手动修改</div>' + grp(fixes);
}

function audio() {
  const inputs = [['', '系统默认'], ...S.inputs.map(n => [n, n])];
  if (S.input && !S.inputs.includes(S.input)) inputs.push([S.input, `${S.input}（未连接）`]);
  return head('音频')
    + grp([row('输入设备', select('input', S.input, inputs, '输入设备'), '每次录音都会重新读取设备；选中的设备不在时用系统默认。')])
    + grp([
      row('录音时静音其他声音', sw('duck', S.duck, '录音时静音其他声音'), '使用带回声消除的耳机时自动跳过。录音结束或意外退出后都会恢复。'),
      row('静音时在胶囊里提示', sw('show_ducked', S.prefs.show_ducked, '静音时在胶囊里提示'), '显示一个小喇叭斜杠，让你知道音乐停了是谁干的。'),
    ]);
}

function privacy() {
  const p = S.prefs, c = UI.confirm;
  const confirmBox = !c ? '' : c.kind === 'days'
    ? `<div class="confirm"><span>${c.n ? `会删除 ${c.n} 条 ${esc(DAYS[c.days])}以前的听写。` : `以后只保留最近 ${esc(DAYS[c.days])}。`}</span><button class="mbtn" data-act="cancelconfirm">取消</button><button class="mbtn pri" data-act="confirmdays">${c.n ? '删除并保留' : '好'}</button></div>`
    : `<div class="confirm"><span>${c.n ? `删除全部 ${c.n} 条听写历史？不能撤销。` : '现在没有听写历史。'}</span><button class="mbtn" data-act="cancelconfirm">取消</button>${c.n ? '<button class="mbtn pri" data-act="confirmclear">全部删除</button>' : ''}</div>`;
  const days = select('history_days', c && c.kind === 'days' ? c.days : p.history_days, S.choices.history_days.map(v => [v, DAYS[v] || `${v} 天`]), '保留');
  return head('历史与隐私')
    + grp([
      row('保存听写历史', sw('save_history', p.save_history, '保存听写历史'), `文字、耗时和 App 名称存在这台 Mac 上；${S.history.count ? `现在有 ${S.history.count} 条，` : ''}从不保存音频。`),
      row('保留', days),
    ], c && c.kind === 'days' ? confirmBox : '')
    + '<div class="grp-l">发送给润色模型的内容</div>'
    + grp([
      row('原始转写文字', '<span class="st-ok">发送</span>'),
      row('当前 App 名称和窗口标题', sw('send_window_title', p.send_window_title, '发送窗口标题'), '用来判断语气。窗口标题可能包含文件名或邮件主题。'),
      row('所选文字', sw('rewrite_selection', p.rewrite_selection, '发送所选文字'), '只在“改写所选文字”时发送。'),
      row('音频', '<span class="val">从不离开这台 Mac</span>'),
    ])
    + `<div class="grp" style="background:transparent; box-shadow:none">${c && c.kind === 'clear' ? `<div class="grp">${confirmBox}</div>` : ''}<div class="btnrow left"><button class="mbtn" data-act="open" data-what="data">${I('folder')} 在访达中显示数据</button><button class="mbtn danger" data-act="clear">${I('trash')} 清除历史…</button></div></div>`;
}

const RENDER = { general, dictation, keys, model, vocab, audio, privacy };

/* ---------------- drawing ---------------- */
function drawSide() {
  $('#side').innerHTML = PANES.map(([id, t, ic, c]) =>
    `<button role="tab" aria-selected="${id === pane}" data-pane="${id}"><span class="tile" style="background:${c}">${I(ic)}</span>${t}</button>`).join('')
    + `<div class="foot">${S ? esc(`${S.name} ${S.version || ''}`) : ''}</div>`;
}

function draw() {
  if (!S) return;
  // Keep what is being typed across a redraw.
  const a = document.activeElement, id = a && a.id, val = a && 'value' in a ? a.value : null;
  const sel = a && a.selectionStart != null ? [a.selectionStart, a.selectionEnd] : null;
  drawSide();
  const main = $('#panes'), top = main.scrollTop;
  main.innerHTML = `<section class="pane" role="tabpanel" aria-label="${esc(PANES.find(p => p[0] === pane)[1])}">${RENDER[pane]()}</section>`;
  main.scrollTop = top;
  if (id) {
    const el = document.getElementById(id);
    if (el) { if (val != null) el.value = val; el.focus(); if (sel) try { el.setSelectionRange(sel[0], sel[1]); } catch (e) { /* select */ } }
  }
  reportGlass();
}

function show(id) {
  if (!RENDER[id]) return;
  pane = id;
  UI.confirm = null;
  draw();
  $('#panes').scrollTop = 0;
}

/* ---------------- native glass under the sidebar ---------------- */
let lastGeo = '';
function reportGlass() {
  const r = $('#side').getBoundingClientRect();
  const s = [{ id: 'side', x: r.left, y: r.top, w: r.width, h: r.height, r: parseFloat(getComputedStyle($('#side')).borderTopLeftRadius) || 18, a: 1, glass: true, hit: false }];
  const key = JSON.stringify(s);
  if (key !== lastGeo) { lastGeo = key; post({ t: 'geo', s }); }
}
window.addEventListener('resize', reportGlass);

/* ---------------- input ---------------- */
function value(el) {
  if (el.classList.contains('sw')) return el.getAttribute('aria-checked') !== 'true';
  if (el.dataset.v != null) return el.dataset.v;
  return el.value;
}
const NUMERIC = new Set(['dismiss_seconds', 'max_minutes', 'history_days']);

function setting(el) {
  const key = el.dataset.set;
  let v = value(el);
  if (NUMERIC.has(key)) v = Number(v);
  if (key === 'history_days' && v !== 0 && v !== S.prefs.history_days) {
    // Shortening the history deletes what is older: ask first, in place.
    UI.confirm = { kind: 'days', days: v, n: null };
    post({ t: 'count', days: v });
    draw();
    return;
  }
  // Optimistic: switches flip at once; Python's next state settles it.
  if (key in S.prefs) S.prefs[key] = v;
  if (key === 'duck') S.duck = v;
  post({ t: 'set', key, value: v });
  draw();
}

document.addEventListener('click', e => {
  const tab = e.target.closest('[data-pane]');
  if (tab) { show(tab.dataset.pane); return; }
  const set = e.target.closest('button[data-set]');
  if (set && !set.disabled) { setting(set); return; }
  const preset = e.target.closest('tr[data-preset]');
  if (preset && preset.dataset.preset !== S.active) { S.active = preset.dataset.preset; post({ t: 'set', key: 'preset', value: S.active }); draw(); return; }
  const act = e.target.closest('[data-act]');
  if (!act || act.disabled) return;
  const a = act.dataset.act;
  if (a === 'open') post({ t: 'open', what: act.dataset.what });
  else if (a === 'test') { UI.test = { busy: true }; post({ t: 'test' }); draw(); }
  else if (a === 'editkey') { UI.keyEdit = act.dataset.env; delete UI.keyMsg[UI.keyEdit]; draw(); const f = document.getElementById(`key-${UI.keyEdit}`); if (f) f.focus(); }
  else if (a === 'cancelkey') { UI.keyEdit = ''; draw(); }
  else if (a === 'savekey') saveKey(act.dataset.env);
  else if (a === 'migrate') post({ t: 'migrate' });
  else if (a === 'word') post({ t: 'vocab', op: 'add', term: act.dataset.term });
  else if (a === 'unword') post({ t: 'vocab', op: 'remove', term: act.dataset.term });
  else if (a === 'reject') post({ t: 'vocab', op: 'reject', term: act.dataset.term });
  else if (a === 'clear') { UI.confirm = { kind: 'clear', n: S.history.count }; draw(); }
  else if (a === 'cancelconfirm') { UI.confirm = null; draw(); }
  else if (a === 'confirmdays') { const d = UI.confirm.days; UI.confirm = null; S.prefs.history_days = d; post({ t: 'set', key: 'history_days', value: d }); draw(); }
  else if (a === 'confirmclear') { UI.confirm = null; post({ t: 'clear' }); draw(); }
});

document.addEventListener('change', e => {
  const el = e.target.closest('select[data-set]');
  if (el) setting(el);
});

document.addEventListener('keydown', e => {
  if (e.target.id === 'newword' && e.key === 'Enter') {
    const term = e.target.value.trim();
    if (term) { post({ t: 'vocab', op: 'add', term }); e.target.value = ''; }
    e.preventDefault();
  } else if (e.target.id && e.target.id.startsWith('key-')) {
    if (e.key === 'Enter') { e.preventDefault(); saveKey(e.target.id.slice(4)); }
    if (e.key === 'Escape') { e.preventDefault(); UI.keyEdit = ''; draw(); }
  } else if (e.key === 'Escape' && UI.confirm) { UI.confirm = null; draw(); }
  else if ((e.metaKey || e.ctrlKey) && /^[1-7]$/.test(e.key)) { e.preventDefault(); show(PANES[+e.key - 1][0]); }
});

function saveKey(envName) {
  const f = document.getElementById(`key-${envName}`);
  const v = f ? f.value.trim() : '';
  if (!v) { if (f) f.focus(); return; }
  UI.keyBusy = envName;
  post({ t: 'key', env: envName, value: v });
  draw();
}

/* ---------------- from Python ---------------- */
on('env', m => { env(m); document.body.classList.toggle('has-glass', !!m.native); });
on('state', m => { S = m; draw(); });
on('pane', m => show(m.id));
on('keyResult', m => {
  UI.keyBusy = '';
  UI.keyMsg[m.env] = { ok: m.ok, text: m.msg };
  if (m.ok) UI.keyEdit = '';
  draw();
});
on('testResult', m => { UI.test = m; draw(); });
on('count', m => { if (UI.confirm && UI.confirm.kind === 'days' && UI.confirm.days === m.days) { UI.confirm.n = m.n; draw(); } });
on('vocabResult', m => { UI.vocabMsg = m.msg || ''; draw(); });

drawSide();
post({ t: 'ready' });
})();
