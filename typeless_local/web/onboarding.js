/* The first-run guide: welcome, microphone, Accessibility, API key, one
   practice dictation, done. Python sends what is already granted
   ({t:'state'}) and redraws it whenever a permission changes, so a step that
   is already done shows as done and one being waited on continues by itself. */
(() => {
'use strict';
const { I, esc, $, $$, post, on, env, L, lang, reduceMotion } = kit;

const LAST = 5;
let S = null;             // what Python last sent
let step = 0;
// Per-step progress that only this page knows about.
const UI = { asked: '', key: null, keyBusy: false, dl: null, practiced: false, meter: false, counted: false, pressed: false, heard: false, result: null, revealed: false, loops: 0 };
// A second click or Enter landing just after a step change belongs to the step that was left.
let lastGo = 0;
const tooSoon = () => performance.now() - lastGo < 350;
// Each draw starts the page's little animations afresh; timers from an earlier draw see a stale generation and stop.
let gen = 0;
const after = (ms, fn) => { const g = gen; setTimeout(() => { if (g === gen) fn(); }, ms); };

const tile = (n, c) => `<div class="sym" style="background:${c}">${I(n)}</div>`;
const icon = () => '<div class="sym ico"><img src="appicon.svg" alt=""></div>';
const status = (text, cls = '') => `<span class="status ${cls}" id="st" role="status" aria-live="polite">${text}</span>`;
const spin = text => status(`<span class="spin"></span>${esc(text)}`);
const btn = (label, act, pri = true, disabled = false) =>
  `<button class="gbtn${pri ? ' pri' : ''}" data-o="${act}"${disabled ? ' disabled' : ''}>${esc(label)}</button>`;
const link = (label, act, v) => `<button class="linkbtn" data-o="${act}"${v ? ` data-v="${esc(v)}"` : ''}>${esc(label)}</button>`;
const page = (top, title, lede, extra, act) =>
  `${top}<h1 tabindex="-1">${esc(title)}</h1><p class="lede">${lede}</p>${extra}<div class="act">${act}</div>`;

// The one place the guide offers both languages at once, so either reader can switch.
const langSwitch = () => `<div class="langsw" role="radiogroup" aria-label="Language 语言">`
  + [['zh', '中文'], ['en', 'English']].map(([v, t]) =>
    `<button class="linkbtn" role="radio" aria-checked="${lang() === v}" data-o="lang" data-v="${v}">${t}</button>`).join('<span aria-hidden="true">·</span>')
  + '</div>';
const later = () => link(L('稍后再说', 'Not Now'), 'next');
const skip = () => link(L('跳过', 'Skip'), 'next');
const next = () => btn(L('继续', 'Continue'), 'next');

// The guide's one visual idea comes from the icon: 言 is a dot and strokes
// over a little capsule. Voice moves the strokes; the strokes become words,
// set one character at a time like movable type, and the filler falls out.
const yan = (cls = '') => `<div class="yan ${cls}" aria-hidden="true"><i class="dot"></i><i class="s s1"></i><i class="s s2"></i><i class="s s3"></i>`
  + '<span class="pill"><b></b><b></b><b></b><b></b></span></div>';
// A line as single characters; kind 1 is filler (falls out), 2 is added by the refinement.
const typeLine = (parts, cls = '') => `<p class="type ${cls}" aria-hidden="true">${parts.map(([t, k]) =>
  [...t].map(ch => `<span class="${k === 1 ? 'f' : k === 2 ? 'a' : ''}">${ch === ' ' ? '&nbsp;' : esc(ch)}</span>`).join('')).join('')}</p>`;
const DEMO = () => L(
  [['嗯，', 1], ['那个，', 1], ['明天下午'], ['三点……不对，', 1], ['四点开会'], ['。', 2]],
  [['Meeting at '], ['um, ', 1], ['three, no, ', 1], ['four'], [' tomorrow'], ['.', 2]]);
const RCMD = () => L('右 ⌘', 'right ⌘');

function welcome() {
  return page(`<div class="stage">${yan('big')}${typeLine(DEMO(), 'demo')}</div>`, L(`欢迎使用${S.name}`, `Welcome to ${S.name}`),
    L(`轻点一下右边的 ⌘，说话，再点一下。${esc(S.name)}去掉口头禅、理顺句子，放到光标所在的地方。`,
      `Tap the right ⌘ key, speak, tap it again. ${esc(S.name)} drops the filler, tidies the sentence and puts it where your cursor is.`),
    langSwitch(), btn(L('开始设置', 'Get Started'), 'next'));
}

// Characters are set one by one (each with its own delay), then the filler drops and the rest close up.
function setType(line, then) {
  const chars = $$('span', line);
  chars.forEach((c, i) => c.style.transitionDelay = `${i * 45}ms`);
  line.classList.add('set');
  after(chars.length * 45 + 350, () => {
    chars.forEach(c => c.style.transitionDelay = '');
    line.classList.add('drop');
    after(380, () => { line.classList.add('close'); if (then) after(500, then); });
  });
}

// Played twice, then it rests on the finished line; pointing at 言 plays it again.
function playWelcome() {
  const stage = $('.stage'), line = $('.type.demo');
  if (!stage || !line) return;
  if (reduceMotion()) { line.className = 'type demo set drop close'; return; }
  UI.loops++;
  stage.classList.add('busy');
  line.className = 'type demo';
  stage.classList.add('talk');
  after(900, () => {
    stage.classList.remove('talk');
    setType(line, () => (UI.loops < 2 ? after(1500, playWelcome) : stage.classList.remove('busy')));
  });
}
document.addEventListener('mouseover', e => {
  const stage = e.target.closest?.('.stage');
  if (stage && e.target.closest('.yan') && !stage.classList.contains('busy') && STEPS[step] === welcome) { gen++; UI.loops = 1; playWelcome(); }
});

function microphone() {
  const lede = L('平时只在你按下右 ⌘ 之后录音；这一页会先听一下，确认麦克风能用。转写在这台 Mac 上完成，音频不会离开它。',
    'Normally it only records after you tap right ⌘; this page listens for a moment to check the microphone works. Transcription happens on this Mac, and the audio never leaves it.');
  const allow = L('允许访问麦克风', 'Allow Microphone');
  let act;
  if (S.mic === 'authorized') act = status(L('已允许', 'Allowed'), 'ok') + next();
  else if (UI.asked === 'mic') act = spin(L('等待你的选择…', 'Waiting for your choice…')) + btn(allow, 'mic', true, true);
  else if (S.mic === 'not_determined') act = btn(allow, 'mic');
  else act = status(L(`之前没有允许。在系统设置里打开${esc(S.name)}，这里会自己继续。`, `It was not allowed earlier. Turn on ${esc(S.name)} in System Settings and this continues by itself.`))
    + btn(L('打开系统设置', 'Open System Settings'), 'mic');
  // Once allowed, the real input moves the bars, so they can see it hears them.
  const meter = S.mic !== 'authorized' ? yan('big') : yan('big live');
  const hint = S.mic !== 'authorized' ? ''
    : `<p class="mhint">${L('对着它说句话，笔画跟着动就说明听得到', 'Say something to it: if the strokes move, it can hear you')}${S.input ? ` · ${esc(S.input)}` : ''}</p>`;
  return page(meter, L('允许使用麦克风', 'Allow the microphone'), lede, hint, act + later());
}

function accessibility() {
  const lede = L(`${esc(S.name)}要靠这个权限听到右 ⌘，并把文字放进其他 App。在「系统设置 › 隐私与安全性 › 辅助功能」里打开${esc(S.name)}，这里会自己继续，不用重启。`,
    `This lets it put the text into other apps. Turn on ${esc(S.name)} in System Settings › Privacy & Security › Accessibility; this continues by itself, no restart needed.`);
  let act;
  if (S.ax) act = status(UI.asked === 'a11y' ? L('已授权，正在继续', 'Granted, continuing') : L('已授权', 'Granted'), 'ok') + next();
  else if (UI.asked === 'a11y') act = spin(L('正在等待授权…', 'Waiting for permission…')) + btn(L('再次打开系统设置', 'Open System Settings Again'), 'a11y', false);
  else act = btn(L('打开系统设置', 'Open System Settings'), 'a11y');
  // A small System Settings window where the switch gets turned on, so they know what to look for.
  const mock = `<div class="axmock${S.ax ? ' granted' : ''}" aria-hidden="true">
    <div class="axbar"><i></i><i></i><i></i><span>${L('辅助功能', 'Accessibility')}</span></div>
    <div class="axrow dim"><span class="axic"></span><span>Terminal</span><span class="axsw"></span></div>
    <div class="axrow"><img src="appicon.svg" alt=""><span>${esc(S.name)}</span><span class="axsw on"></span></div>
    <i class="axcur"></i></div>`;
  return page(mock, L(`允许${S.name}响应右 ⌘`, `Let ${S.name} respond to right ⌘`), lede, '', act + later());
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
  const lede = L('前大约 300 次润色免费，不用填任何东西，现在就能用。之后需要你自己的 OpenAI API Key，到时候会提醒你。',
    'Your first 300 or so refinements are free, with nothing to fill in. After that you will need your own OpenAI API key; you will be reminded when the time comes.');
  const privacy = `<p class="fine">${esc(L('润色时，听写的文字会经言字的服务器转给 OpenAI，不会保存。',
    'While refining, your dictated text passes through our server to OpenAI and is not stored.'))}</p>`;
  const start = `<button class="gbtn pri big" data-o="next">${esc(L('开始免费试用', 'Start the Free Trial'))}</button>`;
  if (!UI.ownKey && !UI.keyBusy && !UI.key) {
    const card = `<div class="trialcard${UI.counted ? '' : ' glow'}"><b id="tc">~${UI.counted ? 300 : 0}</b><span>${esc(L('次免费润色，送给你', 'free refinements, on us'))}</span></div>`;
    return page(tile('key', '#34C759'), L('润色可以免费试用', 'Refinement is free to try'), lede, card + privacy,
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

// The bottom row of a Mac keyboard with right ⌘ marked; it lights up when they press it for real.
function keyRow() {
  const cls = UI.pressed ? ' down' : '';
  return `<div class="krow" aria-hidden="true"><span>fn</span><span>⌃</span><span>⌥</span><span class="w">⌘</span><span class="sp"></span>`
    + `<span class="w rc${cls}">⌘<small>${esc(RCMD())}</small></span><span>⌥</span></div>`;
}

// Raw against refined: what was dropped falls out, what was added is set in.
// By character for Chinese, by word for Latin text ("meeting" vs "Meeting").
const units = s => (/[A-Za-z]/.test(s) ? s.match(/\s*\S+\s*/g) || [] : [...s]).slice(0, 200);  // a word keeps its trailing space
function diffParts(raw, text) {
  const a = units(raw), b = units(text), words = /[A-Za-z]/.test(raw);
  const n = a.length, m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { out.push([a[i]]); i++; j++; }
    // What was struck comes before what replaced it, as an editor marks a page.
    else if (i < n && (j >= m || dp[i + 1][j] >= dp[i][j + 1])) { const w = a[i++]; out.push([words && !/\s$/.test(w) ? w + ' ' : w, 1]); }
    else out.push([b[j++], 2]);
  }
  return out;
}

function practice() {
  const lede = L('点一下下面的框，轻点右 ⌘，说完再点一下。试着说：', 'Click the box below, tap right ⌘, speak, then tap it again. Try saying:');
  const say = `<p class="say">${L('“嗯，那个，明天下午三点开会，记得带电脑”', '“Um, so, meeting tomorrow at three, uh, bring your laptop”')}</p>`;
  const box = `<textarea class="practice" id="pr" placeholder="${L('文字会出现在这里', 'The text appears here')}" aria-label="${L('试着听写一句', 'Try a dictation')}"></textarea>`;
  const r = UI.result;
  const reveal = UI.practiced && r && r.raw && r.raw !== r.text
    ? `<div class="reveal"><small>${L('你说的 → 插入的', 'What you said → what went in')}</small>${typeLine(diffParts(r.raw, r.text), UI.revealed ? 'set drop close' : 'set')}</div>` : '';
  let act;
  if (UI.practiced) act = `<span class="status ok pop" id="st" role="status" aria-live="polite"><span class="stamp" aria-hidden="true">言</span>${L('成功了', 'It worked')}</span>` + next();
  else if (S.mic !== 'authorized') act = status(L('还没有麦克风权限，听不到你说话。', 'No microphone permission yet, so it can’t hear you.'), 'err') + btn(L('去授权', 'Grant Permission'), 'goto-mic') + skip();
  else if (!S.ax) act = status(L('还没有辅助功能权限，右 ⌘ 暂时不起作用。', 'No Accessibility permission yet, so right ⌘ does nothing.'), 'err') + btn(L('去授权', 'Grant Permission'), 'goto-a11y') + skip();
  else if (UI.dl && UI.dl.error) act = status(L('语音模型下载好才能试，先在下面重试。', 'You can try once the speech model downloads; try again below.'), 'err')
    + link(L('先完成设置，稍后再试', 'Finish Setup and Try Later'), 'next');
  else if (!modelReady()) act = spin(L('语音模型下载好就能试，大概还要一会儿', 'You can try once the speech model finishes downloading'))
    + link(L('先完成设置，稍后再试', 'Finish Setup and Try Later'), 'next');
  else if (UI.heard) act = spin(L('正在转写…', 'Transcribing…')) + skip();
  else if (UI.pressed) act = status(L('就是这个键。正在听，说完再点一下右 ⌘', 'That’s the one. Listening; tap right ⌘ again when done')) + skip();
  else act = status(L('轻点空格键右边的 ⌘', 'Tap the ⌘ just right of the space bar')) + skip();
  return page(keyRow(), L('说一句试试', 'Try it'), lede, say + box + reveal, act);
}

// Each tip acts out its gesture on a tiny keycap, instead of an icon.
const TIPS = () => [
  ['tap', '⌘', L('轻点右 ⌘ 开始，再点一下结束', 'Tap right ⌘ to start, tap again to finish')],
  ['hold', '⌘', L('按住右 ⌘ 说话，松开就完成', 'Hold right ⌘ while you talk; let go to finish')],
  ['dbl', '⌘', L('连点两下右 ⌘ 免手持，适合说长段', 'Double-tap right ⌘ to go hands-free for long passages')],
  ['tap', 'esc', L('说错了按 esc 取消', 'Said it wrong? Press esc to cancel')],
  ['sel', '⌘', L('选中文字再点右 ⌘，说“翻成英文”这类要求就能改写', 'Select text, tap right ⌘ and say something like “make it formal” to rewrite it')],
];

function done() {
  // The keycaps act out their gestures one after another, once round.
  const tips = `<ul class="tips" aria-label="${L('小技巧', 'Tips')}">${TIPS().map(([g, k, t], i) =>
    `<li><span class="gest ${g}" style="--d:${i * 0.9}s" aria-hidden="true"><b>${esc(k)}</b></span><span>${esc(t)}</span></li>`).join('')}</ul>`;
  const note = `<p class="note">${L('每天发送一次匿名统计：听写次数、字数和免费试用花费，带一个随机编号。从不包含听写内容。可以在「设置 › 历史与隐私」里关掉。',
    'Once a day it sends anonymous counts: dictations, characters and free-trial spend, with a random ID. They never include what you dictated. Turn them off in Settings › History & Privacy.')}</p>`;
  // Skipped a permission on the way: say so here rather than leave right ⌘ silently doing nothing.
  const missing = S.mic !== 'authorized' ? 'goto-mic' : !S.ax ? 'goto-a11y' : '';
  if (missing) {
    return page(icon(), L('还差一步', 'One step left'),
      missing === 'goto-mic' ? L('还没有麦克风权限，现在按右 ⌘ 听不到你说话。', 'There is no microphone permission yet, so right ⌘ can’t hear you.')
        : L('还没有辅助功能权限，现在按右 ⌘ 不会有反应。', 'There is no Accessibility permission yet, so right ⌘ does nothing.'),
      tips + note, btn(L('去授权', 'Grant Permission'), missing) + link(L('先这样，稍后再说', 'Finish Anyway'), 'done'));
  }
  return page(icon(), L('一切就绪', 'All set'),
    L(`${esc(S.name)}会待在菜单栏里，忘了快捷键点菜单栏图标就能看到。`,
      `${esc(S.name)} lives in the menu bar; click its icon if you forget a shortcut.`),
    tips + note, btn(L('完成', 'Done'), 'done'));
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
  const where = step < LAST ? `<span class="sr">${L(`第 ${step + 1} 步，共 ${LAST} 步`, `Step ${step + 1} of ${LAST}`)}</span>` : '';
  root.innerHTML = `<div class="steps" aria-hidden="true">${dots}</div>${where}${STEPS[step]()}${STEPS[step] === done ? '' : dlLine()}`;
  const key = $('#key'), pr = $('#pr');
  if (key) key.value = typed.key;
  if (pr) pr.value = typed.pr;
  const again = focused && document.getElementById(focused);
  if (again && !again.disabled) again.focus();
  else if (key && !key.disabled) key.focus();
  else if (pr) pr.focus();
  else root.querySelector('.gbtn.pri:not(:disabled)')?.focus();
  gen++;
  if (STEPS[step] === welcome) playWelcome();
  if (STEPS[step] === apiKey && S.key.trial) countUp();
  const rv = $('.reveal .type');
  if (rv && !UI.revealed) {
    UI.revealed = true;
    if (reduceMotion()) rv.className = 'type set drop close';
    else after(700, () => { rv.classList.add('drop'); after(380, () => rv.classList.add('close')); });
  }
  // The level bars need the microphone open, only while that page is up.
  // Asked again on every draw while wanted: after the window is closed and
  // reopened the stream is gone, and Python ignores a repeat.
  const wantMeter = STEPS[step] === microphone && S.mic === 'authorized';
  if (wantMeter || UI.meter) { UI.meter = wantMeter; post({ t: 'meter', on: wantMeter }); }
}

function countUp() {
  const el = $('#tc');
  if (!el || UI.counted) return;
  UI.counted = true;
  if (reduceMotion()) { el.textContent = '~300'; return; }
  const start = performance.now();
  const tick = now => {
    const k = Math.min(1, (now - start) / 1100);
    el.textContent = '~' + Math.round(300 * (1 - Math.pow(1 - k, 3)));
    if (k < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function go(to) {
  const from = step;
  step = Math.max(0, Math.min(LAST, to));
  UI.asked = '';
  lastGo = performance.now();
  if (STEPS[step] === practice && from !== step) {
    // A fresh try: nothing from an earlier dictation, no key already lit.
    Object.assign(UI, { practiced: false, pressed: false, heard: false, result: null, revealed: false });
  }
  draw();
  const root = $('#onb');
  if (from !== step && !reduceMotion()) { root.classList.remove('enter'); void root.offsetWidth; root.classList.add('enter'); }
  // A screen reader starts reading the new step from its title.
  if (from !== step) $('#onb h1')?.focus();
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
  if (!o || e.detail > 1) return;  // a double-click is one press, not two steps
  if ((o === 'next' || o === 'done') && tooSoon()) return;
  if (o === 'next') go(step + 1);
  else if (o === 'goto-a11y') go(2);
  else if (o === 'goto-mic') go(1);
  else if (o === 'mic') { UI.asked = 'mic'; post({ t: 'mic' }); draw(); }
  else if (o === 'a11y') { UI.asked = 'a11y'; post({ t: 'a11y' }); draw(); }
  else if (o === 'verify') verify();
  else if (o === 'open-keys') post({ t: 'open', what: 'openai-keys' });
  else if (o === 'own-key') { UI.ownKey = true; draw(); }
  else if (o === 'download') { UI.dl = { p: 0, eta: '', done: false, error: false }; post({ t: 'download' }); draw(); }
  else if (o === 'done') { post({ t: 'meter', on: false }); post({ t: 'done' }); }
  else if (o === 'lang') post({ t: 'lang', v: e.target.closest('[data-o]').dataset.v });
  else if (o === 'source') { UI.dl = { p: 0, eta: '', done: false, error: false }; post({ t: 'source', v: e.target.closest('[data-o]').dataset.v }); draw(); }
});

document.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.isComposing) return;
  if (e.target.id === 'pr') return;
  if (e.target.id === 'key') { e.preventDefault(); verify(); return; }
  if (e.target.tagName === 'BUTTON' || tooSoon()) return;
  const primary = $('#onb .gbtn.pri:not(:disabled)');
  if (primary) { e.preventDefault(); primary.click(); }
});

// The practice box is filled by the app's own paste, like any other text field.
document.addEventListener('input', e => {
  if (e.target.id === 'pr' && e.target.value.trim() && !UI.practiced) {
    UI.practiced = true;
    draw();  // stays: the before/after is worth a look, and Continue is theirs
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
// The real input level moves the strokes of the big 言 on the microphone page.
let level = 0, peak = 0;
on('level', m => {
  const v = Math.min(1, Math.sqrt(Math.max(0, +m.v || 0)) * 1.6);
  level = v > level ? v : level * 0.8 + v * 0.2;  // quick to rise, slow to fall
  peak = Math.max(v, peak * 0.97);
  const el = $('.yan.live');
  if (el) { el.style.setProperty('--lv', level.toFixed(3)); el.style.setProperty('--pk', peak.toFixed(3)); }
});
// Right ⌘ (or F5) pressed somewhere: on the practice page the key lights up.
on('hotkey', m => {
  // Nothing to dictate with until the model is here, and no key without permissions.
  if (STEPS[step] !== practice || UI.practiced || !modelReady() || !S.ax || S.mic !== 'authorized') return;
  if (m.a === 'primary_down' && UI.pressed) {
    UI.heard = true;  // the second tap: it stopped listening and is working on it
    draw();
    return;
  }
  if (m.a === 'primary_down' || m.a === 'hands_free') {
    UI.pressed = true;
    const k = $('.krow .rc');
    if (k) { k.classList.remove('down'); void k.offsetWidth; k.classList.add('down'); }
    const st = $('#st');
    if (st) st.textContent = L('就是这个键。正在听，说完再点一下右 ⌘', 'That’s the one. Listening; tap right ⌘ again when done');
  } else if (m.a === 'cancel') { UI.pressed = UI.heard = false; draw(); }
});
// A dictation finished while the guide is open: what was heard, and what went in.
on('result', m => {
  if (STEPS[step] !== practice) return;
  UI.result = { raw: String(m.raw || ''), text: String(m.text || '') };
  // Done even when the paste went somewhere other than the box.
  UI.practiced = true;
  UI.heard = false;
  draw();
});
on('keyResult', m => { UI.keyBusy = false; UI.key = { ok: m.ok, msg: m.msg }; draw(); });
on('download', m => {
  const first = !UI.dl;
  UI.dl = m;
  // Progress only changes the line's text; a finished or failed download redraws the page.
  const line = $('#dlt');
  if (!m.done && !m.error) {
    if (line) {
      const pct = Math.round(m.p * 100);
      line.textContent = progressText(pct, m.eta);
      const fill = $('#dlb');
      if (fill) fill.style.width = pct + '%';
    }
    if (line || !first) return;  // a page without the line (Done) is not redrawn on every tick
  }
  draw();
});

post({ t: 'ready' });
})();
