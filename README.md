# Typeless Local

Standalone macOS dictation overlay modeled after Typeless' Fn recording control,
with F5 (the dictation key on Apple keyboards) as the local trigger.

This app is intentionally separate from the Jarvis project. It can reuse Jarvis'
existing ASR configuration and modules through `JARVIS_PROJECT_ROOT`, but it owns
its own global hotkey, floating UI, recording lifecycle, refinement prompt, and
text insertion path.

## Run

The shipped, self-contained app bundle:

```bash
open -n "/Applications/Typeless Local.app"
```

Dev mode (uses the sibling `jarvis/` checkout + its `.venv`):

```bash
./scripts/run.sh
```

### Build a fresh `.app`

```bash
# A Homebrew or python.org Python with libpython.dylib (uv-standalone Pythons
# don't ship one, so py2app's launcher can't link against them).
PYBUILD=/opt/homebrew/bin/python3.13
$PYBUILD -m venv /tmp/build-venv
/tmp/build-venv/bin/pip install \
  pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz \
  pyobjc-framework-ApplicationServices pyobjc-framework-WebKit \
  numpy sounddevice openai pyyaml mlx-whisper py2app
/tmp/build-venv/bin/python scripts/build_app.py
# Result at dist/Typeless Local.app — move to /Applications/.
```

The bundle is fully self-contained: it includes its own Python interpreter,
all wheels, and the vendored Jarvis core subset (`speech_recognizer` +
`media_ducking`). No external `jarvis/` checkout required at runtime.
First launch downloads the Whisper model to `~/.cache/huggingface/`
(~1.5 GB) on first F5 press.

Default behavior:

- `F5` starts and stops dictation.
- `F5+Space` starts hands-free dictation.
- `Esc` cancels the active or pending dictation.
- During recording, macOS system output is muted through Jarvis' Inherent
  `SystemAudioDucker` and restored when recording ends or is canceled.
- After recording stops, audio is transcribed through Jarvis ASR, refined with
  the Jarvis fast OpenAI preset (`gpt-5.4-mini`), then pasted into the previously
  focused app.

Permissions macOS may require:

- Microphone access for recording.
- Accessibility access for global key capture and paste insertion.

## Environment

Optional variables:

- `JARVIS_PROJECT_ROOT`: path to the Jarvis checkout. Defaults to the sibling
  `../jarvis` directory when present.
- `TYPELESS_LOCAL_LOG_LEVEL`: Python logging level, default `INFO`.
- `TYPELESS_LOCAL_DEBUG_HOTKEY`: set to `1` to also use `RightOption` as a
  debug trigger when F5 cannot be captured by the OS event tap.
- `TYPELESS_LOCAL_ASR_LANGUAGE`: optional fixed Whisper language code. Empty by
  default so dictation can auto-detect mixed Chinese/English input.
- `TYPELESS_LOCAL_MLX_INITIAL_PROMPT`: optional Whisper initial prompt. Empty by
  default to avoid Jarvis' command-oriented Chinese bias in this dictation app.

Secrets are not stored here. The OpenAI API key is read through Jarvis'
`config.yaml` preset, normally `OPENAI_API_KEY`.

## Vocabulary

Edit `~/.typeless-local/vocab.yaml` to bias the ASR + refine LLM toward
your proper nouns and domain terms:

```yaml
user:
  - Jarvis
  - Typeless
  - mlx-whisper
auto: []   # auto-filled by scripts/extract_hotwords.py
```

`user:` entries are kept verbatim; `auto:` is rewritten by the extraction
script. The menu-bar **Reload Vocab** action re-reads the file without
restarting.

## Trace database

Every dictation session writes one row to `~/.typeless-local/trace.db`:

```bash
sqlite3 ~/.typeless-local/trace.db \
  'SELECT datetime(started_at,"unixepoch","localtime") AS at,
          raw_asr_text, refined_text, latency_total_ms, error
     FROM sessions ORDER BY id DESC LIMIT 20'
```

Fields cover audio quality (rms, duration), per-stage latency, the vocab
list sent to ASR, focus context, paste outcome, and any pipeline error.

## Auto-discover hotwords

```bash
python scripts/extract_hotwords.py --days 30 --min-count 2 --top-k 50
```

The script diffs `refined_text` vs `raw_asr_text` per session, counts
"added" tokens, filters bilingual stopwords (`assets/stopwords-{en,zh}.txt`)
and existing `user:` terms, and writes the top survivors to `auto:`.
`--dry-run` prints candidates without saving.

## Menu bar

When running, Typeless Local appears as a menu-bar icon (no Dock icon).
Color reflects state: gray (idle), yellow (starting/thinking), red
(recording or error). Click the icon for **Reload Vocab**, **Open Trace
Folder**, **Show Log**, and **Quit**.

## Pixel Audit

Recommended capture protocol for the final local recording:

1. Open a bright, non-editable background window, such as a blank browser page.
2. Do not focus a text input. The end of the recording should show the Copy
   fallback instead of inserting text.
3. Use the same macOS screen-recording UI used for the reference videos. The
   command-line `screencapture -v` path may miss the floating overlay and should
   not be used as final proof.
4. Start recording, press `F5`, speak a short phrase, press `F5` again to finish,
   and keep recording until Thinking and Copy fallback have both appeared.
5. Run the audit command below against the official and latest local `.mov`.

To compare an official Typeless recording against a local recording:

```bash
python scripts/video_pixel_audit.py \
  --official "/path/to/official.mov" \
  --local "/path/to/local.mov" \
  --fps 5 \
  --gate
```

Or use the wrapper:

```bash
scripts/final_pixel_gate.sh "/path/to/official.mov" "/path/to/local.mov"
```

The audit extracts frames with `ffmpeg` and reports recording, Thinking, copy
fallback, and waveform metrics as JSON. With `--gate`, it exits non-zero when
the local recording misses required UI states or exceeds pixel/waveform
thresholds. By default, each run uses a process-specific extraction directory
under `/tmp`; `--reuse` requires `--workdir <path>` and should only be used
when intentionally reusing a single extracted frame cache. It is intended for
regression checks against new local screen recordings.
