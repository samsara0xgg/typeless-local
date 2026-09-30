/* The first-run guide: welcome, microphone, Accessibility, API key, speech
   model, one practice dictation, done. Python sends what is already granted
   ({t:'state'}) and redraws it whenever a permission changes, so a step that
   is already done shows as done and one being waited on continues by itself. */
(() => {
'use strict';
const { I, esc, $, post, on, env } = kit;

const LAST = 6;
let S = null;             // what Python last sent
let step = 0;
// Per-step progress that only this page knows about.
const UI = { asked: '', key: null, keyBusy: false, dl: null, practiced: false };
let advanceTimer = 0;

const tile = (n, c) => `<div class="sym" style="background:${c}">${I(n)}</div>`;
const icon = () => '<div class="sym ico"><img src="appicon.svg" alt=""></div>';
const status = (text, cls = '') => `<span class="status ${cls}" id="st">${text}</span>`;
const spin = text => status(`<span class="spin"></span>${esc(text)}`);
const btn = (label, act, pri = true, disabled = false) =>
  `<button class="gbtn${pri ? ' pri' : ''}" data-o="${act}"${disabled ? ' disabled' : ''}>${esc(label)}</button>`;
const link = (label, act) => `<button class="linkbtn" data-o="${act}">${esc(label)}</button>`;
const page = (top, title, lede, extra, act) =>
  `${top}<h1>${esc(title)}</h1><p class="lede">${lede}</p>${extra}<div class="act">${act}</div>`;

function welcome() {
  return page(icon(), `欢迎使用${S.name}`,
    '按一下 F5，说话，再按一下。整理好的文字会出现在光标所在的地方。接下来的几步只需要一分钟。',
    '', btn('开始设置', 'next'));
}

function microphone() {
  const lede = '只在你按下 F5 时录音。转写在这台 Mac 上完成，音频不会离开它。';
  let act;
  if (S.mic === 'authorized') act = status('已允许', 'ok') + btn('继续', 'next');
  else if (UI.asked === 'mic') act = spin('等待你的选择…') + btn('允许访问麦克风', 'mic', true, true);
  else if (S.mic === 'not_determined') act = btn('允许访问麦克风', 'mic');
  else act = status(`之前没有允许。在系统设置里打开${esc(S.name)}，这里会自己继续。`) + btn('打开系统设置', 'mic');
  return page(tile('mic', '#007AFF'), '允许使用麦克风', lede, '', act + link('稍后再说', 'next'));
}

function accessibility() {
  const lede = `还要用它把文字放进其他 App。在「系统设置 › 隐私与安全性 › 辅助功能」里打开${esc(S.name)}，这里会自己继续，不需要重启。`;
  let act;
  if (S.ax) act = status(UI.asked === 'a11y' ? '已授权，正在继续' : '已授权', 'ok') + btn('继续', 'next');
  else if (UI.asked === 'a11y') act = spin('正在等待授权…') + btn('再次打开系统设置', 'a11y', false);
  else act = btn('打开系统设置', 'a11y');
  return page(tile('a11y', '#0A84FF'), `允许${S.name}响应 F5`, lede, '', act + link('稍后再说', 'next'));
}

function apiKey() {
  const k = S.key;
  const lede = `润色需要一个 ${esc(k.service)} 的 API Key，保存在这台 Mac 的钥匙串里。没有也能用：会先插入原始转写。`;
  const field = `<div class="fieldline"><span class="svc">${esc(k.service)}</span>`
    + `<input class="secure" id="key" type="password" autocomplete="off" spellcheck="false" placeholder="${k.has ? '已保存，留空就用现在这个' : 'sk-…'}" aria-label="${esc(k.service)} API Key"${UI.keyBusy ? ' disabled' : ''}></div>`;
  let act;
  if (UI.keyBusy) act = spin('正在保存并发送一次测试请求…') + btn('验证并继续', 'verify', true, true);
  else if (UI.key && UI.key.ok) act = status(esc(UI.key.msg), 'ok') + btn('继续', 'next');
  else if (UI.key) act = status(esc(UI.key.msg), 'err') + btn('验证并继续', 'verify');
  else if (k.has) act = status('已保存在钥匙串', 'ok') + btn('继续', 'next');
  else act = btn('验证并继续', 'verify');
  return page(tile('key', '#AF52DE'), '连接润色模型', lede, field, act + (k.has || (UI.key && UI.key.ok) ? '' : link('暂不设置，先插入原始转写', 'next')));
}

function download() {
  const m = S.model;
  const dl = UI.dl || { p: m.p, eta: '', done: m.ready, error: false };
  const ready = m.ready || dl.done;
  const size = /large-v3-turbo/.test(m.name) ? '约 1.5 GB，' : '';
  const lede = `${esc(m.name || '语音识别模型')}，${size}只需要下载一次。可以先关掉窗口，下载会在后台继续。`;
  const pct = ready ? 100 : Math.round((dl.p || 0) * 100);
  const bar = `<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><i style="width:${pct}%"></i></div>`;
  let act;
  if (ready) act = status('已下载', 'ok') + btn('继续', 'next');
  else if (dl.error) act = status('下载失败，检查一下网络再试。', 'err') + btn('重试', 'download') + link('跳过', 'next');
  else if (!m.downloading && !UI.dl) act = status('还没有下载，可能是刚才没有网络。') + btn('开始下载', 'download') + link('跳过', 'next');
  else act = status(`已下载 ${pct}%${dl.eta ? ` · 还要${esc(dl.eta)}` : ''}`) + btn('继续', 'next', true, true) + link('在后台继续', 'next');
  return page(tile('down', '#34C759'), '下载语音识别模型', lede, bar, act);
}

function practice() {
  const lede = '点一下下面的框，按 F5 说一句话，说完再按一下 F5。';
  const box = `<textarea class="practice" id="pr" placeholder="文字会出现在这里" aria-label="试着听写一句"></textarea>`;
  let act;
  if (UI.practiced) act = status('成功了', 'ok') + btn('继续', 'next');
  else if (!S.ax) act = status('还没有辅助功能权限，F5 暂时不起作用。', 'err') + btn('去授权', 'goto-a11y') + link('跳过', 'next');
  else act = status(`按 F5，说“你好，${esc(S.name)}”`) + link('跳过', 'next');
  return page(tile('wave', '#FF9500'), '说一句试试', lede, box, act);
}

function done() {
  return page(icon(), '一切就绪',
    `${esc(S.name)}会待在菜单栏里。随时按 F5 开始；忘了快捷键，点菜单栏图标就能看到。`,
    '', btn('完成', 'done'));
}

const STEPS = [welcome, microphone, accessibility, apiKey, download, practice, done];

function draw() {
  if (!S) return;
  const root = $('#onb');
  // Keep what is being typed across a redraw.
  const typed = { key: $('#key')?.value || '', pr: $('#pr')?.value || '' };
  const focused = document.activeElement?.id;
  const dots = STEPS.slice(0, LAST).map((_, i) => `<i class="${i === step ? 'on' : i < step ? 'done' : ''}"></i>`).join('');
  root.innerHTML = `<div class="steps" aria-hidden="true">${dots}</div>${STEPS[step]()}`;
  const key = $('#key'), pr = $('#pr');
  if (key) key.value = typed.key;
  if (pr) pr.value = typed.pr;
  const again = focused && document.getElementById(focused);
  if (again && !again.disabled) again.focus();
  else if (key && !key.disabled) key.focus();
  else if (pr) pr.focus();
  else root.querySelector('.gbtn.pri:not(:disabled)')?.focus();
}

function go(to) {
  clearTimeout(advanceTimer);
  step = Math.max(0, Math.min(LAST, to));
  UI.asked = '';
  draw();
}

function advanceSoon(from) {
  clearTimeout(advanceTimer);
  advanceTimer = setTimeout(() => { if (step === from) go(from + 1); }, 900);
}

function verify() {
  const f = $('#key');
  const value = f ? f.value.trim() : '';
  if (!value) {
    if (S.key.has) { go(step + 1); return; }
    if (f) f.focus();
    return;
  }
  UI.keyBusy = true;
  UI.key = null;
  post({ t: 'key', env: S.key.env, value });
  draw();
}

document.addEventListener('click', e => {
  const o = e.target.closest('[data-o]')?.dataset.o;
  if (!o) return;
  if (o === 'next') go(step + 1);
  else if (o === 'goto-a11y') go(2);
  else if (o === 'mic') { UI.asked = 'mic'; post({ t: 'mic' }); draw(); }
  else if (o === 'a11y') { UI.asked = 'a11y'; post({ t: 'a11y' }); draw(); }
  else if (o === 'verify') verify();
  else if (o === 'download') { UI.dl = { p: 0, eta: '', done: false, error: false }; post({ t: 'download' }); draw(); }
  else if (o === 'done') post({ t: 'done' });
});

document.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.isComposing) return;
  if (e.target.id === 'pr') return;
  if (e.target.id === 'key') { e.preventDefault(); verify(); return; }
  if (e.target.tagName === 'BUTTON') return;
  const primary = $('#onb .gbtn.pri:not(:disabled)');
  if (primary) { e.preventDefault(); primary.click(); }
});

// The practice box is filled by the app's own paste, like any other text field.
document.addEventListener('input', e => {
  if (e.target.id === 'pr' && e.target.value.trim() && !UI.practiced) {
    UI.practiced = true;
    draw();
    advanceSoon(5);
  }
});

on('env', m => env(m));
on('state', m => {
  const before = S;
  S = m;
  // Waiting on a permission and it just came through: carry on by itself.
  if (before && step === 1 && UI.asked === 'mic' && m.mic !== 'not_determined') {
    UI.asked = '';
    if (m.mic === 'authorized') advanceSoon(1);
  }
  if (before && step === 2 && UI.asked === 'a11y' && m.ax && !before.ax) advanceSoon(2);
  draw();
});
on('keyResult', m => { UI.keyBusy = false; UI.key = { ok: m.ok, msg: m.msg }; draw(); });
on('download', m => {
  UI.dl = m;
  if (step === 4) {
    // Only the bar and the line under it change; a full redraw would restart the bar's transition.
    const bar = $('.bar i'), st = $('#st');
    if (bar && !m.done && !m.error) {
      const pct = Math.round(m.p * 100);
      bar.style.width = pct + '%';
      bar.parentElement.setAttribute('aria-valuenow', pct);
      if (st) st.textContent = `已下载 ${pct}%${m.eta ? ` · 还要${m.eta}` : ''}`;
      return;
    }
    draw();
  }
});

post({ t: 'ready' });
})();
