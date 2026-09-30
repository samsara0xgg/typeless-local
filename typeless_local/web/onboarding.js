/* The first-run guide: welcome, microphone, Accessibility, API key, speech
   model, one practice dictation, done. Python sends what is already granted
   ({t:'state'}) and redraws it whenever a permission changes, so a step that
   is already done shows as done and one being waited on continues by itself. */
(() => {
'use strict';
const { I, esc, $, post, on, env, L, lang } = kit;

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
const link = (label, act, v) => `<button class="linkbtn" data-o="${act}"${v ? ` data-v="${esc(v)}"` : ''}>${esc(label)}</button>`;
const page = (top, title, lede, extra, act) =>
  `${top}<h1>${esc(title)}</h1><p class="lede">${lede}</p>${extra}<div class="act">${act}</div>`;

// The one place the guide offers both languages at once, so either reader can switch.
const langSwitch = () => `<div class="langsw" role="radiogroup" aria-label="Language 语言">`
  + [['zh', '中文'], ['en', 'English']].map(([v, t]) =>
    `<button class="linkbtn" role="radio" aria-checked="${lang() === v}" data-o="lang" data-v="${v}">${t}</button>`).join('<span aria-hidden="true">·</span>')
  + '</div>';
const later = () => link(L('稍后再说', 'Not Now'), 'next');
const skip = () => link(L('跳过', 'Skip'), 'next');
const next = () => btn(L('继续', 'Continue'), 'next');

function welcome() {
  return page(icon(), L(`欢迎使用${S.name}`, `Welcome to ${S.name}`),
    L('按一下 F5，说话，再按一下。整理好的文字会出现在光标所在的地方。接下来的几步只需要一分钟。',
      'Press F5, speak, press it again. Clean text appears where your cursor is. Setting up takes about a minute.'),
    langSwitch(), btn(L('开始设置', 'Get Started'), 'next'));
}

function microphone() {
  const lede = L('只在你按下 F5 时录音。转写在这台 Mac 上完成，音频不会离开它。',
    'It only records while you press F5. Transcription happens on this Mac, and the audio never leaves it.');
  const allow = L('允许访问麦克风', 'Allow Microphone');
  let act;
  if (S.mic === 'authorized') act = status(L('已允许', 'Allowed'), 'ok') + next();
  else if (UI.asked === 'mic') act = spin(L('等待你的选择…', 'Waiting for your choice…')) + btn(allow, 'mic', true, true);
  else if (S.mic === 'not_determined') act = btn(allow, 'mic');
  else act = status(L(`之前没有允许。在系统设置里打开${esc(S.name)}，这里会自己继续。`, `It was not allowed earlier. Turn on ${esc(S.name)} in System Settings and this continues by itself.`))
    + btn(L('打开系统设置', 'Open System Settings'), 'mic');
  return page(tile('mic', '#007AFF'), L('允许使用麦克风', 'Allow the microphone'), lede, '', act + later());
}

function accessibility() {
  const lede = L(`还要用它把文字放进其他 App。在「系统设置 › 隐私与安全性 › 辅助功能」里打开${esc(S.name)}，这里会自己继续，不需要重启。`,
    `This lets it put the text into other apps. Turn on ${esc(S.name)} in System Settings › Privacy & Security › Accessibility; this continues by itself, no restart needed.`);
  let act;
  if (S.ax) act = status(UI.asked === 'a11y' ? L('已授权，正在继续', 'Granted, continuing') : L('已授权', 'Granted'), 'ok') + next();
  else if (UI.asked === 'a11y') act = spin(L('正在等待授权…', 'Waiting for permission…')) + btn(L('再次打开系统设置', 'Open System Settings Again'), 'a11y', false);
  else act = btn(L('打开系统设置', 'Open System Settings'), 'a11y');
  return page(tile('a11y', '#0A84FF'), L(`允许${S.name}响应 F5`, `Let ${S.name} respond to F5`), lede, '', act + later());
}

function apiKey() {
  const k = S.key;
  const lede = L(`润色需要一个 ${esc(k.service)} 的 API Key，保存在这台 Mac 的钥匙串里。没有也能用：会先插入原始转写。`,
    `Refinement needs a ${esc(k.service)} API key, kept in this Mac's keychain. It works without one too: you get the raw transcript.`);
  const field = `<div class="fieldline"><span class="svc">${esc(k.service)}</span>`
    + `<input class="secure" id="key" type="password" autocomplete="off" spellcheck="false" placeholder="${k.has ? L('已保存，留空就用现在这个', 'Saved; leave empty to keep it') : 'sk-…'}" aria-label="${esc(k.service)} API Key"${UI.keyBusy ? ' disabled' : ''}></div>`;
  const verify = L('验证并继续', 'Verify and Continue');
  let act;
  if (UI.keyBusy) act = spin(L('正在保存并发送一次测试请求…', 'Saving and sending a test request…')) + btn(verify, 'verify', true, true);
  else if (UI.key && UI.key.ok) act = status(esc(UI.key.msg), 'ok') + next();
  else if (UI.key) act = status(esc(UI.key.msg), 'err') + btn(verify, 'verify');
  else if (k.has) act = status(L('已保存在钥匙串', 'Saved in the keychain'), 'ok') + next();
  else act = btn(verify, 'verify');
  return page(tile('key', '#AF52DE'), L('连接润色模型', 'Connect the refinement model'), lede, field,
    act + (k.has || (UI.key && UI.key.ok) ? '' : link(L('暂不设置，先插入原始转写', 'Skip for now and insert raw transcripts'), 'next')));
}

function download() {
  const m = S.model;
  const dl = UI.dl || { p: m.p, eta: '', done: m.ready, error: false };
  const ready = m.ready || dl.done;
  const big = /large-v3-turbo/.test(m.name);
  const name = esc(m.name || L('语音识别模型', 'The speech model'));
  const lede = L(`${name}，${big ? '约 1.5 GB，' : ''}只需要下载一次。可以先关掉窗口，下载会在后台继续。`,
    `${name}${big ? ' is about 1.5 GB and' : ''} only downloads once. You can close this window; the download carries on in the background.`);
  const pct = ready ? 100 : Math.round((dl.p || 0) * 100);
  const bar = `<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><i style="width:${pct}%"></i></div>`;
  let act;
  if (ready) act = status(L('已下载', 'Downloaded'), 'ok') + next();
  else if (dl.error) act = status(L('下载失败，检查一下网络再试。', 'The download failed. Check the network and try again.'), 'err') + btn(L('重试', 'Try Again'), 'download') + switchSource(m) + skip();
  else if (!m.downloading && !UI.dl) act = status(L('还没有下载，可能是刚才没有网络。', 'Not downloaded yet; the network may have been down.')) + btn(L('开始下载', 'Download'), 'download') + switchSource(m) + skip();
  else act = status(progressText(pct, dl.eta)) + btn(L('继续', 'Continue'), 'next', true, true) + link(L('在后台继续', 'Continue in Background'), 'next');
  return page(tile('down', '#34C759'), L('下载语音识别模型', 'Download the speech model'), lede, bar, act);
}
// Hugging Face does not answer from mainland China; offer the other source when a download failed.
const switchSource = m => m.mirror
  ? link(L('改从 Hugging Face 下载', 'Download from Hugging Face instead'), 'source', 'huggingface')
  : link(L('改从国内镜像下载', 'Download from the China mirror instead'), 'source', 'mirror');
const progressText = (pct, eta) => L(`已下载 ${pct}%${eta ? ` · 还要${eta}` : ''}`, `${pct}% downloaded${eta ? ` · ${eta} left` : ''}`);

function practice() {
  const lede = L('点一下下面的框，按 F5 说一句话，说完再按一下 F5。', 'Click the box below, press F5, say a sentence, then press F5 again.');
  const box = `<textarea class="practice" id="pr" placeholder="${L('文字会出现在这里', 'The text appears here')}" aria-label="${L('试着听写一句', 'Try a dictation')}"></textarea>`;
  let act;
  if (UI.practiced) act = status(L('成功了', 'It worked'), 'ok') + next();
  else if (!S.ax) act = status(L('还没有辅助功能权限，F5 暂时不起作用。', 'No Accessibility permission yet, so F5 does nothing.'), 'err') + btn(L('去授权', 'Grant Permission'), 'goto-a11y') + skip();
  else act = status(L(`按 F5，说“你好，${esc(S.name)}”`, `Press F5 and say “Hello, ${esc(S.name)}”`)) + skip();
  return page(tile('wave', '#FF9500'), L('说一句试试', 'Try it'), lede, box, act);
}

function done() {
  return page(icon(), L('一切就绪', 'All set'),
    L(`${esc(S.name)}会待在菜单栏里。随时按 F5 开始；忘了快捷键，点菜单栏图标就能看到。`,
      `${esc(S.name)} lives in the menu bar. Press F5 any time; if you forget the shortcut, click the menu bar icon.`),
    '', btn(L('完成', 'Done'), 'done'));
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
  else if (o === 'lang') post({ t: 'lang', v: e.target.closest('[data-o]').dataset.v });
  else if (o === 'source') { UI.dl = { p: 0, eta: '', done: false, error: false }; post({ t: 'source', v: e.target.closest('[data-o]').dataset.v }); draw(); }
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

on('env', m => {
  env(m);
  document.title = L('欢迎', 'Welcome');
  draw();
});
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
      if (st) st.textContent = progressText(pct, m.eta);
      return;
    }
    draw();
  }
});

post({ t: 'ready' });
})();
