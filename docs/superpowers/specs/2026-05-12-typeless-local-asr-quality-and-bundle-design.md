# Typeless Local: ASR Quality Loop + Self-Contained App Bundle

**Status:** Draft v2 (post-optimization)
**Date:** 2026-05-12
**Author:** Allen + Claude

## Problem

Typeless Local works end-to-end, but three pain points block daily use:

1. **ASR accuracy on proper nouns and domain terms.** Whisper consistently
   mis-hears names (`Jarvis`, `Typeless`, `mlx-whisper`, `PyObjC`, `Hermes
   Aging`, ...) as homophonic common words. The current `refine.py` preserves
   what Whisper produced rather than correcting it; nothing biases Whisper
   toward the user's vocabulary; nothing learns from corrections.
2. **No visible state.** The app runs as an accessory (`LSUIElement`) with
   only a transient floating overlay during recording. With the overlay
   hidden, the user can't tell whether the app is even running, and there's
   no quick action surface (quit, reload, open trace folder).
3. **Brittle packaging.** The `.app` bundle is a shell-script launcher that
   `exec`s `scripts/run.sh`, which itself depends on a sibling `jarvis/`
   checkout and its `.venv`. Moving the `.app` to another machine breaks it.

## Goals

- Improve ASR accuracy specifically for proper nouns / domain terms, by
  feeding a user-maintained vocabulary into both Whisper's `initial_prompt`
  and the existing refine LLM prompt.
- Record every dictation session to a SQLite trace database so the user can
  analyze quality, latency, and which terms get corrected.
- Auto-extract candidate hotwords from the trace (term-frequency analysis of
  raw-vs-refined diffs) into the user's vocabulary file.
- Show app state and basic actions in the macOS menu bar.
- Produce a self-contained `.app` bundle via py2app that doesn't depend on
  any external Python venv or sibling `jarvis/` checkout.

## Non-Goals

- Cross-language translation (out of scope; not what user wants).
- Cross-platform packaging (macOS only).
- Distribution / notarization / Gatekeeper trust (personal-use builds only;
  ad-hoc code signing is sufficient).
- Real-time streaming ASR / partial results.
- Sub-second latency targets — we accept ~1-2 s end-to-end as today.
- Audio archival (we deliberately do NOT store raw audio in the trace; only
  derived metrics).
- A GUI viewer for the trace DB (the user can `sqlite3 ~/.typeless-local/trace.db`
  or write ad-hoc scripts).

## Approach Overview

Two phases, independently shippable:

- **Phase A:** ASR quality loop. New `vocab.py`, `trace.py`,
  `scripts/extract_hotwords.py`. Modify `refine.py` to accept a vocab list
  and append a "correct mishears" instruction to the system prompt. Modify
  `asr.py` to pass the vocab as Whisper `initial_prompt`. Modify `app.py` to
  build a `SessionRecord` through the pipeline with `try/finally` semantics.
- **Phase B:** Status indicator + self-contained bundle. New `menubar.py`
  (NSStatusItem). New `setup.py` for py2app. Vendor the minimal `core/`
  subset of Jarvis (`speech_recognizer`, `media_ducking` and their
  transitive deps) into `typeless_local/_vendor/jarvis_core/`. New
  `scripts/build_app.py`. Strip the shell-script `.app` wrapper.

Critical design choice (re-revised during brainstorm): we **do not** add a
separate "VocabCorrector" LLM stage. Instead we fold the vocab-aware
correction into the existing `refine.py` system prompt. This keeps the LLM
call count at 1, avoids ~1 s of added latency, and the diff between
`raw_asr_text` and `refined_text` in the trace remains the right signal for
auto-extraction.

## Phase A — Components

### A1. `typeless_local/vocab.py` + `~/.typeless-local/vocab.yaml`

**File format.** Two flat string lists, nothing else:

```yaml
user:                       # User-edited. Never overwritten by scripts.
  - Jarvis
  - Typeless
  - mlx-whisper
  - PyObjC
auto:                       # Written by scripts/extract_hotwords.py.
  - "Hermes Aging"
  - "MoshiVox"
```

Frequency and `last_seen` metadata live in `trace.db`, not in the YAML.

**Public API.**

```python
def load_vocab(path: Path) -> list[str]:
    """Return deduplicated terms. Order: user first, then auto.
    Missing file → []. Malformed YAML → log warning, return []."""

def as_initial_prompt(terms: list[str], max_chars: int = 600) -> str:
    """Render terms as a single-line Whisper initial prompt:
        'Common terms: Jarvis, Typeless, mlx-whisper, PyObjC, ...'
    Truncates from the tail at term boundaries to stay under
    ~200 Whisper tokens. Empty list → empty string."""

def save_auto_terms(path: Path, terms: list[str]) -> None:
    """Re-write only the `auto:` section. Preserves `user:` and any
    leading comments / order. Atomic write via temp file + rename."""
```

**Edge cases.**

- File missing → first read creates `~/.typeless-local/` directory and
  writes a starter file with empty lists and an explanatory comment header.
- Duplicate term across `user` and `auto` → keep in `user`, drop from `auto`.
- Trailing whitespace / case differences → dedup case-sensitively (preserves
  the user's chosen capitalization).
- Very long lists → `as_initial_prompt` truncates with a hard char budget;
  truncation order is auto-section last-out (user terms always kept).

### A2. `typeless_local/asr.py`

Add a per-call `initial_prompt` to `JarvisASR.transcribe`. Implementation
note: `core.speech_recognizer.SpeechRecognizer.transcribe` currently does
not accept a per-call initial prompt — it reads `config["asr"]
["mlx_whisper_initial_prompt"]` at recognizer init. Two options at
implementation time, decided after reading the actual Jarvis API:

1. **Preferred:** add an optional `initial_prompt` kwarg to Jarvis's
   `transcribe`. Backward compatible. Requires a small Jarvis-side change
   (and once Jarvis is vendored, this lives in our tree).
2. **Fallback:** mutate `self._recognizer._config["asr"]
   ["mlx_whisper_initial_prompt"]` in place before each `transcribe` call.
   Ugly but works without touching Jarvis core. Acceptable if mlx-whisper
   actually reads this field per call.

The choice is made during impl; the public `JarvisASR.transcribe(audio,
initial_prompt=None)` signature is the contract.

### A3. `typeless_local/refine.py`

The system prompt grows by one new section, appended only when a non-empty
vocab is passed:

```
User vocabulary (high-confidence terms used frequently by this user):
Jarvis, Typeless, mlx-whisper, PyObjC, Hermes Aging, MoshiVox

Where the raw transcript contains short fragments that are plausibly
mishears of these specific terms (homophones, fuzzy phonetic matches),
replace them with the correct term. Do not invent occurrences — only
correct fragments that already seem to be attempts at one of these terms.
```

API change:

```python
def refine(
    self,
    raw_text: str,
    context: FocusContext | None = None,
    vocab: list[str] | None = None,
) -> RefineResult: ...
```

When `vocab is None or empty`, the system prompt is exactly today's prompt
(no behavior change).

### A4. `typeless_local/trace.py`

SQLite-backed per-session record. Single table, single-writer (app process
only), WAL mode, auto-commit per row.

**Schema (`v1`).**

```sql
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at REAL NOT NULL,
  ended_at REAL NOT NULL,
  audio_duration_s REAL,
  audio_rms REAL,
  audio_sample_rate INTEGER,
  raw_asr_text TEXT,
  raw_asr_language TEXT,
  raw_asr_confidence REAL,
  refined_text TEXT,
  focus_app TEXT,
  focus_window TEXT,
  was_pasted INTEGER,                -- 0/1
  vocab_terms_used TEXT,             -- comma-separated, what we sent to ASR
  hotwords_count INTEGER,
  latency_asr_ms INTEGER,
  latency_refine_ms INTEGER,
  latency_total_ms INTEGER,
  asr_model TEXT,
  refine_model TEXT,
  app_version TEXT,                  -- git short hash at runtime
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_started_at ON sessions(started_at);
PRAGMA user_version = 1;
PRAGMA journal_mode = WAL;
```

**Public API.**

```python
@dataclass
class SessionRecord:
    started_at: float
    ended_at: float = 0.0
    audio_duration_s: float = 0.0
    audio_rms: float = 0.0
    audio_sample_rate: int = 0
    raw_asr_text: str = ""
    raw_asr_language: str = ""
    raw_asr_confidence: float = 0.0
    refined_text: str = ""
    focus_app: str = ""
    focus_window: str = ""
    was_pasted: bool = False
    vocab_terms_used: str = ""
    hotwords_count: int = 0
    latency_asr_ms: int = 0
    latency_refine_ms: int = 0
    latency_total_ms: int = 0
    asr_model: str = ""
    refine_model: str = ""
    app_version: str = ""
    error: str | None = None

class DictationTrace:
    def __init__(self, db_path: Path) -> None: ...
    def log(self, record: SessionRecord) -> None: ...
    def close(self) -> None: ...
```

`log` swallows any exception (logs at WARNING) and never raises — trace
failures must not break dictation.

**Migrations.** v1 only at first release. If schema changes later, branch on
`PRAGMA user_version` and apply ALTER TABLEs in order.

**Threading.** `DictationTrace.log()` opens a fresh `sqlite3.connect(...)`
per call (with `isolation_level=None` for autocommit). Avoids
`check_same_thread` issues: the trace object is constructed on the main
thread but called from the executor worker. Connect overhead is negligible
(~ms) at our once-per-session rate.

**Dropped sessions.** The pipeline also drops audio that fails the quality
gate (silence, too-short, low-volume) before ASR runs. Those still create a
trace row so we can count silence drops; the `error` column carries the
human-readable reason (`"dropped: low volume"`) and ASR / refine columns
are blank. This gives the user honest accuracy stats — total drops vs
successful transcriptions.

### A5. `scripts/extract_hotwords.py`

Standalone CLI:

```
python scripts/extract_hotwords.py [--db PATH] [--days 30]
                                   [--min-count 2] [--top-k 50]
                                   [--dry-run]
```

**Algorithm.**

1. Query `sessions` with `started_at >= now - days*86400`.
2. For each row, tokenize `raw_asr_text` and `refined_text`:
   - English: `re.findall(r"[A-Za-z][A-Za-z0-9-]+", text)` (≥ 2 chars).
   - Chinese: `re.findall(r"[一-鿿]{2,4}", text)` (2-4 CJK chars).
3. `added = set(refined_tokens) - set(raw_tokens)`.
4. Increment global counter for each token in `added`.
5. Filter:
   - Already in `vocab.user` (case-insensitive) → drop.
   - Length < 2 → drop.
   - In stopword list (`assets/stopwords-zh.txt`, `assets/stopwords-en.txt`)
     → drop.
   - Count < `min_count` → drop.
6. Sort by count desc, truncate to `top_k`.
7. Print before/after summary. With `--dry-run`, stop here.
8. `save_auto_terms(vocab_path, top_terms)`.

**Stopwords.** Ship a minimal list (~200 zh + ~200 en common words / fillers)
under `assets/`. Editable; reload from disk on each run.

**No automatic scheduling in v1.** User runs it manually or via cron. Future:
trigger from menu bar "Refresh Auto-Hotwords" item.

### A6. `typeless_local/app.py` wiring

Two surfaces change:

1. **At init** — load vocab once, instantiate trace.
2. **In `_process_audio`** — wrap the existing ASR → refine → paste flow in
   a `SessionRecord` built via try/finally:

```python
def _process_audio(self, audio, context, session_id):
    record = SessionRecord(
        started_at=time.time(),
        audio_duration_s=audio.size / self.config.sample_rate,
        audio_rms=self.recorder.get_volume_level(audio),
        audio_sample_rate=self.config.sample_rate,
        focus_app=context.app_name,
        focus_window=context.window_title,
        vocab_terms_used=", ".join(self.vocab),
        hotwords_count=len(self.vocab),
        asr_model=self.asr.model_name,
        refine_model=self.config.refine.model,
        app_version=self._app_version,
    )
    try:
        # ... existing quality gate, ASR, refine, paste ...
        record.raw_asr_text = transcript.text
        record.raw_asr_language = transcript.language
        record.raw_asr_confidence = transcript.confidence
        record.latency_asr_ms = ...
        record.refined_text = refined.text
        record.latency_refine_ms = ...
        record.was_pasted = pasted
    except Exception as exc:
        record.error = repr(exc)
        raise
    finally:
        record.ended_at = time.time()
        record.latency_total_ms = int((record.ended_at - record.started_at) * 1000)
        self.trace.log(record)
```

Also expose `reload_vocab()` for the menu bar to call. `reload_vocab()`
atomically replaces `self.vocab` with a freshly loaded list (no in-place
mutation), so a concurrent ASR worker reading `self.vocab` sees either the
old or new list — never a torn intermediate state.

`was_pasted` is set to `True` only **after** `paste_text(final_text)`
returns successfully, not from the `context.can_insert_text` prediction —
that way the trace reflects what actually happened, including paste
failures (which fall through to the copy-fallback path).

Latency capture uses `time.monotonic()` snapshots wrapped in a small
`_StopWatch` helper to keep `_process_audio` readable: stopwatches for
`asr`, `refine`, and total are aggregated into the record at the end of
each stage.

### A7. `typeless_local/config.py`

Add three resolved paths:

```python
@dataclass(frozen=True)
class AppConfig:
    ...
    vocab_path: Path           # ~/.typeless-local/vocab.yaml
    trace_db_path: Path        # ~/.typeless-local/trace.db
    stopwords_dir: Path        # assets/ inside the app bundle
```

`load_config()` ensures `~/.typeless-local/` exists; if `vocab.yaml` is
missing, writes a starter file with empty lists.

**Logging.** `configure_logging()` is also updated to route logs to
`~/.typeless-local/app.log` (rotating, 1 MB × 5 files via
`RotatingFileHandler`) in addition to stderr. The menu bar's "Show Log"
opens this path. The legacy `/tmp/typeless-local-launch.log` (written by the
old shell-script wrapper) is no longer used by the py2app bundle.

### A8. Tests

| File | Coverage |
|---|---|
| `tests/test_vocab.py` | Load, save, truncation, dedup, missing file, malformed YAML. |
| `tests/test_trace.py` | Schema creation, insert, query, WAL mode, log() swallows errors. |
| `tests/test_extract_hotwords.py` | Tokenization, added-set computation, stopword filtering, dry-run. |
| `tests/test_refine.py` | Vocab section appears in system prompt iff vocab non-empty; idempotent on empty vocab. |
| `tests/test_app_trace_wiring.py` | Fake ASR + refine; assert a `sessions` row matches expectations; assert error path also logs a row; assert low-quality drops also log a row. |
| `tests/test_vocab.py` (continued) | `as_initial_prompt` truncation: long input list is cut at term boundary, user terms always preserved over auto terms when truncating. |

Existing tests for app/audio remain. Run `pytest -q` as the green-bar gate.

## Phase B — Components

### B1. `typeless_local/menubar.py`

**Stateful NSStatusItem.** SF Symbols for icons, system colors for tint:

| App state | SF Symbol | Tint |
|---|---|---|
| idle | `mic` | systemGray |
| starting | `mic` | systemYellow |
| recording | `record.circle.fill` | systemRed |
| processing | `ellipsis.circle` | systemYellow |
| error | `exclamationmark.triangle.fill` | systemRed, auto-reset to idle after 3s |

**Menu items.**

```
[disabled] Typeless Local — <state>
─────────
Reload Vocab                                ⌘R
─────────
Open Trace Folder
Show Log
─────────
Quit                                        ⌘Q
```

**API.**

```python
class MenuBarIcon:
    def __init__(
        self,
        on_reload_vocab: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None: ...
    def setup(self) -> None: ...
    def set_state(self, state: Literal["idle","starting","recording","processing","error"]) -> None: ...
```

**Thread safety.** All NSStatusItem mutations route through
`AppHelper.callAfter` so worker threads can call `set_state` directly. The
class is constructed on the main thread during `app.start()`.

**Integration in `app.py`.** Every `self.state = "..."` assignment is
followed by `self._set_menubar(self.state)`. Existing floating overlay is
untouched and continues to work in parallel.

### B2. py2app self-contained bundle

**`setup.py`** at repo root (replacing the shell-script `.app/Contents/MacOS/typeless-local`):

```python
from setuptools import setup

APP = ['typeless_local/__main__.py']
DATA_FILES = [
    ('Resources', ['assets/AppIcon.icns', 'assets/config.yaml',
                   'assets/stopwords-zh.txt', 'assets/stopwords-en.txt']),
]
OPTIONS = {
    'argv_emulation': False,
    'packages': [
        'typeless_local', 'numpy', 'sounddevice', 'AppKit', 'Quartz',
        'ApplicationServices', 'PyObjCTools', 'objc', 'openai', 'yaml',
        'mlx_whisper',
    ],
    'includes': ['ctypes', 'sqlite3', 'json', 're'],
    'excludes': ['tkinter', 'PIL', 'matplotlib', 'pytest', 'setuptools',
                 'pip', 'wheel'],
    'plist': {
        'CFBundleName': 'Typeless Local',
        'CFBundleDisplayName': 'Typeless Local',
        'CFBundleIdentifier': 'com.alllllenshi.typeless-local',
        'CFBundleShortVersionString': '0.2.0',
        'CFBundleVersion': '0.2.0',
        'LSUIElement': True,
        'LSMinimumSystemVersion': '13.0',
        'NSHighResolutionCapable': True,
        'NSMicrophoneUsageDescription':
            'Typeless Local records audio when you press F5 to dictate.',
        'NSAppleEventsUsageDescription':
            'Typeless Local pastes refined dictation into the focused app.',
    },
    'iconfile': 'assets/AppIcon.icns',
}

setup(
    app=APP,
    name='Typeless Local',
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
```

**Vendored Jarvis.** Create `typeless_local/_vendor/jarvis_core/` and copy
the minimum required source files. Concretely:

1. **Trace deps first.** During implementation, run an import-graph trace
   from `core.speech_recognizer` and `core.media_ducking` over the current
   Jarvis tree to enumerate what they actually import from sibling Jarvis
   modules. Document the result inline in `_vendor/README.md`.
2. **Copy verbatim.** Each vendored file's first comment line is `# vendored
   from jarvis @ <commit> on <date>` so future syncs are auditable.
3. **Rewrite imports.** Inside vendored files, `from core.X` becomes `from
   typeless_local._vendor.jarvis_core.X`. Top-level vendored package
   exposes `SpeechRecognizer` and `SystemAudioDucker` re-exports.
4. **App-side imports** (`asr.py`, `app.py`) switch to the vendored paths.
5. **Dev fallback.** If `JARVIS_PROJECT_ROOT` is set and the vendored
   modules import fails, fall back to the sibling tree — useful while
   developing.

**Config relocation.** The current `core.speech_recognizer` reads
`config.yaml` from `jarvis_root`. We replace this dependency:

- Ship a minimal `assets/config.yaml` inside the `.app/Contents/Resources/`
  containing only the fields typeless-local actually reads (asr provider,
  asr models, refine preset). Load order:
  1. `~/.typeless-local/config.yaml` if it exists (user override).
  2. `<bundle>/Contents/Resources/config.yaml` (shipped default).
  3. `<repo>/assets/config.yaml` (dev fallback).

**Model files.** mlx-whisper model (`whisper-large-v3-turbo`, ~1.5 GB) is
*not* bundled. On first run, mlx-whisper downloads to
`~/.cache/huggingface/` as it already does. The menu bar shows
`Downloading model…` during first transcription; the floating overlay
keeps the existing "Thinking" indicator.

**Build script `scripts/build_app.py`:**

```python
#!/usr/bin/env python
import shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist'

def main():
    for d in (ROOT / 'build', DIST):
        if d.exists():
            shutil.rmtree(d)
    subprocess.check_call([sys.executable, 'setup.py', 'py2app'], cwd=ROOT)
    app = DIST / 'Typeless Local.app'
    subprocess.check_call(['codesign', '--force', '--deep', '--sign', '-', str(app)])
    print(f"Built: {app}")

if __name__ == '__main__':
    main()
```

Ad-hoc signing (`--sign -`) gives the bundle a stable identity so macOS
permissions (mic, accessibility) survive rebuilds as long as
`CFBundleIdentifier` doesn't change.

**Version baking.** Inside a built `.app` the `.git/` directory is absent,
so runtime `git rev-parse` fails. The build script writes
`typeless_local/_version.py` (a single line `VERSION = "0.2.0+abc1234"`)
**before** invoking py2app, capturing the git short hash + dirty marker if
applicable. At runtime, `app_version` reads from `_version.VERSION` if
present, else falls back to subprocess `git rev-parse --short HEAD`, else
`"unknown"`.

**Required config keys.** During Phase B2, before vendoring, the
implementer must run `core.speech_recognizer` against an empty config and
record the `KeyError` traces — those are the required keys that must be
present in `assets/config.yaml`. Mirror them with sane defaults
(specifically: `asr.provider`, `asr.mlx_whisper_model`,
`asr.sensevoice_model_dir` if used, `audio.vad_model_path` if used).

**Cleanup of old shell wrapper.** Remove:

- `Typeless Local.app/` (the in-tree shell wrapper). The build output is
  `dist/Typeless Local.app/` which the user moves to `/Applications/`.
- Keep `scripts/run.sh` for dev mode but document it's dev-only.

### B3. Tests

| File | Coverage |
|---|---|
| `tests/test_menubar.py` | `set_state` updates the tracked state; menu wiring callbacks fire. (Hard to assert NSStatusItem in headless tests; assert internal state and call recording instead.) |
| `tests/test_vendor_imports.py` | After build (or in dev with `JARVIS_PROJECT_ROOT` unset), `typeless_local._vendor.jarvis_core.SpeechRecognizer` imports cleanly. |
| Manual smoke | `python scripts/build_app.py && open dist/Typeless\ Local.app` — verify menubar shows, F5 records, vocab applied. |

## File Layout (final)

```
typeless-local/
├── typeless_local/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py                       # modified
│   ├── asr.py                       # modified
│   ├── audio.py                     # untouched
│   ├── config.py                    # modified
│   ├── mac_integration.py           # untouched
│   ├── menubar.py                   # new
│   ├── overlay.py                   # untouched
│   ├── refine.py                    # modified
│   ├── trace.py                     # new
│   ├── vocab.py                     # new
│   └── _vendor/
│       └── jarvis_core/             # new (vendored)
│           ├── __init__.py
│           ├── README.md
│           ├── speech_recognizer.py
│           ├── media_ducking.py
│           └── ... (transitive deps)
├── assets/                          # new
│   ├── AppIcon.icns
│   ├── config.yaml
│   ├── stopwords-en.txt
│   └── stopwords-zh.txt
├── scripts/
│   ├── build_app.py                 # new
│   ├── extract_hotwords.py          # new
│   ├── final_pixel_gate.sh          # untouched
│   ├── run.sh                       # untouched (dev only)
│   └── video_pixel_audit.py         # untouched
├── tests/
│   ├── test_app_trace_wiring.py     # new
│   ├── test_extract_hotwords.py     # new
│   ├── test_menubar.py              # new
│   ├── test_refine.py               # new
│   ├── test_trace.py                # new
│   ├── test_vendor_imports.py       # new
│   └── test_vocab.py                # new
├── docs/superpowers/
│   ├── specs/2026-05-12-typeless-local-asr-quality-and-bundle-design.md
│   └── plans/2026-05-12-typeless-local-impl-plan.md
├── setup.py                         # new (py2app)
├── pyproject.toml                   # updated (deps)
└── README.md                        # updated
```

User-side runtime files (auto-created):

```
~/.typeless-local/
├── vocab.yaml
├── trace.db
└── config.yaml                      # optional user override
```

## Error Handling

- **Vocab file malformed or missing** → log warning, treat as empty list.
- **Trace insert fails** → log warning, do not block dictation.
- **Vendored Jarvis fails to import** → log error, fall back to env-based
  Jarvis root if `JARVIS_PROJECT_ROOT` is set; otherwise surface to user.
- **Model download failure** → existing error path in `asr.py`; menu bar
  flashes error state.
- **HF cache unwritable** → existing mlx-whisper behavior; user sees error
  in overlay.

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Vendoring Jarvis core pulls in much larger dep graph than expected | Medium | Phase B2 starts with an import-graph trace; if vendoring balloons, fall back to "ship .venv inside .app" (the originally-rejected option C). Decision deferred until impl. |
| py2app misses a runtime import (common with pyobjc / mlx) | High | Test the built `.app` end-to-end before declaring done. Use `--debug-modulegraph` if needed. Add explicit `packages` / `includes`. |
| Vocab in Whisper initial prompt actively hurts on terms not present in audio | Low | Whisper is well-known to handle initial prompts gracefully; correction LLM also forbidden from inventing terms. Verified empirically before merge. |
| Refine LLM with vocab section starts "correcting" things that weren't mishears | Medium | Prompt explicitly says "only correct fragments that already seem to be attempts at one of these terms"; test cases cover this. If still problematic, fall back to two-stage (correct.py) — design preserves that as a clean option. |
| Trace DB grows unbounded | Low | Per-session row ~1 KB. 100 sessions/day × 365 days = ~36 MB/yr. Acceptable. If it becomes an issue, add `--retain-days` to a future maintenance script. |
| Menu bar state diverges from app state (race) | Low | All updates via `AppHelper.callAfter`; menubar reflects last `set_state` call. Worst case: brief stale indicator. |
| Stopword lists not yet exist as source files | Certain | Build them as part of Phase A5: ship a small curated list (~150 zh + ~150 en) committed to `assets/`. The actual lists are part of the implementation deliverable. |
| `_version.py` becomes stale when devs forget to rebuild | Low | Build script always overwrites; dev mode falls back to live `git rev-parse`. |
| Vocab list leaks into Whisper output as a spoken phrase | Low | Whisper occasionally repeats initial prompt in output for very short audio. Mitigation: the refine LLM strips any "Common terms: ..." prefix it sees; add a defensive `re.sub(r'^Common terms:.*?\n', '', text)` in `JarvisASR.transcribe` post-process. |

## Implementation Order

Linear with checkpoints. Each phase has a green-bar gate before moving on.

1. **Phase A1+A2+A3** — vocab, asr signature, refine signature. Pure
   library code, no app wiring yet. Tests: `test_vocab`, `test_refine`.
2. **Phase A4** — trace module + DB. Tests: `test_trace`.
3. **Phase A5** — `extract_hotwords.py`. Tests: `test_extract_hotwords`.
4. **Phase A6+A7** — wire `app.py` and `config.py`. Tests:
   `test_app_trace_wiring`.
5. **Phase B1** — menubar. Tests: `test_menubar`. App still runs via dev
   mode `scripts/run.sh`.
6. **Phase B2** — vendoring + py2app + build script. Tests:
   `test_vendor_imports`, manual `dist/Typeless Local.app` smoke.
7. **Final smoke** — clean-room build, install to `/Applications/`, grant
   permissions, do five real dictations, verify trace rows.

The implementation plan (`plans/2026-05-12-typeless-local-impl-plan.md`)
breaks each phase into concrete file-level tasks with acceptance criteria.

## Out of Scope (Explicit YAGNI)

- Snippets / voice commands ("send", "new paragraph", ...).
- Custom AI "personalities" (formal, casual, etc.).
- Personalization learning loop beyond simple auto-hotword extraction.
- Web search integration.
- Mobile / iOS.
- Notarization / Gatekeeper distribution.
- A trace viewer GUI.
- Audio archival.
- Multi-user / multi-vocab profiles.
- Multi-word phrase auto-extraction (only unigrams in v1; user can manually
  add multi-word phrases like "Hermes Aging" to `user:`).
- Real-time streaming partial transcripts.
- Confidence-based ASR re-run / two-pass decoding.

## Optimization Pass v2 — What Changed Since v1

| Topic | v1 had | v2 has | Reason |
|---|---|---|---|
| Threading on trace DB | Implicit single conn | Fresh connection per `log()` | Avoid `check_same_thread` issues across executor/main threads. |
| Low-quality drops | Not recorded | Logged as trace rows with `error` field | Otherwise accuracy stats undercount silence/short drops. |
| `was_pasted` | Set from `context.can_insert_text` | Set after paste returns | Trace reflects reality including paste failures. |
| Log file location | `/tmp/typeless-local-launch.log` (shell-script era) | `~/.typeless-local/app.log` (RotatingFileHandler) | Survives reboots; works inside `.app`; menu bar "Show Log" has a stable path. |
| Version capture | Runtime `git rev-parse` | Build-time `_version.py` baked, runtime fallback to git or "unknown" | `.app` bundle has no `.git/`. |
| Vocab leak into Whisper output | Not addressed | Defensive `re.sub` strip in `transcribe` | Whisper sometimes echoes initial prompt for short audio. |
| Reload-vocab race | Not addressed | Atomic list-replace via `self.vocab = new_list` | Worker thread reading vocab can't see partial update. |
| Stopword lists | "Implementer decides" | Ship `assets/stopwords-{en,zh}.txt` as deliverables | Removes hidden setup step. |
| Latency capture | Hand-rolled timestamps | Small `_StopWatch` helper | Keeps `_process_audio` readable as it grows. |
| Required Jarvis config keys | "Implementer figures out" | Documented: trace via empty-config KeyError run, mirror in `assets/config.yaml` | Otherwise vendoring silently breaks on first run. |
