# 言字 (Yana)

**[Download for macOS](https://github.com/samsara0xgg/typeless-local/releases/download/v0.4.3/Yana-0.4.3.dmg)** (Apple silicon, macOS 13.5+)

> **Limited-time free trial.** Download Yana now and dictate with no API key: a new Mac in the US or Canada gets free refinement to start.

A standalone macOS dictation app: hold a key, talk, and the cleaned-up text is
pasted into whatever app you were in. Speech recognition runs locally through
Whisper; only the final tidy-up pass goes to a language model.

The app is called 言字 on a Chinese system and Yana everywhere else
(`typeless_local/brand.py` holds both). It used to be called Typlus: the bundle
ID and the `~/.typlus` folder keep that name, so the permissions macOS granted
and your key, words and history carry over.

## Gets more accurate the more you use it

Yana learns your words from how you use it, with nothing to set up:

- **It learns from the fixes you already make.** Dictate into a chat box, fix
  a misheard word right there, press Enter: Yana compares what it pasted with
  what you sent and adds the corrected word to your vocabulary on the spot
  ("Jeff → Jev"). Only small word swaps count; rewording, added or deleted
  text, punctuation and capitalization are ignored, so normal editing does not
  pollute it. Learned words are listed under **Settings › 词库** with how
  often you fixed them, and one click removes a word for good. Works in
  Claude, ChatGPT and most Mac apps; apps that hide their text box from other
  apps (WeChat) can't be learned from.
- **Hot words reach both steps.** Your whole vocabulary goes to the
  refinement model, which turns mishearings of those terms back into the right
  words. Speech recognition gets the hottest of them as a hint (Whisper's hint
  has room for about 600 characters): ranked by how many times you fixed a word
  and how often it came up in the last 90 days, so the words it keeps getting
  wrong come first.
- **Context.** Refinement sees which app you are in and its window title, so
  a message in a chat, an email and code each come out right. Optionally it
  also reads up to 300 characters before the cursor (off by default). Each is
  a switch in **Settings › 历史与隐私**; password fields are never read.
- **Your languages.** On Automatic, the spoken language is detected every
  time, mixed languages included. Short clips are kept to the languages this
  Mac and your longer dictations show you speak, so a two-second phrase is
  not mistaken for Icelandic. Chinese always comes out in Simplified
  characters, and nothing is ever translated.

## Install

[Download Yana-0.4.3.dmg](https://github.com/samsara0xgg/typeless-local/releases/download/v0.4.3/Yana-0.4.3.dmg) (all versions are under
[Releases](https://github.com/samsara0xgg/typeless-local/releases)), open it, and
drag the app to Applications. The build is signed and notarized by Apple, so it
opens by double-clicking with no security warnings. If an older `Typlus.app` is
still in Applications, delete it.

On first launch a short guide walks through what the app needs, one step at a
time, and continues by itself as each permission comes through:

- **Microphone**, to record what you say.
- **Accessibility**, to see the global hotkey and paste into other apps.
- **An API key** for the refinement model, kept in the login keychain. In the
  US and Canada it is optional at first: a new Mac without a key gets a free
  trial of refinement (see below). Elsewhere it can be skipped, and dictation
  then pastes the raw transcript.
- **One practice dictation** into the guide's own text box.

The speech model (~1.5 GB) downloads from the moment the app opens, with a
thin progress line under every step rather than a step of its own. If it
fails, the guide and the menu offer to try again (or to switch source); too
little disk space is caught before it starts.

Anyone already set up (an existing Typlus user) never sees the guide. Keys can
be changed later in **Settings › 润色模型**.

It needs a Mac with Apple silicon (M1 or later) on macOS 13.5 or later:
speech recognition runs on MLX, which has no Intel build. On an Intel Mac, or under Rosetta, it says so
and quits.

In mainland China (the Mac's region is China, or its clock is on China time),
Hugging Face and OpenAI don't answer, so there the model downloads from
hf-mirror.com and a new install starts on DeepSeek. **Settings › 听写 › 模型下载源**
picks the download source by hand; an `HF_ENDPOINT` set in the environment
always wins.

## Use

- Tap right `Cmd` to start dictation and tap it again to finish. Hold it
  alone for a moment (0.35 s) to talk while holding; letting go finishes.
- Double-tap right `Cmd` for hands-free dictation; right `Cmd+Space` locks a
  recording already running (when idle it stays `Cmd+Space`, Spotlight).
- Right `Cmd` used as a modifier (`Cmd+C`, `Cmd+Tab`, `Cmd`-click) does nothing.
  A hold that turns into a chord drops only the recording it started; muting
  and pausing music wait until a hold has lasted 0.6 s. It is never armed with
  another modifier down or while a password field has Secure Input on.
- **Settings › 快捷键 › 用右 ⌘ 听写** turns right `Cmd` off for anyone whose
  right `Cmd` switches input sources; `F5` is then the shortcut.
- `F5` (the dictation key on a MacBook) is left to macOS's own dictation unless
  **Settings › 快捷键 › 也用 F5** is on. Installs set up before 0.4.0 keep it on.
- `Esc` cancels the active or pending dictation.
- `Return` while recording finishes the dictation and sends it: once the text
  has landed in the field, Return is pressed for you. Not after a raw-transcript
  fallback or a paste that did not land. `Shift+Return` is left alone.
- While recording, system output is muted and playing music is paused, then
  both are restored. Music only counts as paused when its app visibly stops
  sending audio; with only a call (Zoom, WeChat, Teams) holding output, the
  play/pause key is never pressed. A speaker with no software volume cannot
  be muted, and Settings › 音频 says so. Turning off **录音时静音其他声音**
  leaves both alone.
- If refinement fails, times out, or its reply is cut off, the raw transcript
  is pasted instead, so a dictation is never lost to the polish step.
- **Settings** (`⌘,` from the menu) has nine panes: general, dictation,
  shortcuts, refinement models and keys, vocabulary, audio, usage, history
  and privacy, and about.
- **Feedback**: Settings › 关于 (or **发送反馈…** in the menu) has a box
  that sends a message straight to the developer, with the app and macOS
  version and Mac model, optionally a reply address, and diagnostics only if
  you tick the box. Never any dictated text.
- **History** (`⌘Y`) lists every dictation by day, shows what the model changed
  and where the time went, and adds a misheard word to the vocabulary in one
  click. Nothing is ever deleted unless you pick a retention limit.
- **What you actually sent**: after a paste, the field it landed in is read
  until it empties (a chat box on Enter) or you switch apps, and the final
  text is stored next to the refined one, so History shows what you fixed by
  hand and the vocabulary learns the words you corrected. Only small fields,
  never documents; off in Settings › 历史与隐私.
- **English practice** (menu: **英语练习**, off by default): the same refine
  request also writes a natural English version and 1-3 phrases worth keeping,
  shown in a card after the paste; the paste itself is not delayed. For an
  English dictation it offers a more natural phrasing with **Use this**.
- **Word book**: click a word on the English card, or drag across several, to
  keep it. Its Chinese meaning in that sentence is looked up once with
  gpt-5.6-luna; History › 单词本 lists them with the sentence they came from.
  Stored only in the local history database.
- **Spoken language** (Settings › 听写 › 识别语言): Automatic, 中文, English
  or Français. Keep Automatic if you speak more than one language; a fixed
  language is only for people who speak just that one.
- **Diagnostics** (Settings › 通用 › 诊断信息) zips the log, the changed
  settings and a summary of the Mac for a bug report, with API keys cut out and
  no dictation history, and shows the file in Finder.
- **Usage** (Settings › 用量, and a line in the menu) counts dictations per day
  and estimates what refinement cost, from the token counts the API returned
  for this app's own requests. Prices for gpt-5.4-mini / gpt-5.6-terra /
  gpt-5.6-luna are built in; add others under `llm.prices` in
  `~/.typlus/config.yaml` as `model: [input, cached input, output]` dollars per
  million tokens.

## Free trial and usage stats

A new Mac whose region is the US or Canada (or, with no region set, whose clock
is on a US or Canadian time zone) and that has no OpenAI key starts on the
`free-trial` preset: refinement goes through a small Cloudflare Worker
(`worker/`) that holds the owner's key, with a budget of $0.50 per Mac (about
300 refinements), $1 per network per day and a monthly cap across everyone.
The Worker checks the country again and only accepts the app's own refine
request. The app sends a random per-Mac token in place of an API key; the
dictated text passes through the Worker to OpenAI and is not stored. When the
trial runs out (remembered, so the Worker is not asked again), or outside
those two countries, dictation pastes the raw transcript and asks for the
user's own key; saving one switches to `gpt-5.6-terra` for good.

Feedback from Settings › 关于 goes to the same Worker and is stored for the
developer to read.

Once a day the app also sends anonymous usage stats to the same Worker: a
random ID for this Mac, the app version, and for each day the number of
dictations, their total character count and what the trial spent. Never any
dictated text, app names, window titles or anything personal. Turn it off in
**Settings › 历史与隐私 › 发送匿名使用统计**; the counts not yet sent are
deleted. `worker/README.md` covers deploying the Worker.

## Settings file

`~/.typlus/config.yaml` holds only what you changed. It is laid over the
bundled `assets/config.yaml` key by key, so a default changed in an update
reaches everyone who hasn't changed that key; delete a line to go back to the
default. Older installs have a full copy there, which keeps working as is.

API keys live in the login keychain. Older installs may still have them in
`~/.typlus/env` as `KEY=value` lines; variables already in the environment win.

Cmd+V and Cmd+Z are sent on whichever key types V and Z on the current keyboard
layout (AZERTY, Dvorak and so on), re-read when the layout changes.

## Vocabulary

Edit `~/.typlus/vocab.yaml` to bias speech recognition and refinement toward
your proper nouns and domain terms:

```yaml
user:
  - Typeless
  - mlx-whisper
auto: []   # auto-filled by scripts/extract_hotwords.py
```

`user:` entries are kept verbatim; `auto:` is rewritten by the extraction
script. Words learned from your hand edits are added to `user:` and noted in
`learned:` (what they were heard as, when, and how many times you fixed
them); a removed one goes to `rejected:` and is never learned again.
**Settings › 词库** edits `user:`, shows what was learned, offers `auto:`
terms to add or reject, and lists words from your recent hand corrections.

The refinement model gets every term. Whisper's hint is capped at about 600
characters, filled from the top of a ranking: 5 points for each time you
fixed a word by hand plus 1 for each dictation in the last 90 days that used
it, ties going to the most recently fixed.

To fill `auto:` from your own history:

```bash
python scripts/extract_hotwords.py --days 30 --min-count 2 --top-k 50
```

The script diffs `refined_text` against `raw_asr_text` per dictation, counts
added tokens, filters bilingual stopwords (`assets/stopwords-{en,zh}.txt`) and
existing `user:` terms, and writes the top survivors to `auto:`. `--dry-run`
prints the candidates without saving.

## History database

Every dictation writes one row to `~/.typlus/trace.db`:

```bash
sqlite3 ~/.typlus/trace.db \
  'SELECT datetime(started_at,"unixepoch","localtime") AS at,
          raw_asr_text, refined_text, latency_total_ms, error
     FROM sessions ORDER BY id DESC LIMIT 20'
```

Fields cover audio quality (rms, duration), per-stage latency, the vocabulary
sent to speech recognition, focus context, paste outcome, token counts, and any
pipeline error. The History window reads the same table.

## Interface

The capsule, Settings, History and the guide are web pages
(`typeless_local/web/`) drawn in transparent WKWebViews over native Liquid
Glass (`NSGlassEffectView` on macOS 26, a vibrancy view before that). The
pages only draw and report what the user did; `overlay.py`, `capsule.py` and
`windows.py` decide what they show and do what they ask.

The interface speaks Chinese or English (Settings › General › Language, or the
switch on the guide's first page; "Same as the Mac" follows the system
language). Every string is written where it is used as a pair, `t("设置",
"Settings")` in Python (`typeless_local/i18n.py`) and `L('设置', 'Settings')`
in the pages (`kit.js`), so a new string cannot ship in one language only
without it showing in review.

When running, the app is a 言 glyph in the menu bar (a Dock icon appears only
while one of its windows is open). A dot blinks while recording and the glyph
breathes while it transcribes and refines. An orange badge means something
needs fixing (no Accessibility, microphone denied, missing API key), and the
menu's first items say what and fix it. The menu also has the last dictation
to copy, the input-device picker, vocabulary, history and settings.

## Build from source

Run from the checkout:

```bash
PYTHON=/path/to/venv/bin/python ./scripts/run.sh
```

Build the app. py2app needs a Python with `libpython.dylib`, so use Homebrew's
or python.org's rather than a uv-standalone one:

```bash
/opt/homebrew/bin/python3.13 -m venv ~/.typlus-build-venv
~/.typlus-build-venv/bin/pip install \
  pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz \
  pyobjc-framework-ApplicationServices pyobjc-framework-WebKit \
  numpy sounddevice openai pyyaml mlx-whisper py2app dmgbuild
~/.typlus-build-venv/bin/python scripts/build_app.py
# Result at dist/Yana.app
```

`--release` also signs with a Developer ID, notarizes through Apple, staples
the ticket, and produces `dist/Yana-<version>.dmg`. Every build has to be
signed with the same Developer ID: an ad-hoc signed build looks like a
different app to macOS, which then drops the Accessibility permission.

The bundle is self-contained: its own Python, every wheel, and the vendored
Jarvis subset (`speech_recognizer`, `media_ducking`). The Whisper weights are
not bundled; they download to `~/.cache/huggingface/` on first launch.

The app icon is drawn by `scripts/make_icon.mjs` (`node scripts/make_icon.mjs
--icns` rewrites `assets/AppIcon.icns`; it needs Playwright).

Optional environment variables:

- `TYPELESS_LOCAL_LOG_LEVEL`: Python logging level, default `INFO`.
- `TYPELESS_LOCAL_DEBUG_HOTKEY`: `1` also uses right `Option` as a trigger
  when right `Cmd` cannot be captured.
- `TYPELESS_LOCAL_ASR_LANGUAGE`: a fixed Whisper language code. Empty by
  default, so mixed Chinese and English is detected.
- `TYPELESS_LOCAL_MLX_INITIAL_PROMPT`: a Whisper initial prompt. Empty by
  default.
- `JARVIS_PROJECT_ROOT`: a Jarvis checkout to reuse in dev mode. Defaults to
  a sibling `../jarvis` when present.
