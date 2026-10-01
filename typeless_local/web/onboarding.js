/* The first-run guide: welcome, microphone, Accessibility, API key, one
   practice dictation, done. Python sends what is already granted
   ({t:'state'}) and redraws it whenever a permission changes, so a step that
   is already done shows as done and one being waited on continues by itself. */
(() => {
'use strict';
const { I, esc, $, post, on, env, L, lang } = kit;

const LAST = 5;
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
    L('轻点一下右边的 ⌘，说话，再轻点一下。整理好的文字会出现在光标所在的地方。接下来的几步只需要一分钟。',
      'Tap the right ⌘ key, speak, tap it again. Clean text appears where your cursor is. Setting up takes about a minute.'),
    langSwitch(), btn(L('开始设置', 'Get Started'), 'next'));
}

function microphone() {
  const lede = L('只在你按下右 ⌘ 之后录音。转写在这台 Mac 上完成，音频不会离开它。',
    'It only records after you tap right ⌘. Transcription happens on this Mac, and the audio never leaves it.');
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
  return page(tile('a11y', '#0A84FF'), L(`允许${S.name}响应右 ⌘`, `Let ${S.name} respond to right ⌘`), lede, '', act + later());
}

function apiKey() {
  const k = S.key;
  if (k.trial) return trialKey();
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

// On the free trial refinement already works: starting the trial is the big,
// obvious choice; their own key is tucked behind a link for later.
function trialKey() {
  const lede = L('前大约 400 次润色免费，不用填任何东西，现在就能用。之后需要你自己的 OpenAI API Key，到时候会提醒你。',
    'Your first 400 or so refinements are free, with nothing to fill in. After that you will need your own OpenAI API key; you will be reminded when the time comes.');
  const start = `<button class="gbtn pri big" data-o="next">${esc(L('开始免费试用', 'Start the Free Trial'))}</button>`;
  if (!UI.ownKey && !UI.keyBusy && !UI.key) {
    const card = `<div class="trialcard"><b>~400</b><span>${esc(L('次免费润色，送给你', 'free refinements, on us'))}</span></div>`;
    return page(tile('key', '#34C759'), L('免费试用已开启', 'Your free trial is on'), lede, card,
      start + link(L('我已经有 OpenAI API Key', 'I already have an OpenAI API key'), 'own-key'));
  }
  const field = `<div class="fieldline"><span class="svc">OpenAI</span>`
    + `<input class="secure" id="key" type="password" autocomplete="off" spellcheck="false" placeholder="sk-…" aria-label="OpenAI API Key"${UI.keyBusy ? ' disabled' : ''}></div>`;
  let act;
  if (UI.keyBusy) act = spin(L('正在保存并发送一次测试请求…', 'Saving and sending a test request…'));
  else if (UI.key && UI.key.ok) act = status(esc(UI.key.msg), 'ok') + next();
  else if (UI.key) act = status(esc(UI.key.msg), 'err') + btn(L('再试一次', 'Try Again'), 'verify') + link(L('先用免费试用', 'Use the Free Trial for Now'), 'next');
  else act = btn(L('保存我的 Key', 'Save My Key'), 'verify') + link(L('去 OpenAI 申请 Key', 'Get a Key from OpenAI'), 'open-keys')
    + link(L('先用免费试用', 'Use the Free Trial for Now'), 'next');
  return page(tile('key', '#AF52DE'), L('用你自己的 OpenAI Key', 'Use your own OpenAI key'),
    L('保存在这台 Mac 的钥匙串里。保存后就不再走免费试用。', "It's kept in this Mac's keychain. Once it's saved, the free trial is no longer used."), field, act);
}

// One slim line under every page while the speech model downloads; failures are fixed from here too.
const modelReady = () => S.model.ready || !!(UI.dl && UI.dl.done);

function dlLine() {
  const m = S.model;
  const dl = UI.dl || { p: m.p, eta: '', done: m.ready, error: false };
  if (m.ready && !UI.dl) return '';
  let body;
  if (dl.done || m.ready) body = `<span class="dlok">${I('check')}${L('语音模型已就绪', 'Speech model ready')}</span>`;
  else if (dl.error || (!m.downloading && !UI.dl)) body = `<span class="st-err">${L('语音模型下载失败', 'Speech model download failed')}</span>`
    + link(L('重试', 'Try Again'), 'download') + switchSource(m);
  else {
    const pct = Math.round((dl.p || 0) * 100);
    body = `<span class="mbar" aria-hidden="true"><i id="dlb" style="width:${pct}%"></i></span><span id="dlt">${progressText(pct, dl.eta)}</span>`;
  }
  return `<div class="dlline">${body}</div>`;
}
// Hugging Face does not answer from mainland China; offer the other source when a download failed.
const switchSource = m => m.mirror
  ? link(L('改从 Hugging Face 下载', 'Download from Hugging Face instead'), 'source', 'huggingface')
  : link(L('改从国内镜像下载', 'Download from the China mirror instead'), 'source', 'mirror');
const progressText = (pct, eta) => L(`语音模型下载中 ${pct}%${eta ? ` · 还要${eta}` : ''}`, `Downloading the speech model · ${pct}%${eta ? ` · ${eta} left` : ''}`);

function practice() {
  const lede = L('点一下下面的框，轻点右 ⌘ 说一句话，说完再轻点一下。', 'Click the box below, tap right ⌘, say a sentence, then tap it again.');
  const box = `<textarea class="practice" id="pr" placeholder="${L('文字会出现在这里', 'The text appears here')}" aria-label="${L('试着听写一句', 'Try a dictation')}"></textarea>`;
  let act;
  if (UI.practiced) act = status(L('成功了', 'It worked'), 'ok') + next();
  else if (!S.ax) act = status(L('还没有辅助功能权限，右 ⌘ 暂时不起作用。', 'No Accessibility permission yet, so right ⌘ does nothing.'), 'err') + btn(L('去授权', 'Grant Permission'), 'goto-a11y') + skip();
  else if (UI.dl && UI.dl.error) act = status(L('语音模型下载好才能试，先在下面重试。', 'You can try once the speech model downloads; try again below.'), 'err')
    + link(L('先完成设置，稍后再试', 'Finish Setup and Try Later'), 'next');
  else if (!modelReady()) act = spin(L('语音模型下载好就能试，大概还要一会儿', 'You can try once the speech model finishes downloading'))
    + link(L('先完成设置，稍后再试', 'Finish Setup and Try Later'), 'next');
  else act = status(L(`轻点右 ⌘，说“你好，${esc(S.name)}”`, `Tap right ⌘ and say “Hello, ${esc(S.name)}”`)) + skip();
  return page(tile('wave', '#FF9500'), L('说一句试试', 'Try it'), lede, box, act);
}

const TIPS = () => [
  ['mic', L('轻点右 ⌘ 开始、再点一下结束；也可以按住右 ⌘ 说话，松开就完成', 'Tap right ⌘ to start and again to finish, or hold it while you talk')],
  ['lock', L('连点两下右 ⌘ 免手持，适合说长段', 'Double-tap right ⌘ to go hands-free for long passages')],
  ['xmark', L('说错了按 esc 取消', 'Said it wrong? Press esc to cancel')],
  ['undo', L('插入后，胶囊上可以撤销或修改', 'After inserting, the capsule offers Undo and Edit')],
  ['pencil', L('选中文字再点右 ⌘，说“翻成英文”这类要求就能改写', 'Select text, tap right ⌘ and say something like “make it formal” to rewrite it')],
];

function done() {
  const tips = `<ul class="tips" aria-label="${L('小技巧', 'Tips')}">${TIPS().map(([i, t]) => `<li>${I(i)}<span>${esc(t)}</span></li>`).join('')}</ul>`;
  return page(icon(), L('一切就绪', 'All set'),
    L(`${esc(S.name)}会待在菜单栏里，忘了快捷键点菜单栏图标就能看到。`,
      `${esc(S.name)} lives in the menu bar; click its icon if you forget a shortcut.`),
    tips + `<p class="note">${L('言字每天会发送一次匿名使用统计：听写了几次、共多少字，只用来了解产品怎么被使用。从不发送听写内容或任何个人信息；可以在 设置 › 历史与隐私 里关掉。',
      'Once a day the app sends anonymous usage stats (how many dictations and characters) only to learn how it is used. Never your dictated text or anything personal; turn it off in Settings › History & Privacy.')}</p>`,
    btn(L('完成', 'Done'), 'done'));
}

// The speech model downloads from launch, behind every step (dlLine), rather than as a step of its own.
const STEPS = [welcome, microphone, accessibility, apiKey, practice, done];

function draw() {
  if (!S) return;
  const root = $('#onb');
  // Keep what is being typed across a redraw.
  const typed = { key: $('#key')?.value || '', pr: $('#pr')?.value || '' };
  const focused = document.activeElement?.id;
  const dots = STEPS.slice(0, LAST).map((_, i) => `<i class="${i === step ? 'on' : i < step ? 'done' : ''}"></i>`).join('');
  root.innerHTML = `<div class="steps" aria-hidden="true">${dots}</div>${STEPS[step]()}${STEPS[step] === done ? '' : dlLine()}`;
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
  else if (o === 'open-keys') post({ t: 'open', what: 'openai-keys' });
  else if (o === 'own-key') { UI.ownKey = true; draw(); }
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
    advanceSoon(4);
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
  // A permission came through: the step stays put, they press Continue themselves.
  if (before && step === 1 && UI.asked === 'mic' && m.mic !== 'not_determined') UI.asked = '';
  if (before && step === 2 && UI.asked === 'a11y' && m.ax) UI.asked = '';
  draw();
});
on('keyResult', m => { UI.keyBusy = false; UI.key = { ok: m.ok, msg: m.msg }; draw(); });
on('download', m => {
  UI.dl = m;
  // Progress only changes the line's text; a finished or failed download redraws the page.
  const line = $('#dlt');
  if (line && !m.done && !m.error) {
    const pct = Math.round(m.p * 100);
    line.textContent = progressText(pct, m.eta);
    const fill = $('#dlb');
    if (fill) fill.style.width = pct + '%';
    return;
  }
  draw();
});

post({ t: 'ready' });
})();
