# Typeless Local

Standalone macOS dictation overlay modeled after Typeless' Fn recording control,
with F5 (the dictation key on Apple keyboards) as the local trigger.

This app is intentionally separate from the Jarvis project. It can reuse Jarvis'
existing ASR configuration and modules through `JARVIS_PROJECT_ROOT`, but it owns
its own global hotkey, floating UI, recording lifecycle, refinement prompt, and
text insertion path.

## Run

As a local macOS app:

```bash
open -n "./Typeless Local.app"
```

Or from the terminal:

```bash
./scripts/run.sh
```

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
