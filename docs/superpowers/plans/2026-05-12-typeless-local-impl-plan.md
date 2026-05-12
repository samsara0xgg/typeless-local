# Typeless Local: ASR Quality + Self-Contained Bundle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-vocabulary-driven ASR quality loop (vocab → Whisper initial prompt + refine prompt, SQLite trace per session, CLI auto-extract of hotwords), a macOS menu-bar status indicator, and a self-contained py2app `.app` bundle that doesn't depend on a sibling Jarvis checkout.

**Architecture:** Two phases. Phase A adds new pure-library modules (`vocab.py`, `trace.py`) and a CLI (`extract_hotwords.py`), modifies `refine.py` / `asr.py` / `config.py` / `app.py` to wire them in. Phase B adds `menubar.py`, vendors a minimal subset of Jarvis core into `typeless_local/_vendor/jarvis_core/`, and ships a `setup.py` + `scripts/build_app.py` that produces a fully self-contained `.app`.

**Tech Stack:** Python 3.12, PyObjC (AppKit / Quartz / ApplicationServices), sqlite3, mlx-whisper, openai, PyYAML, py2app.

**Spec:** `docs/superpowers/specs/2026-05-12-typeless-local-asr-quality-and-bundle-design.md`

**Parallelization marks:**
- 🟢 `PARALLEL-A` — no shared file edits with other 🟢-A tasks; dispatch concurrently.
- 🟡 `PARALLEL-B` — depends on a 🟢-A batch finishing, but independent of other 🟡-B siblings.
- 🔴 `SERIAL` — must run after all preceding parallel batches.

**Verification (global):** After every task, run `pytest -q` from repo root. The plan never advances when tests fail.

---

## Phase A — Library code (Batch 1: 🟢 PARALLEL-A)

### Task 1 — Stopword data files 🟢 PARALLEL-A

**Files:**
- Create: `assets/stopwords-en.txt`
- Create: `assets/stopwords-zh.txt`

- [ ] **Step 1: Create assets directory**

```bash
mkdir -p /Users/alllllenshi/Projects/typeless-local/assets
```

- [ ] **Step 2: Write the English stopwords file**

Content (one term per line, lowercase, ASCII):

```
the
a
an
and
or
but
if
then
else
of
in
on
at
to
for
from
by
with
about
as
is
are
was
were
be
been
being
have
has
had
do
does
did
will
would
should
could
may
might
must
shall
can
i
you
he
she
it
we
they
me
him
her
us
them
my
your
his
its
our
their
this
that
these
those
um
uh
hmm
yeah
yes
no
okay
ok
right
well
so
just
like
really
actually
basically
literally
maybe
perhaps
probably
not
none
some
any
all
every
each
many
much
more
most
less
least
few
several
own
same
other
another
new
old
good
bad
great
also
too
very
quite
rather
also
already
still
yet
ever
never
always
sometimes
often
again
once
twice
here
there
where
when
why
how
what
which
who
whom
whose
because
while
during
before
after
since
until
through
between
above
below
under
over
into
onto
upon
without
within
out
off
up
down
back
forth
away
together
apart
along
across
around
beyond
toward
inside
outside
near
far
```

Write that exact list to `/Users/alllllenshi/Projects/typeless-local/assets/stopwords-en.txt`.

- [ ] **Step 3: Write the Chinese stopwords file**

Content (one term per line):

```
的
了
是
在
有
和
就
不
我
你
他
她
它
我们
你们
他们
这
那
这个
那个
什么
怎么
为什么
哪里
谁
吗
呢
吧
啊
嗯
哦
嗯嗯
然后
但是
所以
因为
如果
虽然
而且
或者
还
也
都
很
非常
比较
特别
真的
确实
应该
可能
也许
大概
当然
其实
就是
还是
只是
而是
还有
没有
不是
就是
对
错
好
坏
大
小
多
少
新
旧
高
低
快
慢
来
去
做
说
看
听
想
要
能
会
可以
应该
得
被
让
让我
让你
让他
比
跟
和
与
对
向
从
到
由
于
里
外
上
下
前
后
左
右
中
间
内
之
之中
之间
之前
之后
之上
之下
之内
之外
首先
其次
最后
另外
此外
而
则
即
其
该
这样
那样
怎样
如此
如下
如上
等等
等
之类
什么的
一些
一点
有点
多少
几
某
某个
任何
所有
全部
全都
全是
全部都
所有的
任何一个
每个
每一个
某一个
某些
其他
其它
别的
其余
另一
另一个
另外的
另外一个
那么
这么
为
为了
被
把
将
给
跟
和
与
同
及
以及
以
以上
以下
以及
以内
以外
以来
以前
以后
之类
之类的
等等
什么的
之类的
人
事
事情
东西
时候
时间
地方
情况
方面
样子
方式
方法
办法
原因
结果
问题
答案
影响
作用
关系
意思
意义
目的
目标
方向
位置
位置上
范围
程度
水平
能力
速度
效率
效果
质量
数量
价格
价值
重点
关键
特点
特征
特性
本质
内容
形式
结构
组成
部分
整体
系统
过程
阶段
步骤
环节
要点
要素
因素
条件
要求
标准
原则
规则
规定
制度
体系
政策
策略
计划
方案
设计
建议
意见
看法
观点
立场
态度
感觉
感受
心情
情绪
反应
表现
表示
表达
说明
解释
描述
介绍
报告
情况
信息
消息
新闻
故事
事件
情节
内容
主题
话题
对象
对方
双方
彼此
我们
你们
他们
她们
它们
咱们
人家
大家
谁
什么
哪
哪里
怎么
什么样
什么时候
为什么
多少
几
些
个
件
次
回
遍
下
两
三
四
五
六
七
八
九
十
百
千
万
零
半
点
分
秒
日
月
年
小时
分钟
今天
明天
昨天
现在
刚才
马上
立即
立刻
随时
随后
即将
即将到来
将来
未来
过去
以前
以后
之前
之后
当前
目前
现在
今后
此刻
此时
那时
当时
彼时
平时
平常
通常
往往
经常
常常
时常
偶尔
有时
有时候
有的时候
有时
时不时
总是
一直
始终
从来
从来不
从不
向来
一向
一贯
始终如一
持续
继续
不断
不停
连续
反复
重复
再次
重新
重来
再来
再说
再次说明
最近
近来
近期
最近一段时间
近一段时间
最近这段时间
近一段时间
最近一段时间内
```

Write that list to `/Users/alllllenshi/Projects/typeless-local/assets/stopwords-zh.txt`.

- [ ] **Step 4: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add assets/stopwords-en.txt assets/stopwords-zh.txt
git commit -m "Add bilingual stopword lists for hotword extraction"
```

**Acceptance:**
- Both files exist and are non-empty.
- `wc -l assets/stopwords-en.txt` ≥ 100; `wc -l assets/stopwords-zh.txt` ≥ 100.

---

### Task 2 — `typeless_local/vocab.py` 🟢 PARALLEL-A

**Files:**
- Create: `typeless_local/vocab.py`
- Test: `tests/test_vocab.py`

- [ ] **Step 1: Write the failing tests**

Create `/Users/alllllenshi/Projects/typeless-local/tests/test_vocab.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from typeless_local import vocab


def test_load_vocab_missing_file_returns_empty_list(tmp_path: Path) -> None:
    result = vocab.load_vocab(tmp_path / "missing.yaml")
    assert result == []


def test_load_vocab_combines_user_and_auto_with_user_first(tmp_path: Path) -> None:
    path = tmp_path / "vocab.yaml"
    path.write_text(
        "user:\n  - Jarvis\n  - Typeless\n"
        "auto:\n  - Hermes Aging\n  - PyObjC\n",
        encoding="utf-8",
    )
    result = vocab.load_vocab(path)
    assert result == ["Jarvis", "Typeless", "Hermes Aging", "PyObjC"]


def test_load_vocab_dedups_term_in_both_user_and_auto(tmp_path: Path) -> None:
    path = tmp_path / "vocab.yaml"
    path.write_text(
        "user:\n  - Jarvis\nauto:\n  - Jarvis\n  - Typeless\n",
        encoding="utf-8",
    )
    result = vocab.load_vocab(path)
    assert result == ["Jarvis", "Typeless"]


def test_load_vocab_malformed_yaml_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "vocab.yaml"
    path.write_text("not: valid: yaml: [", encoding="utf-8")
    result = vocab.load_vocab(path)
    assert result == []


def test_as_initial_prompt_empty_returns_empty_string() -> None:
    assert vocab.as_initial_prompt([]) == ""


def test_as_initial_prompt_renders_comma_separated() -> None:
    result = vocab.as_initial_prompt(["Jarvis", "Typeless"])
    assert result == "Common terms: Jarvis, Typeless."


def test_as_initial_prompt_truncates_at_term_boundary() -> None:
    terms = ["A" * 100 for _ in range(20)]
    out = vocab.as_initial_prompt(terms, max_chars=300)
    # Should fit under budget and end with '.'
    assert len(out) <= 300
    assert out.endswith(".")
    # First term must always be present.
    assert "A" * 100 in out


def test_save_auto_terms_preserves_user_section(tmp_path: Path) -> None:
    path = tmp_path / "vocab.yaml"
    path.write_text(
        "user:\n  - Jarvis\n  - Typeless\nauto:\n  - Old\n",
        encoding="utf-8",
    )
    vocab.save_auto_terms(path, ["NewTerm", "AnotherTerm"])
    loaded = vocab.load_vocab(path)
    assert loaded == ["Jarvis", "Typeless", "NewTerm", "AnotherTerm"]


def test_save_auto_terms_creates_file_if_missing(tmp_path: Path) -> None:
    path = tmp_path / "vocab.yaml"
    vocab.save_auto_terms(path, ["Term1"])
    loaded = vocab.load_vocab(path)
    assert loaded == ["Term1"]
```

- [ ] **Step 2: Run tests, expect ImportError**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_vocab.py -q
```

Expected: collection error (module `typeless_local.vocab` not found).

- [ ] **Step 3: Implement `typeless_local/vocab.py`**

Create `/Users/alllllenshi/Projects/typeless-local/typeless_local/vocab.py`:

```python
"""User-managed vocabulary store for Whisper hotwords and refine prompts."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import yaml

LOGGER = logging.getLogger(__name__)

_STARTER_HEADER = """# Typeless Local vocabulary.
# Edit `user:` freely — those terms are never overwritten.
# `auto:` is rewritten by `scripts/extract_hotwords.py`; don't hand-edit it.
"""


def _read_yaml(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        LOGGER.warning("Failed to read vocab at %s: %s", path, exc)
        return {}
    if not isinstance(loaded, dict):
        LOGGER.warning("Vocab at %s is not a mapping; ignoring", path)
        return {}
    return loaded


def _coerce_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                out.append(stripped)
    return out


def load_vocab(path: Path) -> list[str]:
    """Return deduplicated terms: user first, then auto. Missing/malformed → []."""

    path = Path(path)
    if not path.exists():
        return []
    data = _read_yaml(path)
    user_terms = _coerce_list(data.get("user"))
    auto_terms = _coerce_list(data.get("auto"))
    seen: set[str] = set()
    result: list[str] = []
    for term in user_terms + auto_terms:
        if term in seen:
            continue
        seen.add(term)
        result.append(term)
    return result


def as_initial_prompt(terms: list[str], max_chars: int = 600) -> str:
    """Render terms as a single-line Whisper initial prompt.

    Terms are joined comma-separated under a 'Common terms:' prefix. The
    output is truncated at term boundaries to stay under ``max_chars``. The
    first term is always preserved; subsequent terms are added until adding
    one more would exceed the budget.
    """

    if not terms:
        return ""
    prefix = "Common terms: "
    suffix = "."
    budget = max_chars - len(prefix) - len(suffix)
    kept: list[str] = []
    used = 0
    for term in terms:
        addition = (", " if kept else "") + term
        if kept and used + len(addition) > budget:
            break
        kept.append(term)
        used += len(addition)
    return prefix + ", ".join(kept) + suffix


def save_auto_terms(path: Path, terms: list[str]) -> None:
    """Atomically rewrite `auto:` section. Preserves `user:` section."""

    path = Path(path)
    if path.exists():
        data = _read_yaml(path)
        user_terms = _coerce_list(data.get("user"))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        user_terms = []

    payload = {
        "user": user_terms,
        "auto": [t for t in terms if t.strip()],
    }
    rendered = _STARTER_HEADER + yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )

    fd, tmp_name = tempfile.mkstemp(
        prefix=".vocab-", suffix=".yaml.tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def write_starter_file(path: Path) -> None:
    """Create a starter vocab.yaml with empty lists and a header comment."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    path.write_text(
        _STARTER_HEADER + "user: []\nauto: []\n",
        encoding="utf-8",
    )
```

- [ ] **Step 4: Run tests, expect green**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_vocab.py -q
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add typeless_local/vocab.py tests/test_vocab.py
git commit -m "Add vocab module: user/auto YAML store, Whisper initial-prompt rendering"
```

**Acceptance:**
- All 9 tests pass.
- File round-trip preserves `user:` section verbatim.

---

### Task 3 — `typeless_local/trace.py` 🟢 PARALLEL-A

**Files:**
- Create: `typeless_local/trace.py`
- Test: `tests/test_trace.py`

- [ ] **Step 1: Write failing tests**

Create `/Users/alllllenshi/Projects/typeless-local/tests/test_trace.py`:

```python
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from typeless_local.trace import DictationTrace, SessionRecord


def _make_record(**overrides) -> SessionRecord:
    now = time.time()
    base = SessionRecord(
        started_at=now,
        ended_at=now + 1.0,
        audio_duration_s=2.5,
        audio_rms=0.05,
        audio_sample_rate=16000,
        raw_asr_text="hello jarvis",
        raw_asr_language="en",
        raw_asr_confidence=0.85,
        refined_text="Hello, Jarvis.",
        focus_app="TextEdit",
        focus_window="Untitled",
        was_pasted=True,
        vocab_terms_used="Jarvis, Typeless",
        hotwords_count=2,
        latency_asr_ms=900,
        latency_refine_ms=1100,
        latency_total_ms=2100,
        asr_model="mlx-whisper:large-v3-turbo",
        refine_model="gpt-5.4-mini",
        app_version="0.2.0+abc1234",
        error=None,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_initial_log_creates_db_and_schema(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    trace.log(_make_record())
    assert db.exists()

    conn = sqlite3.connect(db)
    try:
        cur = conn.execute("PRAGMA user_version")
        assert cur.fetchone()[0] == 1
        cur = conn.execute("SELECT COUNT(*) FROM sessions")
        assert cur.fetchone()[0] == 1
    finally:
        conn.close()


def test_log_records_all_fields(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    record = _make_record(raw_asr_text="测试 jarvis", refined_text="测试 Jarvis")
    trace.log(record)

    conn = sqlite3.connect(db)
    try:
        cur = conn.execute(
            "SELECT raw_asr_text, refined_text, was_pasted, hotwords_count, error FROM sessions"
        )
        row = cur.fetchone()
        assert row == ("测试 jarvis", "测试 Jarvis", 1, 2, None)
    finally:
        conn.close()


def test_log_error_field(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    record = _make_record(error="dropped: low volume", refined_text="")
    trace.log(record)
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute("SELECT error FROM sessions")
        assert cur.fetchone()[0] == "dropped: low volume"
    finally:
        conn.close()


def test_log_does_not_raise_on_io_error(tmp_path: Path) -> None:
    # Point to a directory that doesn't exist *and* whose parent isn't writable.
    bad_path = tmp_path / "does-not-exist" / "trace.db"
    # We DO let DictationTrace try to create the parent dir on first use.
    # So craft a different failure: make the parent path a file.
    blocker = tmp_path / "trace.db"
    blocker.write_text("not a db", encoding="utf-8")
    nested = blocker / "trace.db"
    trace = DictationTrace(nested)
    trace.log(_make_record())   # MUST NOT raise
    # No assertions on file contents — the contract is: never raise.


def test_log_is_atomic_per_call(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    for i in range(5):
        trace.log(_make_record(raw_asr_text=f"row {i}"))
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM sessions")
        assert cur.fetchone()[0] == 5
    finally:
        conn.close()


def test_index_on_started_at_exists(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    trace.log(_make_record())
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_started_at'"
        )
        assert cur.fetchone() is not None
    finally:
        conn.close()
```

- [ ] **Step 2: Run tests, expect ImportError**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_trace.py -q
```

Expected: collection error.

- [ ] **Step 3: Implement `typeless_local/trace.py`**

Create `/Users/alllllenshi/Projects/typeless-local/typeless_local/trace.py`:

```python
"""SQLite-backed per-session trace for typeless-local."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import sqlite3
from pathlib import Path

LOGGER = logging.getLogger(__name__)

SCHEMA_SQL = """
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
  was_pasted INTEGER,
  vocab_terms_used TEXT,
  hotwords_count INTEGER,
  latency_asr_ms INTEGER,
  latency_refine_ms INTEGER,
  latency_total_ms INTEGER,
  asr_model TEXT,
  refine_model TEXT,
  app_version TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_started_at ON sessions(started_at);
"""

SCHEMA_VERSION = 1


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


_INSERT_SQL = """
INSERT INTO sessions (
  started_at, ended_at, audio_duration_s, audio_rms, audio_sample_rate,
  raw_asr_text, raw_asr_language, raw_asr_confidence,
  refined_text, focus_app, focus_window, was_pasted,
  vocab_terms_used, hotwords_count,
  latency_asr_ms, latency_refine_ms, latency_total_ms,
  asr_model, refine_model, app_version, error
) VALUES (
  :started_at, :ended_at, :audio_duration_s, :audio_rms, :audio_sample_rate,
  :raw_asr_text, :raw_asr_language, :raw_asr_confidence,
  :refined_text, :focus_app, :focus_window, :was_pasted,
  :vocab_terms_used, :hotwords_count,
  :latency_asr_ms, :latency_refine_ms, :latency_total_ms,
  :asr_model, :refine_model, :app_version, :error
)
"""


class DictationTrace:
    """Append-only per-session log. Never raises from ``log()``."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._initialized = False

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        try:
            conn.executescript(SCHEMA_SQL)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.execute("PRAGMA journal_mode = WAL")
        finally:
            conn.close()
        self._initialized = True

    def log(self, record: SessionRecord) -> None:
        try:
            self._ensure_schema()
            params = {
                **record.__dict__,
                "was_pasted": 1 if record.was_pasted else 0,
            }
            conn = sqlite3.connect(str(self.db_path), isolation_level=None)
            try:
                conn.execute(_INSERT_SQL, params)
            finally:
                conn.close()
        except Exception:
            LOGGER.warning(
                "Trace log failed for session started_at=%s",
                getattr(record, "started_at", "?"),
                exc_info=True,
            )

    def close(self) -> None:  # no-op; connections are per-call
        return None
```

- [ ] **Step 4: Run tests, expect green**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_trace.py -q
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add typeless_local/trace.py tests/test_trace.py
git commit -m "Add SQLite trace module: per-session record, WAL, atomic per-call connection"
```

**Acceptance:**
- All 6 tests pass.
- Bad paths never raise.
- Schema v1, WAL mode set.

---

### Task 4 — `typeless_local/menubar.py` 🟢 PARALLEL-A

**Files:**
- Create: `typeless_local/menubar.py`
- Test: `tests/test_menubar.py`

- [ ] **Step 1: Write failing tests**

Create `/Users/alllllenshi/Projects/typeless-local/tests/test_menubar.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

from typeless_local.menubar import MenuBarIcon, STATE_TO_SYMBOL


def test_state_to_symbol_covers_all_states() -> None:
    for state in ("idle", "starting", "recording", "processing", "error"):
        assert state in STATE_TO_SYMBOL


def test_set_state_updates_tracked_state() -> None:
    icon = MenuBarIcon(on_reload_vocab=MagicMock(), on_quit=MagicMock())
    icon.set_state("recording")
    assert icon.current_state == "recording"
    icon.set_state("idle")
    assert icon.current_state == "idle"


def test_set_state_unknown_state_is_clamped_to_idle() -> None:
    icon = MenuBarIcon(on_reload_vocab=MagicMock(), on_quit=MagicMock())
    icon.set_state("nonsense")  # type: ignore[arg-type]
    assert icon.current_state == "idle"


def test_reload_callback_invoked_via_action() -> None:
    on_reload = MagicMock()
    icon = MenuBarIcon(on_reload_vocab=on_reload, on_quit=MagicMock())
    icon._on_reload_action(None)
    on_reload.assert_called_once()


def test_quit_callback_invoked_via_action() -> None:
    on_quit = MagicMock()
    icon = MenuBarIcon(on_reload_vocab=MagicMock(), on_quit=on_quit)
    icon._on_quit_action(None)
    on_quit.assert_called_once()
```

- [ ] **Step 2: Run tests, expect ImportError**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_menubar.py -q
```

Expected: collection error.

- [ ] **Step 3: Implement `typeless_local/menubar.py`**

Create `/Users/alllllenshi/Projects/typeless-local/typeless_local/menubar.py`:

```python
"""macOS menu-bar status indicator for typeless-local."""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path
from typing import Callable, Literal

LOGGER = logging.getLogger(__name__)

State = Literal["idle", "starting", "recording", "processing", "error"]

STATE_TO_SYMBOL: dict[str, str] = {
    "idle": "mic",
    "starting": "mic",
    "recording": "record.circle.fill",
    "processing": "ellipsis.circle",
    "error": "exclamationmark.triangle.fill",
}

STATE_TO_LABEL: dict[str, str] = {
    "idle": "Ready",
    "starting": "Starting…",
    "recording": "Recording",
    "processing": "Thinking…",
    "error": "Error",
}

_DEFAULT_TRACE_FOLDER = Path.home() / ".typeless-local"
_DEFAULT_LOG_PATH = _DEFAULT_TRACE_FOLDER / "app.log"


class MenuBarIcon:
    """NSStatusItem wrapper; thread-safe ``set_state`` via callAfter."""

    def __init__(
        self,
        on_reload_vocab: Callable[[], None],
        on_quit: Callable[[], None],
        trace_folder: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._on_reload_vocab = on_reload_vocab
        self._on_quit = on_quit
        self._trace_folder = trace_folder or _DEFAULT_TRACE_FOLDER
        self._log_path = log_path or _DEFAULT_LOG_PATH
        self.current_state: State = "idle"
        self._status_item = None
        self._status_label_item = None
        self._lock = threading.Lock()

    def setup(self) -> None:
        """Create the NSStatusItem. Must run on the main thread."""

        from AppKit import (
            NSImage,
            NSImageSymbolConfiguration,
            NSMenu,
            NSMenuItem,
            NSStatusBar,
            NSColor,
        )

        bar = NSStatusBar.systemStatusBar()
        item = bar.statusItemWithLength_(-1)  # NSVariableStatusItemLength
        button = item.button()
        button.setImagePosition_(2)  # NSImageOnly

        menu = NSMenu.alloc().init()

        label = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"Typeless Local — {STATE_TO_LABEL['idle']}", None, ""
        )
        label.setEnabled_(False)
        self._status_label_item = label
        menu.addItem_(label)
        menu.addItem_(NSMenuItem.separatorItem())

        reload_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Reload Vocab", "reloadVocabAction:", "r"
        )
        reload_item.setTarget_(_make_action_target(self._on_reload_action))
        menu.addItem_(reload_item)
        menu.addItem_(NSMenuItem.separatorItem())

        open_trace = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open Trace Folder", "openTraceAction:", ""
        )
        open_trace.setTarget_(_make_action_target(self._on_open_trace_action))
        menu.addItem_(open_trace)

        show_log = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Show Log", "showLogAction:", ""
        )
        show_log.setTarget_(_make_action_target(self._on_show_log_action))
        menu.addItem_(show_log)
        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "quitAction:", "q"
        )
        quit_item.setTarget_(_make_action_target(self._on_quit_action))
        menu.addItem_(quit_item)

        item.setMenu_(menu)
        self._status_item = item
        self._apply_state(self.current_state)

    def set_state(self, state: State) -> None:
        """Thread-safe state update; clamps unknown states to 'idle'."""

        with self._lock:
            if state not in STATE_TO_SYMBOL:
                state = "idle"
            self.current_state = state
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._apply_state, self.current_state)
        except Exception:
            LOGGER.debug("set_state called without AppKit available", exc_info=True)

    def _apply_state(self, state: State) -> None:
        if self._status_item is None:
            return
        try:
            from AppKit import NSImage, NSImageSymbolConfiguration, NSColor

            symbol = STATE_TO_SYMBOL.get(state, "mic")
            image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                symbol, f"Typeless Local {state}"
            )
            if image is not None:
                tint = _state_color(state)
                image.setTemplate_(False)
                config = NSImageSymbolConfiguration.configurationWithHierarchicalColor_(tint)
                tinted = image.imageWithSymbolConfiguration_(config)
                self._status_item.button().setImage_(tinted or image)
            if self._status_label_item is not None:
                self._status_label_item.setTitle_(
                    f"Typeless Local — {STATE_TO_LABEL.get(state, state)}"
                )
        except Exception:
            LOGGER.debug("_apply_state failed", exc_info=True)

    def _on_reload_action(self, sender) -> None:
        try:
            self._on_reload_vocab()
        except Exception:
            LOGGER.warning("Reload-vocab callback failed", exc_info=True)

    def _on_quit_action(self, sender) -> None:
        try:
            self._on_quit()
        except Exception:
            LOGGER.warning("Quit callback failed", exc_info=True)

    def _on_open_trace_action(self, sender) -> None:
        try:
            self._trace_folder.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["open", str(self._trace_folder)])
        except Exception:
            LOGGER.warning("Open trace folder failed", exc_info=True)

    def _on_show_log_action(self, sender) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            if not self._log_path.exists():
                self._log_path.touch()
            subprocess.Popen(["open", str(self._log_path)])
        except Exception:
            LOGGER.warning("Show log failed", exc_info=True)


def _state_color(state: str):
    from AppKit import NSColor

    if state == "recording" or state == "error":
        return NSColor.systemRedColor()
    if state == "starting" or state == "processing":
        return NSColor.systemYellowColor()
    return NSColor.systemGrayColor()


def _make_action_target(handler: Callable):
    """Wrap a Python callable as an NSObject that responds to ObjC selectors.

    The menu items above use selectors like ``reloadVocabAction:`` etc., so
    we generate a class with those exact selector names. Each selector dispatches
    to the corresponding Python handler.
    """

    from objc import python_method
    from Foundation import NSObject

    class _ActionTarget(NSObject):
        def initWithHandler_(self, h):
            self = NSObject.init(self)
            if self is None:
                return None
            self._handler = h
            return self

        def reloadVocabAction_(self, sender):
            self._handler(sender)

        def quitAction_(self, sender):
            self._handler(sender)

        def openTraceAction_(self, sender):
            self._handler(sender)

        def showLogAction_(self, sender):
            self._handler(sender)

    target = _ActionTarget.alloc().initWithHandler_(handler)
    # Keep a strong reference; ObjC retains weakly here.
    _ACTION_TARGETS.append(target)
    return target


_ACTION_TARGETS: list = []
```

- [ ] **Step 4: Run tests, expect green**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_menubar.py -q
```

Expected: 5 passed. (Tests only exercise pure-Python paths; AppKit calls happen inside `setup()` which isn't tested headlessly.)

- [ ] **Step 5: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add typeless_local/menubar.py tests/test_menubar.py
git commit -m "Add menubar status indicator: SF Symbol per state, callback wiring"
```

**Acceptance:**
- All 5 tests pass.
- `setup()` is callable on main thread (verified during integration smoke later).

---

### Task 5 — `assets/config.yaml` minimal default 🟢 PARALLEL-A

**Files:**
- Create: `assets/config.yaml`

- [ ] **Step 1: Read the existing Jarvis config for reference**

```bash
cat /Users/alllllenshi/Projects/jarvis/config.yaml | head -80
```

Note the keys under `asr:` and `audio:` and any `llm:` keys typeless-local uses (see `typeless_local/config.py`).

- [ ] **Step 2: Write a minimal config.yaml that contains only typeless-local-required keys**

Create `/Users/alllllenshi/Projects/typeless-local/assets/config.yaml`:

```yaml
# Minimal config shipped inside the .app bundle.
# Override by writing ~/.typeless-local/config.yaml.

asr:
  provider: mlx_whisper
  mlx_whisper_model: mlx-community/whisper-large-v3-turbo
  mlx_whisper_initial_prompt: ""
  language: ""
  sensevoice_model_dir: ""   # unused but speech_recognizer reads it

audio:
  vad_model_path: ""         # unused but speech_recognizer may read it
  min_duration: 0.25
  low_volume_threshold: 0.02

llm:
  default_preset: fast
  presets:
    fast:
      model: gpt-5.4-mini
      base_url: https://api.openai.com/v1
      api_key_env: OPENAI_API_KEY
      max_tokens: 512
```

- [ ] **Step 3: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add assets/config.yaml
git commit -m "Add bundled default config.yaml for self-contained app"
```

**Acceptance:**
- File contains all keys typeless-local's `config.py` reads.

---

## Phase A — Library code (Batch 2: 🟡 PARALLEL-B, depends on Batch 1)

### Task 6 — `typeless_local/refine.py` accepts vocab 🟡 PARALLEL-B

**Files:**
- Modify: `typeless_local/refine.py`
- Modify: `tests/test_refine.py`

- [ ] **Step 1: Add failing tests for vocab-aware refine**

Append to `/Users/alllllenshi/Projects/typeless-local/tests/test_refine.py`:

```python
def test_refiner_appends_vocab_section_when_provided() -> None:
    fake = _FakeClient()
    refiner = TextRefiner(
        RefineConfig("gpt-5.4-mini", "https://api.openai.com/v1", "OPENAI_API_KEY", 128),
        client=fake,
    )

    refiner.refine(
        "tell jarvas to start",
        FocusContext(app_name="Slack", window_title="#general"),
        vocab=["Jarvis", "Typeless"],
    )

    system_prompt = fake.completions.kwargs["messages"][0]["content"]
    assert "User vocabulary" in system_prompt
    assert "Jarvis, Typeless" in system_prompt
    assert "only correct fragments" in system_prompt


def test_refiner_omits_vocab_section_when_empty() -> None:
    fake = _FakeClient()
    refiner = TextRefiner(
        RefineConfig("gpt-5.4-mini", "https://api.openai.com/v1", "OPENAI_API_KEY", 128),
        client=fake,
    )

    refiner.refine("hello world", vocab=[])

    system_prompt = fake.completions.kwargs["messages"][0]["content"]
    assert "User vocabulary" not in system_prompt


def test_refiner_omits_vocab_section_when_none() -> None:
    fake = _FakeClient()
    refiner = TextRefiner(
        RefineConfig("gpt-5.4-mini", "https://api.openai.com/v1", "OPENAI_API_KEY", 128),
        client=fake,
    )

    refiner.refine("hello world")

    system_prompt = fake.completions.kwargs["messages"][0]["content"]
    assert "User vocabulary" not in system_prompt
```

- [ ] **Step 2: Run tests, expect 3 new failures**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_refine.py -q
```

Expected: 3 failed (the new tests), 2 passed.

- [ ] **Step 3: Implement vocab support in `refine.py`**

In `/Users/alllllenshi/Projects/typeless-local/typeless_local/refine.py`, replace the `refine` method:

```python
    def refine(
        self,
        raw_text: str,
        context: FocusContext | None = None,
        vocab: list[str] | None = None,
    ) -> RefineResult:
        """Refine raw ASR text into insertable dictation text."""

        stripped = raw_text.strip()
        if not stripped:
            return RefineResult(text="", raw_text=raw_text, model=self.config.model)

        focus = context or FocusContext(app_name="", window_title="", selected_text="")
        user_prompt = (
            "Raw transcript:\n"
            f"{stripped}\n\n"
            "Focused app context:\n"
            f"- app: {focus.app_name or 'unknown'}\n"
            f"- window: {focus.window_title or 'unknown'}\n"
            f"- selected text: {focus.selected_text or '(none)'}\n"
        )
        system_prompt = SYSTEM_PROMPT
        if vocab:
            joined = ", ".join(vocab)
            system_prompt = (
                SYSTEM_PROMPT
                + "\n\nUser vocabulary (high-confidence terms used frequently by this user):\n"
                + joined
                + "\n\n"
                "Where the raw transcript contains short fragments that are plausibly "
                "mishears of these specific terms (homophones, fuzzy phonetic matches), "
                "replace them with the correct term. Do not invent occurrences — only "
                "correct fragments that already seem to be attempts at one of these terms.\n"
            )
        token_key = "max_completion_tokens" if self.config.model.startswith("gpt-5") else "max_tokens"
        kwargs = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            token_key: self.config.max_tokens,
        }
        if self.config.model.startswith("gpt-5.4") and (
            not self.config.base_url or "api.openai.com" in self.config.base_url
        ):
            kwargs["prompt_cache_retention"] = "24h"

        LOGGER.info("Refining transcript with %s", self.config.model)
        response = self._get_client().chat.completions.create(**kwargs)
        text = str(response.choices[0].message.content or "").strip()
        return RefineResult(text=text, raw_text=raw_text, model=self.config.model)
```

- [ ] **Step 4: Run tests, expect green**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_refine.py -q
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add typeless_local/refine.py tests/test_refine.py
git commit -m "refine: accept vocab list, append 'correct mishears' instruction when non-empty"
```

**Acceptance:**
- All 5 tests pass.
- Empty/None vocab → system prompt unchanged.

---

### Task 7 — `typeless_local/asr.py` accepts initial_prompt 🟡 PARALLEL-B

**Files:**
- Modify: `typeless_local/asr.py`
- Test: `tests/test_asr.py` (new)

- [ ] **Step 1: Inspect Jarvis SpeechRecognizer signature**

```bash
grep -n "def transcribe\|def __init__\|mlx_whisper_initial_prompt" /Users/alllllenshi/Projects/jarvis/core/speech_recognizer.py | head -40
```

Note whether `transcribe` accepts per-call `initial_prompt`.

- [ ] **Step 2: Write failing test for per-call initial_prompt**

Create `/Users/alllllenshi/Projects/typeless-local/tests/test_asr.py`:

```python
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

import typeless_local.asr as asr_module


def test_transcribe_passes_initial_prompt_through(monkeypatch, tmp_path: Path) -> None:
    captured: dict = {}

    class FakeRecognizer:
        def __init__(self, config):
            self._config = dict(config)
            self.provider = "fake"

        def transcribe(self, audio, **kwargs):
            captured["initial_prompt"] = kwargs.get(
                "initial_prompt",
                self._config.get("asr", {}).get("mlx_whisper_initial_prompt"),
            )
            return SimpleNamespace(text="hello", language="en", confidence=0.9)

    import sys

    fake_module = SimpleNamespace(SpeechRecognizer=FakeRecognizer)
    fake_pkg = SimpleNamespace(speech_recognizer=fake_module)
    monkeypatch.setitem(sys.modules, "core", fake_pkg)
    monkeypatch.setitem(sys.modules, "core.speech_recognizer", fake_module)

    j = asr_module.JarvisASR(tmp_path, {"asr": {"provider": "fake"}})
    audio = np.zeros(16000, dtype=np.float32)
    j.transcribe(audio, initial_prompt="Common terms: Jarvis, Typeless.")

    # The wrapper must either pass per-call OR mutate config; check both possible paths
    assert captured["initial_prompt"] == "Common terms: Jarvis, Typeless." or \
           j._recognizer._config["asr"]["mlx_whisper_initial_prompt"] == "Common terms: Jarvis, Typeless."


def test_transcribe_strips_prompt_echo_from_short_outputs(monkeypatch, tmp_path: Path) -> None:
    class FakeRecognizer:
        def __init__(self, config):
            self._config = dict(config)
            self.provider = "fake"

        def transcribe(self, audio, **kwargs):
            return SimpleNamespace(
                text="Common terms: Jarvis, Typeless.\nhello",
                language="en",
                confidence=0.9,
            )

    import sys

    fake_module = SimpleNamespace(SpeechRecognizer=FakeRecognizer)
    fake_pkg = SimpleNamespace(speech_recognizer=fake_module)
    monkeypatch.setitem(sys.modules, "core", fake_pkg)
    monkeypatch.setitem(sys.modules, "core.speech_recognizer", fake_module)

    j = asr_module.JarvisASR(tmp_path, {"asr": {"provider": "fake"}})
    audio = np.zeros(16000, dtype=np.float32)
    result = j.transcribe(audio, initial_prompt="Common terms: Jarvis, Typeless.")

    assert result.text == "hello"
```

- [ ] **Step 3: Run tests, expect failure**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_asr.py -q
```

Expected: 2 failed (current code ignores `initial_prompt` kwarg).

- [ ] **Step 4: Implement initial_prompt support in `asr.py`**

Replace `/Users/alllllenshi/Projects/typeless-local/typeless_local/asr.py` with:

```python
"""Jarvis ASR adapter used by the standalone app."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import logging
import re
import sys
from pathlib import Path

import numpy as np

LOGGER = logging.getLogger(__name__)

_PROMPT_ECHO_RE = re.compile(r"^\s*Common terms:[^\n]*\n", re.IGNORECASE)


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    confidence: float


class JarvisASR:
    """Thin adapter around Jarvis' existing SpeechRecognizer."""

    def __init__(self, jarvis_root: Path, config: dict) -> None:
        self.jarvis_root = jarvis_root
        if jarvis_root and str(jarvis_root) not in sys.path:
            sys.path.insert(0, str(jarvis_root))

        from core.speech_recognizer import SpeechRecognizer

        self._recognizer = SpeechRecognizer(config)
        self._accepts_per_call_prompt = self._detect_per_call_prompt()
        LOGGER.info(
            "ASR provider: %s (per-call prompt: %s)",
            self._recognizer.provider,
            self._accepts_per_call_prompt,
        )

    @property
    def model_name(self) -> str:
        cfg = getattr(self._recognizer, "_config", None) or {}
        asr_cfg = cfg.get("asr", {}) if isinstance(cfg, dict) else {}
        provider = getattr(self._recognizer, "provider", "unknown")
        model = asr_cfg.get(f"{provider}_model") or asr_cfg.get("model") or ""
        return f"{provider}:{model}" if model else str(provider)

    def _detect_per_call_prompt(self) -> bool:
        try:
            sig = inspect.signature(self._recognizer.transcribe)
            return "initial_prompt" in sig.parameters
        except (TypeError, ValueError):
            return False

    def transcribe(
        self,
        audio: np.ndarray,
        initial_prompt: str | None = None,
    ) -> Transcript:
        """Transcribe mono float32 audio with an optional Whisper initial prompt."""

        prior_prompt = None
        if initial_prompt is not None:
            if self._accepts_per_call_prompt:
                result = self._recognizer.transcribe(audio, initial_prompt=initial_prompt)
            else:
                cfg = getattr(self._recognizer, "_config", None)
                if isinstance(cfg, dict):
                    cfg.setdefault("asr", {})
                    prior_prompt = cfg["asr"].get("mlx_whisper_initial_prompt")
                    cfg["asr"]["mlx_whisper_initial_prompt"] = initial_prompt
                try:
                    result = self._recognizer.transcribe(audio)
                finally:
                    if isinstance(cfg, dict) and prior_prompt is not None:
                        cfg["asr"]["mlx_whisper_initial_prompt"] = prior_prompt
        else:
            result = self._recognizer.transcribe(audio)

        text = str(getattr(result, "text", "") or "")
        if initial_prompt:
            text = _PROMPT_ECHO_RE.sub("", text, count=1)
        return Transcript(
            text=text.strip(),
            language=str(getattr(result, "language", "") or "unknown"),
            confidence=float(getattr(result, "confidence", 0.0) or 0.0),
        )
```

- [ ] **Step 5: Run tests, expect green**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_asr.py -q
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add typeless_local/asr.py tests/test_asr.py
git commit -m "asr: accept per-call initial_prompt; strip prompt echo from output"
```

**Acceptance:**
- Both tests pass.
- Backward-compatible (`transcribe(audio)` still works).

---

### Task 8 — `scripts/extract_hotwords.py` 🟡 PARALLEL-B

**Files:**
- Create: `scripts/extract_hotwords.py`
- Test: `tests/test_extract_hotwords.py`

- [ ] **Step 1: Write failing tests**

Create `/Users/alllllenshi/Projects/typeless-local/tests/test_extract_hotwords.py`:

```python
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from scripts.extract_hotwords import (
    extract_candidates,
    tokenize,
    load_stopwords,
    run,
)
from typeless_local.trace import DictationTrace, SessionRecord


def test_tokenize_english() -> None:
    tokens = tokenize("Hello Jarvis, this is mlx-whisper running.")
    assert "Jarvis" in tokens
    assert "mlx-whisper" in tokens
    assert "Hello" in tokens
    assert "is" in tokens  # too short, but tokenize is dumb; filtering removes it


def test_tokenize_chinese() -> None:
    tokens = tokenize("启动贾维斯的语音模块")
    assert "贾维斯" in tokens or "维斯" in tokens or "贾维" in tokens


def test_extract_candidates_finds_added_terms(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    now = time.time()
    for _ in range(3):
        trace.log(SessionRecord(
            started_at=now, ended_at=now + 1,
            raw_asr_text="tell jarvas to start",
            refined_text="Tell Jarvis to start",
        ))

    candidates = extract_candidates(
        db_path=db, days=30, min_count=2,
        user_terms=set(), stopwords=set(),
    )
    counts = dict(candidates)
    assert counts.get("Jarvis", 0) >= 2


def test_extract_candidates_filters_stopwords(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    now = time.time()
    trace.log(SessionRecord(
        started_at=now, ended_at=now + 1,
        raw_asr_text="hi", refined_text="The Jarvis the Jarvis",
    ))
    candidates = extract_candidates(
        db_path=db, days=30, min_count=1,
        user_terms=set(), stopwords={"the", "a"},
    )
    terms = [t for t, _c in candidates]
    assert "the" not in terms
    assert "The" not in terms


def test_extract_candidates_skips_user_terms_case_insensitive(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    now = time.time()
    trace.log(SessionRecord(
        started_at=now, ended_at=now + 1,
        raw_asr_text="", refined_text="Jarvis is great",
    ))
    candidates = extract_candidates(
        db_path=db, days=30, min_count=1,
        user_terms={"jarvis"}, stopwords=set(),
    )
    terms = [t for t, _c in candidates]
    assert "Jarvis" not in terms


def test_run_dry_run_does_not_write(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "trace.db"
    vocab_path = tmp_path / "vocab.yaml"
    stopwords_dir = tmp_path / "stops"
    stopwords_dir.mkdir()
    (stopwords_dir / "stopwords-en.txt").write_text("the\nand\n", encoding="utf-8")
    (stopwords_dir / "stopwords-zh.txt").write_text("的\n了\n", encoding="utf-8")

    trace = DictationTrace(db)
    now = time.time()
    trace.log(SessionRecord(
        started_at=now, ended_at=now + 1,
        raw_asr_text="hello", refined_text="Hello Jarvis Jarvis",
    ))

    run(
        db_path=db, vocab_path=vocab_path, stopwords_dir=stopwords_dir,
        days=30, min_count=2, top_k=10, dry_run=True,
    )
    assert not vocab_path.exists()


def test_run_writes_auto_section(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    vocab_path = tmp_path / "vocab.yaml"
    stopwords_dir = tmp_path / "stops"
    stopwords_dir.mkdir()
    (stopwords_dir / "stopwords-en.txt").write_text("the\n", encoding="utf-8")
    (stopwords_dir / "stopwords-zh.txt").write_text("的\n", encoding="utf-8")

    trace = DictationTrace(db)
    now = time.time()
    for _ in range(3):
        trace.log(SessionRecord(
            started_at=now, ended_at=now + 1,
            raw_asr_text="tell jarvas", refined_text="Tell Jarvis to go",
        ))

    run(
        db_path=db, vocab_path=vocab_path, stopwords_dir=stopwords_dir,
        days=30, min_count=2, top_k=10, dry_run=False,
    )
    from typeless_local.vocab import load_vocab
    terms = load_vocab(vocab_path)
    assert "Jarvis" in terms
```

- [ ] **Step 2: Run tests, expect ImportError**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_extract_hotwords.py -q
```

Expected: collection error (scripts/extract_hotwords missing).

- [ ] **Step 3: Implement `scripts/extract_hotwords.py`**

Create `/Users/alllllenshi/Projects/typeless-local/scripts/__init__.py` if missing:

```bash
touch /Users/alllllenshi/Projects/typeless-local/scripts/__init__.py
```

Create `/Users/alllllenshi/Projects/typeless-local/scripts/extract_hotwords.py`:

```python
"""Mine the trace DB for likely-hotword candidates and write them to vocab.yaml."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

# Allow running as both `python scripts/extract_hotwords.py` and `python -m scripts.extract_hotwords`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typeless_local.vocab import load_vocab, save_auto_terms  # noqa: E402

_EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9-]{1,}")
_ZH_TOKEN = re.compile(r"[一-鿿]{2,4}")


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    out.extend(_EN_TOKEN.findall(text))
    out.extend(_ZH_TOKEN.findall(text))
    return out


def load_stopwords(stopwords_dir: Path) -> set[str]:
    stops: set[str] = set()
    for name in ("stopwords-en.txt", "stopwords-zh.txt"):
        p = stopwords_dir / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            t = line.strip()
            if t:
                stops.add(t)
    return stops


def extract_candidates(
    db_path: Path,
    days: int,
    min_count: int,
    user_terms: set[str],
    stopwords: set[str],
) -> list[tuple[str, int]]:
    cutoff = time.time() - days * 86400.0
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT raw_asr_text, refined_text FROM sessions WHERE started_at >= ?",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    user_lower = {t.lower() for t in user_terms}
    stops_lower = {t.lower() for t in stopwords}
    counter: Counter[str] = Counter()
    for raw, refined in rows:
        raw_tokens = set(tokenize(raw or ""))
        ref_tokens = tokenize(refined or "")
        added = [t for t in ref_tokens if t not in raw_tokens]
        for t in added:
            if len(t) < 2:
                continue
            if t.lower() in user_lower:
                continue
            if t.lower() in stops_lower:
                continue
            counter[t] += 1

    return [(t, c) for t, c in counter.most_common() if c >= min_count]


def run(
    db_path: Path,
    vocab_path: Path,
    stopwords_dir: Path,
    days: int,
    min_count: int,
    top_k: int,
    dry_run: bool,
) -> None:
    existing = load_vocab(vocab_path)
    candidates = extract_candidates(
        db_path=db_path,
        days=days,
        min_count=min_count,
        user_terms=set(existing),
        stopwords=load_stopwords(stopwords_dir),
    )
    top = [t for t, _c in candidates[:top_k]]

    print(f"sessions scanned (last {days}d), candidates kept: {len(top)}")
    for t, c in candidates[:top_k]:
        print(f"  {c:4d}  {t}")

    if dry_run:
        print("dry-run: not writing vocab.yaml")
        return
    save_auto_terms(vocab_path, top)
    print(f"updated {vocab_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract auto-hotwords from trace.db")
    home_dir = Path.home() / ".typeless-local"
    repo_root = Path(__file__).resolve().parent.parent
    parser.add_argument("--db", type=Path, default=home_dir / "trace.db")
    parser.add_argument("--vocab", type=Path, default=home_dir / "vocab.yaml")
    parser.add_argument("--stopwords-dir", type=Path, default=repo_root / "assets")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--min-count", type=int, default=2)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"trace db not found: {args.db}", file=sys.stderr)
        return 2

    run(
        db_path=args.db,
        vocab_path=args.vocab,
        stopwords_dir=args.stopwords_dir,
        days=args.days,
        min_count=args.min_count,
        top_k=args.top_k,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests, expect green**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_extract_hotwords.py -q
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add scripts/__init__.py scripts/extract_hotwords.py tests/test_extract_hotwords.py
git commit -m "Add extract_hotwords CLI: mine trace diffs for auto-vocab candidates"
```

**Acceptance:**
- All 6 tests pass.
- Dry-run never writes files.

---

### Task 9 — `typeless_local/config.py` adds new paths 🟡 PARALLEL-B

**Files:**
- Modify: `typeless_local/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Add failing test for new fields**

Append to `/Users/alllllenshi/Projects/typeless-local/tests/test_config.py`:

```python
def test_config_resolves_user_paths(monkeypatch, tmp_path):
    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = cfg_mod.resolve_user_paths()
    assert paths.vocab_path == tmp_path / ".typeless-local" / "vocab.yaml"
    assert paths.trace_db_path == tmp_path / ".typeless-local" / "trace.db"
    assert paths.log_path == tmp_path / ".typeless-local" / "app.log"
    assert paths.stopwords_dir.name == "assets"


def test_resolve_user_paths_creates_directory(monkeypatch, tmp_path):
    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_mod.resolve_user_paths()
    assert (tmp_path / ".typeless-local").is_dir()
```

- [ ] **Step 2: Run tests, expect 2 failures**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_config.py -q
```

Expected: 2 failed (resolve_user_paths missing).

- [ ] **Step 3: Implement `resolve_user_paths`**

Append to `/Users/alllllenshi/Projects/typeless-local/typeless_local/config.py`:

```python
@dataclass(frozen=True)
class UserPaths:
    """Filesystem paths typeless-local writes to at runtime."""

    config_dir: Path
    vocab_path: Path
    trace_db_path: Path
    log_path: Path
    stopwords_dir: Path
    user_config_path: Path


def resolve_user_paths(app_root: Path | None = None) -> UserPaths:
    """Return all on-disk paths typeless-local touches outside its install."""

    home = Path(os.environ.get("HOME") or Path.home()).expanduser()
    config_dir = home / ".typeless-local"
    config_dir.mkdir(parents=True, exist_ok=True)
    root = app_root or resolve_app_root()

    # stopwords dir: prefer bundled Resources/, fall back to repo assets/
    bundled = root.parent / "Resources"  # py2app layout: .app/Contents/Resources
    stopwords_dir = bundled if (bundled / "stopwords-en.txt").exists() else (root / "assets")

    return UserPaths(
        config_dir=config_dir,
        vocab_path=config_dir / "vocab.yaml",
        trace_db_path=config_dir / "trace.db",
        log_path=config_dir / "app.log",
        stopwords_dir=stopwords_dir,
        user_config_path=config_dir / "config.yaml",
    )
```

Also extend `AppConfig` (the existing dataclass) by adding three frozen fields and populate them in `load_config()`:

Replace the AppConfig dataclass:

```python
@dataclass(frozen=True)
class AppConfig:
    """Resolved runtime configuration."""

    root: Path
    jarvis_root: Path
    jarvis_config: dict[str, Any]
    refine: RefineConfig
    sample_rate: int = 16000
    max_recording_seconds: float = 540.0
    min_recording_seconds: float = 0.25
    low_volume_threshold: float = 0.02
    debug_hotkey: bool = False
    user_paths: UserPaths | None = None
```

In `load_config()`, set `user_paths=resolve_user_paths(app_root)` and return.

- [ ] **Step 4: Run tests, expect green**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_config.py -q
```

Expected: previous passes + 2 new = green.

- [ ] **Step 5: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add typeless_local/config.py tests/test_config.py
git commit -m "config: add UserPaths (vocab.yaml / trace.db / app.log / stopwords) resolution"
```

**Acceptance:**
- All config tests pass.
- `~/.typeless-local/` is created on first load_config.

---

## Phase A — App wiring (🔴 SERIAL, depends on Batch 2)

### Task 10 — `_version.py` baked-version support 🔴 SERIAL

**Files:**
- Create: `typeless_local/_version.py` (dev placeholder)
- Modify: `typeless_local/__init__.py`

- [ ] **Step 1: Add a placeholder _version.py committed to repo**

Create `/Users/alllllenshi/Projects/typeless-local/typeless_local/_version.py`:

```python
"""Build-time version marker. Overwritten by scripts/build_app.py."""

VERSION = "0.2.0-dev"
```

- [ ] **Step 2: Expose `app_version()` from package**

Modify `/Users/alllllenshi/Projects/typeless-local/typeless_local/__init__.py` to include:

```python
"""Typeless Local — standalone macOS dictation app."""

from __future__ import annotations

import subprocess
from pathlib import Path


def app_version() -> str:
    """Return the running build's version string.

    Resolution order:
    1. ``typeless_local._version.VERSION`` baked by the build script.
    2. ``git rev-parse --short HEAD`` from the repo (dev mode).
    3. ``"unknown"``.
    """

    try:
        from typeless_local._version import VERSION

        if VERSION:
            return str(VERSION)
    except Exception:
        pass
    try:
        repo = Path(__file__).resolve().parent.parent
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo, text=True, timeout=2
        ).strip()
        if out:
            return f"0.2.0+{out}"
    except Exception:
        pass
    return "unknown"
```

- [ ] **Step 3: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add typeless_local/_version.py typeless_local/__init__.py
git commit -m "Add app_version() with build-time bake fallback to git"
```

**Acceptance:**
- `python -c "from typeless_local import app_version; print(app_version())"` prints something other than "unknown" in dev.

---

### Task 11 — `typeless_local/app.py` integrates vocab + trace + menubar 🔴 SERIAL

**Files:**
- Modify: `typeless_local/app.py`
- Test: `tests/test_app_trace_wiring.py` (new)

- [ ] **Step 1: Write failing integration test**

Create `/Users/alllllenshi/Projects/typeless-local/tests/test_app_trace_wiring.py`:

```python
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from typeless_local.config import (
    AppConfig, RefineConfig, UserPaths, resolve_app_root,
)
from typeless_local.mac_integration import FocusContext


def _make_app_config(tmp_path: Path) -> AppConfig:
    user_paths = UserPaths(
        config_dir=tmp_path,
        vocab_path=tmp_path / "vocab.yaml",
        trace_db_path=tmp_path / "trace.db",
        log_path=tmp_path / "app.log",
        stopwords_dir=tmp_path / "stops",
        user_config_path=tmp_path / "config.yaml",
    )
    return AppConfig(
        root=resolve_app_root(),
        jarvis_root=Path("/nonexistent"),
        jarvis_config={},
        refine=RefineConfig("gpt-5.4-mini", "https://api.openai.com/v1", "OPENAI_API_KEY", 128),
        user_paths=user_paths,
    )


def _read_rows(db: Path) -> list[dict]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM sessions").fetchall()]
    finally:
        conn.close()


def test_successful_pipeline_writes_trace_row(tmp_path: Path) -> None:
    cfg = _make_app_config(tmp_path)
    # vocab seeded
    cfg.user_paths.vocab_path.write_text(
        "user:\n  - Jarvis\nauto: []\n", encoding="utf-8"
    )

    # Avoid touching macOS APIs by patching imports at the app boundary.
    with patch("typeless_local.app.TypelessLocalApp._build_components") as build:
        from typeless_local.app import TypelessLocalApp

        fake_asr = MagicMock()
        fake_asr.transcribe.return_value = SimpleNamespace(
            text="hi jarvas", language="en", confidence=0.9,
        )
        fake_asr.model_name = "fake:test"

        fake_refiner = MagicMock()
        fake_refiner.refine.return_value = SimpleNamespace(
            text="Hi Jarvis.", raw_text="hi jarvas", model="gpt-5.4-mini",
        )

        build.return_value = SimpleNamespace(
            asr=fake_asr,
            refiner=fake_refiner,
            recorder=MagicMock(get_volume_level=MagicMock(return_value=0.1),
                               is_quality_ok=MagicMock(return_value=(True, "ok"))),
        )

        app = TypelessLocalApp(cfg, headless=True)

    audio = np.zeros(8000, dtype=np.float32)
    ctx = FocusContext(app_name="TextEdit", window_title="Untitled", can_insert_text=False)
    app._process_audio(audio, ctx, session_id=1)

    rows = _read_rows(cfg.user_paths.trace_db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["raw_asr_text"] == "hi jarvas"
    assert row["refined_text"] == "Hi Jarvis."
    assert row["hotwords_count"] == 1
    assert "Jarvis" in row["vocab_terms_used"]
    assert row["error"] is None


def test_low_quality_audio_still_logs_trace_row(tmp_path: Path) -> None:
    cfg = _make_app_config(tmp_path)
    with patch("typeless_local.app.TypelessLocalApp._build_components") as build:
        from typeless_local.app import TypelessLocalApp

        fake_asr = MagicMock(model_name="fake:test")
        fake_refiner = MagicMock()
        build.return_value = SimpleNamespace(
            asr=fake_asr,
            refiner=fake_refiner,
            recorder=MagicMock(
                get_volume_level=MagicMock(return_value=0.0),
                is_quality_ok=MagicMock(return_value=(False, "silence")),
            ),
        )
        app = TypelessLocalApp(cfg, headless=True)

    audio = np.zeros(800, dtype=np.float32)
    ctx = FocusContext(app_name="x", window_title="y", can_insert_text=False)
    app._process_audio(audio, ctx, session_id=1)

    rows = _read_rows(cfg.user_paths.trace_db_path)
    assert len(rows) == 1
    assert rows[0]["error"] and "silence" in rows[0]["error"]
    # ASR / refine never ran
    fake_asr.transcribe.assert_not_called()


def test_exception_path_logs_error_row(tmp_path: Path) -> None:
    cfg = _make_app_config(tmp_path)
    with patch("typeless_local.app.TypelessLocalApp._build_components") as build:
        from typeless_local.app import TypelessLocalApp

        fake_asr = MagicMock(model_name="fake:test")
        fake_asr.transcribe.side_effect = RuntimeError("boom")
        build.return_value = SimpleNamespace(
            asr=fake_asr,
            refiner=MagicMock(),
            recorder=MagicMock(
                get_volume_level=MagicMock(return_value=0.1),
                is_quality_ok=MagicMock(return_value=(True, "ok")),
            ),
        )
        app = TypelessLocalApp(cfg, headless=True)

    audio = np.zeros(8000, dtype=np.float32)
    ctx = FocusContext(app_name="x", window_title="y", can_insert_text=False)
    with pytest.raises(RuntimeError):
        app._process_audio(audio, ctx, session_id=1)

    rows = _read_rows(cfg.user_paths.trace_db_path)
    assert len(rows) == 1
    assert "boom" in (rows[0]["error"] or "")
```

- [ ] **Step 2: Run, expect failures**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest tests/test_app_trace_wiring.py -q
```

Expected: 3 failed (`headless` kwarg, `_build_components`, and trace-writer wiring missing).

- [ ] **Step 3: Refactor `app.py` for testability and wire vocab + trace**

The refactor:

1. Add a private `_build_components(self)` method that returns a `SimpleNamespace(asr=..., refiner=..., recorder=...)`. Move the current direct constructions of `JarvisASR`, `TextRefiner`, and `MicrophoneRecorder` inside it. The test patches this method to inject fakes.
2. Add `headless: bool = False` parameter. When True, skip `FloatingOverlay`, `GlobalHotkeyMonitor`, `MenuBarIcon`, and `audio_ducker` (audio_ducker stays — but stub it via `_build_components` if needed; simplest: keep but ensure tests don't trigger duck/restore).
3. Load `vocab` via `load_vocab(config.user_paths.vocab_path)` at init.
4. Build `DictationTrace(config.user_paths.trace_db_path)` at init.
5. Rewrite `_process_audio` per the spec § A6 (build SessionRecord, try/finally, log low-quality drops, set was_pasted post-paste).
6. Add `reload_vocab(self)` method.
7. Pass `self.vocab` to `self.asr.transcribe(audio, initial_prompt=as_initial_prompt(self.vocab))` and `self.refiner.refine(..., vocab=self.vocab)`.

Show the new `_process_audio`:

```python
def _process_audio(self, audio, context, session_id=None):
    from typeless_local import app_version
    from typeless_local.trace import SessionRecord
    from typeless_local.vocab import as_initial_prompt

    session_id = getattr(self, "_active_session_id", 0) if session_id is None else session_id
    started = time.time()
    audio_rms = float(self.recorder.get_volume_level(audio))
    record = SessionRecord(
        started_at=started,
        audio_duration_s=audio.size / self.config.sample_rate,
        audio_rms=audio_rms,
        audio_sample_rate=self.config.sample_rate,
        focus_app=context.app_name or "",
        focus_window=context.window_title or "",
        vocab_terms_used=", ".join(self.vocab),
        hotwords_count=len(self.vocab),
        asr_model=getattr(self.asr, "model_name", ""),
        refine_model=self.config.refine.model,
        app_version=app_version(),
    )

    quality_ok, quality_message = self.recorder.is_quality_ok(
        audio,
        min_duration=float(getattr(self.config, "min_recording_seconds", 0.25)),
        low_volume_threshold=float(getattr(self.config, "low_volume_threshold", 0.02)),
    )
    if not quality_ok:
        record.error = f"dropped: {quality_message}"
        record.ended_at = time.time()
        record.latency_total_ms = int((record.ended_at - started) * 1000)
        self.trace.log(record)
        if not getattr(self, "headless", False):
            self._show_empty_then_idle(session_id)
        return

    try:
        if not self._is_current_processing_session(session_id) and not getattr(self, "headless", False):
            return
        self._set_processing_message("Thinking")

        asr_start = time.monotonic()
        transcript = self.asr.transcribe(
            audio, initial_prompt=as_initial_prompt(self.vocab) or None
        )
        record.raw_asr_text = transcript.text
        record.raw_asr_language = transcript.language
        record.raw_asr_confidence = transcript.confidence
        record.latency_asr_ms = int((time.monotonic() - asr_start) * 1000)

        if self._should_drop_transcript(transcript):
            record.error = "dropped: empty/short transcript"
            if not getattr(self, "headless", False):
                self._show_empty_then_idle(session_id)
            return

        refine_start = time.monotonic()
        refined = self.refiner.refine(transcript.text, context, vocab=self.vocab)
        record.refined_text = refined.text or transcript.text
        record.latency_refine_ms = int((time.monotonic() - refine_start) * 1000)
        final_text = record.refined_text

        if getattr(self, "headless", False):
            return  # tests stop here

        if not self._is_current_processing_session(session_id):
            return
        self._stop_processing_progress()
        self._call_ui(self.overlay.show_thinking, progress=1.0, message="Thinking")
        if context.can_insert_text:
            paste_text(final_text)
            record.was_pasted = True
            self.state = "idle"
            self._copy_fallback_text = ""
            self._call_ui(self.overlay.hide)
            return

        self._copy_fallback_text = final_text
        self.state = "idle"
        self._call_ui(self.overlay.show_copy_fallback, final_text, False)
    except Exception as exc:
        record.error = repr(exc)
        if not getattr(self, "headless", False):
            self._stop_processing_progress()
            self.state = "idle"
            self._call_ui(self.overlay.show_error, "Retry")
            time.sleep(1.4)
            self._call_ui(self.overlay.hide)
        raise
    finally:
        record.ended_at = time.time()
        record.latency_total_ms = int((record.ended_at - started) * 1000)
        self.trace.log(record)
```

(The full refactor for `__init__` and `_build_components` follows the same approach — copy the current direct constructions into `_build_components`, parameterize on `headless`.)

**MUST PRESERVE from the existing `_process_audio`** (the rewrite above drops them for brevity; merge them back):

- `self._cancel_recording_timeout()` at the start of the try block before the ASR call (the original calls it inside `_finish_recording`, which is unchanged — verify the call still runs).
- `self._restore_audio_ducking()` is called by `_finish_recording` before processing starts — keep the existing call there; the rewrite to `_process_audio` does NOT need to call it again.
- `self.executor.submit(self._process_audio, audio, self.focus_context, session_id)` and `future.add_done_callback(self._log_processing_done)` in `_finish_recording` stay unchanged.
- `self._stop_processing_progress()`, `_start_processing_progress`, `_set_processing_message` calls during processing — keep them in the same places they live now; `_process_audio` already drives them.
- `_should_drop_transcript(transcript)` and the `_show_empty_then_idle(session_id)` call on early exit.
- `_is_current_processing_session(session_id)` checks before/between stages.

The rewrite shown above includes most of these markers in the right order. Diff carefully against the original to confirm nothing is silently removed.

- [ ] **Step 4: Run all tests**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest -q
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add typeless_local/app.py tests/test_app_trace_wiring.py
git commit -m "app: wire vocab into ASR/refine, write SessionRecord to trace per dictation"
```

**Acceptance:**
- All 3 wiring tests pass.
- Existing app tests still pass.

---

### Task 12 — Wire menubar into app + RotatingFileHandler logging 🔴 SERIAL

**Files:**
- Modify: `typeless_local/app.py`

- [ ] **Step 1: Add menubar field and wire state transitions**

In `TypelessLocalApp.__init__`, after `_build_components`, if not `headless`:

```python
        from typeless_local.menubar import MenuBarIcon
        from AppKit import NSApp

        user_paths = config.user_paths
        self.menubar = MenuBarIcon(
            on_reload_vocab=self.reload_vocab,
            on_quit=lambda: NSApp().terminate_(None),
            trace_folder=user_paths.config_dir if user_paths else None,
            log_path=user_paths.log_path if user_paths else None,
        )
```

Add to `TypelessLocalApp.start` (right after overlay.setup, before hotkey start):

```python
        self.menubar.setup()
        self.menubar.set_state("idle")
```

Add `_set_menubar`:

```python
    def _set_menubar(self, state: str) -> None:
        mb = getattr(self, "menubar", None)
        if mb is not None:
            mb.set_state(state)
```

And call it everywhere `self.state` changes:

- After `self.state = "starting"` → `self._set_menubar("starting")`
- After `self.state = "recording"` → `self._set_menubar("recording")`
- After `self.state = "processing"` → `self._set_menubar("processing")`
- After `self.state = "idle"` → `self._set_menubar("idle")`
- On error paths → `self._set_menubar("error")`

Add `reload_vocab`:

```python
    def reload_vocab(self) -> None:
        from typeless_local.vocab import load_vocab

        path = self.config.user_paths.vocab_path if self.config.user_paths else None
        if path is None:
            return
        self.vocab = load_vocab(path)
        LOGGER.info("Reloaded vocab: %d terms", len(self.vocab))
```

- [ ] **Step 2: Add RotatingFileHandler to configure_logging**

Replace `configure_logging` in `app.py`:

```python
def configure_logging() -> None:
    """Configure process logging."""

    from logging.handlers import RotatingFileHandler

    level_name = os.environ.get("TYPELESS_LOCAL_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        log_dir = Path.home() / ".typeless-local"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "app.log"
        handlers.append(
            RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5)
        )
    except Exception:
        pass
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
```

- [ ] **Step 3: Run all tests**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest -q
```

Expected: all green.

- [ ] **Step 4: Smoke test (manual)**

```bash
pkill -f "python -m typeless_local"
"/Users/alllllenshi/Projects/typeless-local/Typeless Local.app/Contents/MacOS/typeless-local" &
sleep 4
ls -la ~/.typeless-local/
```

Expected: menu bar shows a mic icon; `~/.typeless-local/` exists with `vocab.yaml`, `app.log`.

- [ ] **Step 5: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add typeless_local/app.py
git commit -m "app: wire menubar + rotating file log; reload_vocab handler"
```

**Acceptance:**
- App starts with menu bar visible.
- State transitions update the icon.

---

## Phase B — Vendoring + py2app (🔴 SERIAL)

### Task 13 — Vendor Jarvis core 🔴 SERIAL

**Files:**
- Create: `typeless_local/_vendor/__init__.py`
- Create: `typeless_local/_vendor/jarvis_core/__init__.py`
- Create: `typeless_local/_vendor/jarvis_core/README.md`
- Create: `typeless_local/_vendor/jarvis_core/speech_recognizer.py` (and transitive deps)
- Create: `typeless_local/_vendor/jarvis_core/media_ducking.py` (and transitive deps)
- Test: `tests/test_vendor_imports.py`

- [ ] **Step 1: Trace Jarvis import graph**

```bash
cd /Users/alllllenshi/Projects/jarvis
python -c "
import ast, pathlib
roots = ['core/speech_recognizer.py', 'core/media_ducking.py']
seen = set()
def walk(p):
    p = pathlib.Path(p)
    if str(p) in seen or not p.exists(): return
    seen.add(str(p))
    tree = ast.parse(p.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('core'):
            sub = node.module.replace('.', '/') + '.py'
            walk(sub)
for r in roots:
    walk(r)
for s in sorted(seen): print(s)
"
```

Record the listed files; copy each into `typeless_local/_vendor/jarvis_core/` (preserving relative paths). Each copied file's first line:

```python
# vendored from jarvis @ <git short hash> on 2026-05-12
```

- [ ] **Step 2: Rewrite imports**

For every vendored file, replace `from core.X import Y` with
`from typeless_local._vendor.jarvis_core.X import Y` and `import core.X` with
`from typeless_local._vendor.jarvis_core import X`.

- [ ] **Step 3: Update typeless_local-side imports**

In `typeless_local/asr.py`, replace:

```python
from core.speech_recognizer import SpeechRecognizer
```

with:

```python
try:
    from typeless_local._vendor.jarvis_core.speech_recognizer import SpeechRecognizer
except ImportError:
    if str(jarvis_root) not in sys.path:
        sys.path.insert(0, str(jarvis_root))
    from core.speech_recognizer import SpeechRecognizer
```

In `typeless_local/app.py`, similarly for `SystemAudioDucker`:

```python
try:
    from typeless_local._vendor.jarvis_core.media_ducking import SystemAudioDucker
except ImportError:
    from core.media_ducking import SystemAudioDucker
```

- [ ] **Step 4: Write `_vendor/jarvis_core/README.md`**

Create with content:

```markdown
# Vendored Jarvis core

Source: ../../../../jarvis @ <commit-hash> on 2026-05-12.

These files are copied verbatim from the Jarvis project so the .app bundle
doesn't depend on a sibling jarvis/ checkout. To resync:

1. `cp -r ../../../jarvis/core/{speech_recognizer.py,media_ducking.py,...} typeless_local/_vendor/jarvis_core/`
2. Update import statements: `from core.X` → `from typeless_local._vendor.jarvis_core.X`.
3. Update the date and commit hash at the top of this file.

Do not modify vendored files for typeless-local-specific behavior. If you
need typeless-local-specific changes to the ASR or ducker, wrap them in
typeless_local/ files instead so resyncs are clean.
```

- [ ] **Step 5: Write the import test**

Create `/Users/alllllenshi/Projects/typeless-local/tests/test_vendor_imports.py`:

```python
def test_can_import_speech_recognizer_from_vendor() -> None:
    from typeless_local._vendor.jarvis_core.speech_recognizer import SpeechRecognizer  # noqa: F401


def test_can_import_media_ducking_from_vendor() -> None:
    from typeless_local._vendor.jarvis_core.media_ducking import SystemAudioDucker  # noqa: F401
```

- [ ] **Step 6: Run tests**

```bash
cd /Users/alllllenshi/Projects/typeless-local
pytest -q
```

Expected: green (vendor imports succeed, existing tests still pass).

- [ ] **Step 7: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add typeless_local/_vendor/ tests/test_vendor_imports.py
git add typeless_local/asr.py typeless_local/app.py
git commit -m "Vendor jarvis core: speech_recognizer + media_ducking (and transitive deps)"
```

**Acceptance:**
- Both import tests pass.
- App still runs in dev (verified by overall `pytest -q`).

---

### Task 14 — `setup.py` for py2app 🔴 SERIAL

**Files:**
- Create: `setup.py`
- Modify: `pyproject.toml` (add py2app to dev deps)

- [ ] **Step 1: Create setup.py**

Create `/Users/alllllenshi/Projects/typeless-local/setup.py`:

```python
"""py2app build config for Typeless Local."""

from pathlib import Path

from setuptools import setup

ROOT = Path(__file__).resolve().parent
APP = [str(ROOT / "typeless_local" / "__main__.py")]
DATA_FILES = [
    (
        "Resources",
        [
            str(ROOT / "assets" / "AppIcon.icns"),
            str(ROOT / "assets" / "config.yaml"),
            str(ROOT / "assets" / "stopwords-en.txt"),
            str(ROOT / "assets" / "stopwords-zh.txt"),
        ],
    ),
]

OPTIONS = {
    "argv_emulation": False,
    "packages": [
        "typeless_local",
        "numpy",
        "sounddevice",
        "AppKit",
        "Quartz",
        "ApplicationServices",
        "PyObjCTools",
        "objc",
        "openai",
        "yaml",
        "mlx_whisper",
    ],
    "includes": ["ctypes", "sqlite3", "json", "re", "logging.handlers"],
    "excludes": [
        "tkinter",
        "PIL",
        "matplotlib",
        "pytest",
        "setuptools",
        "pip",
        "wheel",
    ],
    "plist": {
        "CFBundleName": "Typeless Local",
        "CFBundleDisplayName": "Typeless Local",
        "CFBundleIdentifier": "com.alllllenshi.typeless-local",
        "CFBundleShortVersionString": "0.2.0",
        "CFBundleVersion": "0.2.0",
        "LSUIElement": True,
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription":
            "Typeless Local records audio when you press F5 to dictate.",
        "NSAppleEventsUsageDescription":
            "Typeless Local pastes refined dictation into the focused app.",
    },
    "iconfile": str(ROOT / "assets" / "AppIcon.icns"),
}

setup(
    app=APP,
    name="Typeless Local",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
```

- [ ] **Step 2: Create a placeholder AppIcon.icns**

```bash
cd /Users/alllllenshi/Projects/typeless-local
# Use the system mic SF Symbol as a quick placeholder.
mkdir -p assets
sips -s format icns /System/Library/PrivateFrameworks/CoreEmoji.framework/Versions/A/Resources/AppIcon.png --out assets/AppIcon.icns 2>/dev/null || \
  (echo "Falling back to empty icns" && touch assets/AppIcon.icns)
```

If the sips call fails (file path may differ across macOS versions), just create an empty `assets/AppIcon.icns` — py2app accepts it and the bundle just gets a default icon.

- [ ] **Step 3: Add py2app to pyproject.toml**

Append to `/Users/alllllenshi/Projects/typeless-local/pyproject.toml`:

```toml
[project.optional-dependencies]
build = ["py2app>=0.28"]
```

- [ ] **Step 4: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add setup.py pyproject.toml assets/AppIcon.icns
git commit -m "Add py2app setup.py with bundle plist and resource list"
```

**Acceptance:**
- `python -c "import ast; ast.parse(open('setup.py').read())"` passes.

---

### Task 15 — `scripts/build_app.py` with version baking 🔴 SERIAL

**Files:**
- Create: `scripts/build_app.py`

- [ ] **Step 1: Implement build script**

Create `/Users/alllllenshi/Projects/typeless-local/scripts/build_app.py`:

```python
#!/usr/bin/env python
"""Build the Typeless Local self-contained .app via py2app."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
VERSION_FILE = ROOT / "typeless_local" / "_version.py"
BUNDLE_ID = "com.alllllenshi.typeless-local"


def short_hash() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
        dirty = (
            subprocess.run(
                ["git", "diff-index", "--quiet", "HEAD"], cwd=ROOT
            ).returncode
            != 0
        )
        return f"{out}{'+dirty' if dirty else ''}"
    except Exception:
        return "unknown"


def bake_version() -> None:
    h = short_hash()
    VERSION_FILE.write_text(
        f'"""Build-time version marker. Overwritten by scripts/build_app.py."""\n\n'
        f'VERSION = "0.2.0+{h}"\n',
        encoding="utf-8",
    )
    print(f"baked version: 0.2.0+{h}")


def clean() -> None:
    for d in (BUILD, DIST):
        if d.exists():
            print(f"rm -rf {d}")
            shutil.rmtree(d)


def build() -> Path:
    subprocess.check_call([sys.executable, "setup.py", "py2app"], cwd=ROOT)
    app = DIST / "Typeless Local.app"
    if not app.exists():
        raise SystemExit(f"build did not produce {app}")
    return app


def sign(app: Path) -> None:
    subprocess.check_call(
        ["codesign", "--force", "--deep", "--sign", "-", str(app)]
    )


def main() -> int:
    bake_version()
    clean()
    app = build()
    sign(app)
    print(f"\nBuilt: {app}")
    print("Move to /Applications/ or run with: open '" + str(app) + "'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Make executable**

```bash
chmod +x /Users/alllllenshi/Projects/typeless-local/scripts/build_app.py
```

- [ ] **Step 3: Smoke test the build script (dry run check)**

```bash
cd /Users/alllllenshi/Projects/typeless-local
python -c "import ast; ast.parse(open('scripts/build_app.py').read())"
```

Expected: no output (parse OK).

- [ ] **Step 4: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add scripts/build_app.py
git commit -m "Add build_app.py: bake version, clean, py2app, ad-hoc sign"
```

**Acceptance:**
- Script parses; ready for actual build in Task 16.

---

### Task 16 — Actually build the .app and smoke-test 🔴 SERIAL

**Files:**
- (modifies `dist/` outputs only)

- [ ] **Step 1: Ensure py2app is installed**

```bash
cd /Users/alllllenshi/Projects/typeless-local
uv pip install "py2app>=0.28"
```

(Uses the user's preferred uv tool per CLAUDE.md.)

- [ ] **Step 2: Run the build**

```bash
cd /Users/alllllenshi/Projects/typeless-local
python scripts/build_app.py 2>&1 | tail -50
```

Expected: ends with `Built: ...dist/Typeless Local.app`. If a runtime import is missing, the build still succeeds but the app will fail at launch — the next steps verify that.

- [ ] **Step 3: Launch the built .app, capture log**

```bash
pkill -f "python -m typeless_local" 2>/dev/null
open "/Users/alllllenshi/Projects/typeless-local/dist/Typeless Local.app"
sleep 8
tail -100 ~/.typeless-local/app.log
```

Expected: log shows `Typeless Local ready` and `ASR provider: mlx_whisper`. No tracebacks.

- [ ] **Step 4: Verify menubar icon is present**

```bash
osascript -e 'tell application "System Events" to get the title of every menu bar item of menu bar 1 of process "Typeless Local"' 2>/dev/null
```

Or visually confirm in macOS menu bar.

- [ ] **Step 5: Test one dictation round-trip (manual)**

Press F5, say "hello jarvis", press F5 again. Wait. Check that text appears in the focused app, then verify the trace row:

```bash
sqlite3 ~/.typeless-local/trace.db "SELECT raw_asr_text, refined_text, latency_total_ms FROM sessions ORDER BY id DESC LIMIT 1"
```

Expected: one row with the dictated text.

- [ ] **Step 6: If everything works, commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add -A
git status   # confirm only intentional changes
git commit -m "Verify py2app build runs end-to-end (manual smoke)" --allow-empty
```

**Acceptance:**
- Built .app runs.
- Menu bar shows icon.
- One F5 round-trip writes a trace row with non-empty `refined_text`.

---

### Task 17 — Cleanup old shell-script wrapper + README update 🔴 SERIAL

**Files:**
- Delete: `Typeless Local.app/` (the in-tree shell wrapper)
- Modify: `README.md`

- [ ] **Step 1: Remove old in-tree shell wrapper**

```bash
cd /Users/alllllenshi/Projects/typeless-local
rm -rf "Typeless Local.app"
```

Note: the BUILT `.app` lives in `dist/` and is git-ignored. Keep `scripts/run.sh` for dev mode.

- [ ] **Step 2: Update README**

Add to `/Users/alllllenshi/Projects/typeless-local/README.md` after the `## Run` section:

```markdown
## Build the self-contained .app

```bash
python scripts/build_app.py
open dist/Typeless\ Local.app
```

The built bundle is fully self-contained (no external venv or jarvis/ checkout
required). First run downloads the Whisper model (~1.5GB) to
`~/.cache/huggingface/`.

## Vocabulary

User-managed term list at `~/.typeless-local/vocab.yaml`:

```yaml
user:
  - Jarvis
  - Typeless
auto: []   # populated by scripts/extract_hotwords.py
```

Terms are fed to Whisper as initial prompt and to the refine LLM as a
"correct mishears" hint. Reload from the menu bar after editing.

## Trace database

Every dictation session writes one row to `~/.typeless-local/trace.db`. Query
example:

```bash
sqlite3 ~/.typeless-local/trace.db \
  'SELECT datetime(started_at,"unixepoch","localtime"), raw_asr_text, refined_text, latency_total_ms
   FROM sessions ORDER BY id DESC LIMIT 20'
```

## Auto-discover hotwords

```bash
python scripts/extract_hotwords.py --days 30 --min-count 2
```

Scans recent trace rows; adds high-frequency "added in refine" tokens to
`vocab.yaml`'s `auto:` section.
```

- [ ] **Step 3: Add `dist/` and `build/` to `.gitignore`**

Append to `/Users/alllllenshi/Projects/typeless-local/.gitignore`:

```
build/
dist/
*.egg-info/
```

- [ ] **Step 4: Commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add README.md .gitignore
git rm -r "Typeless Local.app" 2>/dev/null || true
git commit -m "Remove shell-script .app wrapper; document py2app build + vocab/trace workflow"
```

**Acceptance:**
- `git ls-files | grep -i 'typeless local.app'` returns nothing.
- README documents build + vocab + trace + extract_hotwords usage.

---

## Final Verification

### Task 18 — Full clean-room rebuild and smoke 🔴 SERIAL

- [ ] **Step 1: Wipe build artifacts**

```bash
cd /Users/alllllenshi/Projects/typeless-local
rm -rf build/ dist/
```

- [ ] **Step 2: Rebuild from scratch**

```bash
python scripts/build_app.py
```

- [ ] **Step 3: Move to /Applications**

```bash
rm -rf "/Applications/Typeless Local.app"
mv "dist/Typeless Local.app" /Applications/
```

- [ ] **Step 4: Launch and grant permissions if needed**

```bash
open "/Applications/Typeless Local.app"
```

If prompted, grant Microphone + Accessibility.

- [ ] **Step 5: Five-press dictation gauntlet**

Press F5, say one short phrase, press F5 to stop. Repeat 5x. Then:

```bash
sqlite3 ~/.typeless-local/trace.db \
  "SELECT id, raw_asr_text, refined_text, latency_total_ms, error
   FROM sessions ORDER BY id DESC LIMIT 5"
```

Expected: 5 rows with sensible text and no errors.

- [ ] **Step 6: Test vocabulary loop**

```bash
echo "user:
  - Jarvis
  - Typeless
  - mlx-whisper
auto: []" > ~/.typeless-local/vocab.yaml
```

Click menu bar → Reload Vocab. Do one more F5 dictation saying a term from the list. Verify the term appears verbatim in `refined_text`.

- [ ] **Step 7: Test extract_hotwords**

```bash
cd /Users/alllllenshi/Projects/typeless-local
python scripts/extract_hotwords.py --dry-run --min-count 1 --days 1
```

Expected: prints any new candidate terms; doesn't modify vocab.yaml.

- [ ] **Step 8: Final commit**

```bash
cd /Users/alllllenshi/Projects/typeless-local
git add -A
git diff --cached --stat   # confirm only doc/version updates
git commit -m "End-to-end smoke: 5 dictations + vocab reload + extract dry-run all passing" --allow-empty
```

**Acceptance:**
- 5 successful dictations.
- Trace rows present.
- Reload Vocab path works.
- extract_hotwords runs cleanly.

---

## Parallelization Summary

| Batch | Tasks | Can dispatch in parallel? |
|---|---|---|
| Batch 1 🟢 | 1, 2, 3, 4, 5 | YES — 5 independent subagents |
| Batch 2 🟡 | 6, 7, 8, 9 | YES — 4 independent subagents (after Batch 1 lands) |
| Batch 3 🔴 | 10, 11, 12 | SERIAL — each modifies `app.py` |
| Batch 4 🔴 | 13, 14, 15, 16, 17 | SERIAL — vendoring → setup → build → smoke → cleanup |
| Batch 5 🔴 | 18 | SERIAL — final clean-room smoke |

After each batch, the dispatcher reviews diffs and runs `pytest -q` before
proceeding.
