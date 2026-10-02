from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from typeless_local import brand, devices, history, login_item, permissions, preferences, reach, vocab, webview, windows
from typeless_local.config import UserPaths, refine_config_for
from typeless_local.trace import DictationTrace, SessionRecord, append_correction
from typeless_local.webview import web_root

JARVIS = {
    "llm": {
        "default_preset": "mini",
        "presets": {
            "mini": {"model": "gpt-mini", "api_key_env": "TEST_KEY_A"},
            "deep": {"model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1", "api_key_env": "TEST_KEY_B"},
        },
    },
    "asr": {"provider": "mlx_whisper", "language": "zh"},
}


class FakeWindow:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.sent: list[dict] = []
        self.shown = False
        self.closed = False
        self.has_glass = True
        self.glass: list = []
        self.suppressed = None

    def show(self) -> None:
        self.shown = True

    def set_title(self, title: str) -> None:
        self.kwargs["title"] = title

    def visible(self) -> bool:
        return self.shown

    def send(self, message: dict) -> None:
        self.sent.append(message)

    def close(self) -> None:
        self.shown = False
        self.closed = True

    def apply_glass(self, shapes) -> None:
        self.glass.append(shapes)

    def suppress_glass(self, suppressed: bool) -> None:
        self.suppressed = suppressed

    def last(self, kind: str) -> dict:
        return [m for m in self.sent if m.get("t") == kind][-1]


class FakeApp:
    def __init__(self, tmp_path: Path) -> None:
        paths = UserPaths(
            config_dir=tmp_path,
            vocab_path=tmp_path / "vocab.yaml",
            corrections_path=tmp_path / "corrections.yaml",
            trace_db_path=tmp_path / "trace.db",
            log_path=tmp_path / "app.log",
            stopwords_dir=tmp_path / "stops",
            user_config_path=tmp_path / "config.yaml",
            env_path=tmp_path / "env",
        )
        jarvis = {key: dict(value) for key, value in JARVIS.items()}
        self.config = SimpleNamespace(
            jarvis_config=jarvis, refine=refine_config_for(jarvis, "mini"), input_device="", user_paths=paths
        )
        self.prefs = preferences.Preferences()
        self.asr = SimpleNamespace(model_name="mlx_whisper:whisper")
        self.audio_ducker = SimpleNamespace(enabled=True)
        self._download = None
        self.calls: list[tuple] = []
        self.feedback_result = (True, "")

    def _call_ui(self, callback, *args, **kwargs) -> None:
        callback(*args, **kwargs)

    def set_preference(self, key, value):
        self.calls.append(("pref", key, value))
        self.prefs = dataclasses.replace(self.prefs, **{key: preferences.coerce(key, value)})
        return self.prefs

    def set_language(self, language: str) -> None:
        self.calls.append(("language", language))

    def set_ducking(self, enabled: bool) -> None:
        self.calls.append(("duck", enabled))

    def select_model(self, preset: str) -> None:
        self.calls.append(("preset", preset))

    def select_input_device(self, name: str) -> None:
        self.calls.append(("input", name))

    def store_api_key(self, env: str, value: str) -> None:
        self.calls.append(("key", env, value))

    def reload_vocab(self) -> None:
        self.calls.append(("reload",))

    def show_log(self) -> None:
        self.calls.append(("log",))

    def export_diagnostics(self) -> None:
        self.calls.append(("diagnostics",))

    def send_feedback(self, message, email, attach, done) -> None:
        self.calls.append(("feedback", message, email, attach))
        done(*self.feedback_result)

    def _start_model_prefetch(self) -> None:
        self.calls.append(("prefetch",))


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setattr(webview, "accessibility_env", lambda: {"rm": False, "rt": False, "hc": False})
    monkeypatch.setattr(devices, "list_input_devices", lambda: ["MacBook Pro Microphone", "USB Mic"])
    monkeypatch.setattr(login_item, "status", lambda: "disabled")
    monkeypatch.setattr(permissions, "system_dictation_uses_f5", lambda: False)
    monkeypatch.setattr(permissions, "microphone_status", lambda: "authorized")
    monkeypatch.setattr(windows, "has_accessibility_trust", lambda: True)
    monkeypatch.delenv("TEST_KEY_A", raising=False)
    monkeypatch.delenv("TEST_KEY_B", raising=False)
    app = FakeApp(tmp_path)
    controller = windows.Windows(app, factory=FakeWindow)
    # Worker threads run inline so each test sees the result at once.
    monkeypatch.setattr(controller, "_run", lambda job, name: job())
    return SimpleNamespace(app=app, windows=controller, paths=app.config.user_paths)


def _open_settings(ui) -> FakeWindow:
    ui.windows.show_settings()
    ui.windows._settings_message({"t": "ready"})
    return ui.windows.settings


def _log(db: Path, **fields) -> None:
    DictationTrace(db).log(SessionRecord(started_at=fields.pop("at", 1000.0), **fields))


# --------------------------------------------------------------- helpers


def test_service_names_come_from_the_preset_base_url() -> None:
    assert windows.service_name(None) == "OpenAI"
    assert windows.service_name("https://api.openai.com/v1") == "OpenAI"
    assert windows.service_name("https://api.deepseek.com/v1") == "DeepSeek"
    assert windows.service_name("https://llm.example.org/v1") == "llm.example.org"


def test_env_file_keys_lists_only_names_with_a_value(tmp_path) -> None:
    env = tmp_path / "env"
    env.write_text("# comment\nTEST_KEY_A=abc\nTEST_KEY_B=\n", encoding="utf-8")
    assert windows.env_file_keys(env) == {"TEST_KEY_A"}
    assert windows.env_file_keys(tmp_path / "missing") == set()


# -------------------------------------------------------------- settings


def test_settings_opens_once_and_answers_ready_with_env_and_state(ui) -> None:
    window = _open_settings(ui)
    ui.windows.show_settings("model")
    assert window is ui.windows.settings and window.shown
    kinds = [m["t"] for m in window.sent]
    assert kinds[:2] == ["pane", "env"] or kinds[0] == "env"
    assert window.last("env")["native"] is True
    assert window.suppressed is False
    assert window.last("pane") == {"t": "pane", "id": "model"}


def test_switching_to_english_redraws_every_window_already_built(ui) -> None:
    from typeless_local import i18n

    settings = _open_settings(ui)
    ui.windows.show_history()
    ui.windows._history_message({"t": "ready"})
    history = ui.windows.history
    assert settings.last("env")["lang"] == "zh"

    i18n.use("en")
    ui.windows.relocalize()

    assert settings.kwargs["title"] == "Settings" and history.kwargs["title"] == "History"
    assert settings.last("env")["lang"] == "en" and history.last("env")["lang"] == "en"
    assert settings.last("state")["name"] == "Yana"
    assert ui.windows.onboarding is None  # never built, nothing to redraw


def test_reduce_transparency_hides_the_glass(ui, monkeypatch) -> None:
    monkeypatch.setattr(webview, "accessibility_env", lambda: {"rm": False, "rt": True, "hc": False})
    window = _open_settings(ui)
    assert window.suppressed is True
    assert window.last("env")["native"] is False


def test_settings_state_describes_models_keys_and_the_engine(ui, monkeypatch) -> None:
    monkeypatch.setenv("TEST_KEY_A", "sk-test-aaaaaaaaaaaa1234")
    ui.paths.env_path.write_text("TEST_KEY_B=sk-file-bbbbbbbbbbbb\n", encoding="utf-8")
    state = ui.windows.settings_state()
    assert state["t"] == "state"
    assert [p["name"] for p in state["presets"]] == ["mini", "deep"]
    assert state["presets"][0] == {
        "name": "mini", "model": "gpt-mini", "service": "OpenAI", "env": "TEST_KEY_A", "hasKey": True, "median": None,
    }
    assert state["presets"][1]["service"] == "DeepSeek" and state["presets"][1]["hasKey"] is False
    keys = {k["env"]: k for k in state["keys"]}
    assert keys["TEST_KEY_A"]["where"] == "keychain" and keys["TEST_KEY_A"]["hint"] == "sk-…234"
    assert "TEST_KEY_B" not in keys  # only the key the model in use reads
    assert state["active"] == "mini"
    assert state["language"] == "zh"
    assert state["asrModel"] == "whisper-large-v3-turbo"
    assert state["inputs"] == ["MacBook Pro Microphone", "USB Mic"]
    assert state["choices"]["history_days"] == [30, 90, 365, 0]
    assert state["prefs"]["refine"] is True
    assert state["login"] == "disabled" and state["f5"] is False and state["duck"] is True


def test_settings_changes_go_to_the_app_and_come_back_as_state(ui) -> None:
    window = _open_settings(ui)
    for key, value in [("show_handle", False), ("language", "en"), ("duck", False), ("preset", "deep"), ("input", "USB Mic")]:
        window.sent.clear()
        ui.windows._settings_message({"t": "set", "key": key, "value": value})
        assert window.sent and window.sent[-1]["t"] == "state"
    assert ui.app.calls == [
        ("pref", "show_handle", False), ("language", "en"), ("duck", False), ("preset", "deep"), ("input", "USB Mic"),
    ]


def test_an_invalid_setting_is_logged_not_raised(ui) -> None:
    window = _open_settings(ui)
    ui.windows._settings_message({"t": "set", "key": "dismiss_seconds", "value": "soon"})
    assert window.sent[-1]["t"] == "state"


def test_login_item_needing_approval_opens_system_settings(ui, monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(login_item, "set_enabled", lambda on: "requires_approval")
    monkeypatch.setattr(login_item, "open_system_settings", lambda: opened.append(True))
    _open_settings(ui)
    ui.windows._settings_message({"t": "set", "key": "login", "value": True})
    assert opened == [True]


def test_a_malformed_key_is_refused_without_saving(ui) -> None:
    window = _open_settings(ui)
    ui.windows._settings_message({"t": "key", "env": "TEST_KEY_A", "value": "not a key"})
    assert window.last("keyResult")["ok"] is False
    assert not [c for c in ui.app.calls if c[0] == "key"]


def test_a_key_is_saved_and_settings_redrawn(ui) -> None:
    window = _open_settings(ui)
    window.sent.clear()
    ui.windows._settings_message({"t": "key", "env": "TEST_KEY_A", "value": "sk-test-aaaaaaaaaaaa1234"})
    assert ("key", "TEST_KEY_A", "sk-test-aaaaaaaaaaaa1234") in ui.app.calls
    assert window.last("keyResult") == {"t": "keyResult", "env": "TEST_KEY_A", "ok": True, "msg": "已保存到钥匙串"}
    assert window.sent[-1]["t"] == "state"


def test_connection_test_reports_the_round_trip(ui, monkeypatch) -> None:
    window = _open_settings(ui)
    monkeypatch.setattr(ui.windows, "test_preset", lambda preset: (True, 820, ""))
    ui.windows._settings_message({"t": "test"})
    assert window.last("testResult") == {"t": "testResult", "ok": True, "ms": 820, "msg": "", "preset": "mini"}


def test_connection_test_without_a_key_says_so(ui) -> None:
    ok, ms, error = ui.windows.test_preset("mini")
    assert (ok, ms) == (False, 0) and "API Key" in error


def test_vocabulary_edits_rewrite_the_file_and_reload(ui) -> None:
    window = _open_settings(ui)
    path = ui.paths.vocab_path
    vocab._atomic_write_sections(path, {"user": ["Claude"], "auto": ["PyObjC", "Hermes"], "rejected": []})
    ui.windows._settings_message({"t": "vocab", "op": "add", "term": " Typlus "})
    ui.windows._settings_message({"t": "vocab", "op": "add", "term": "Claude"})
    assert window.last("vocabResult")["msg"] == "“Claude”已经在词库里了。"
    ui.windows._settings_message({"t": "vocab", "op": "remove", "term": "Claude"})
    ui.windows._settings_message({"t": "vocab", "op": "reject", "term": "Hermes"})
    assert vocab.load_user_terms(path) == ["Typlus"]
    assert vocab._load_sections(path)["rejected"] == ["Hermes"]
    assert ("reload",) in ui.app.calls
    state = window.last("state")
    assert state["vocab"]["mine"] == ["Typlus"]
    assert [s["term"] for s in state["vocab"]["suggest"]] == ["PyObjC"]


def test_recent_hand_corrections_are_offered_once_each(ui) -> None:
    for before, after in [("用派 objc", "用 PyObjC"), ("派 objc 好用", "PyObjC 好用"), ("cloud code", "Claude Code")]:
        append_correction(ui.paths.corrections_path, 1, before, after)
    fixes = ui.windows._vocab_state()["fixes"]
    assert [(f["wrong"], f["right"]) for f in fixes] == [("cloud", "Claude"), ("派 objc", "PyObjC")]


def test_fix_terms_are_whole_words() -> None:
    assert windows.fix_terms("用派 objc", "用 PyObjC") == [("objc", "PyObjC")]
    assert windows.fix_terms("cloud code", "Claude Code") == [("cloud", "Claude")]
    assert windows.fix_terms("我在杭州", "我在航州") == []


def test_history_limit_asks_how_many_would_go_then_clear_empties_it(ui) -> None:
    window = _open_settings(ui)
    db = ui.paths.trace_db_path
    _log(db, at=1.0, raw_asr_text="old", refined_text="old")
    _log(db, at=9e12, raw_asr_text="new", refined_text="new")
    ui.windows._settings_message({"t": "count", "days": 30})
    assert window.last("count") == {"t": "count", "days": 30, "n": 1}
    ui.windows._settings_message({"t": "clear"})
    assert history.count_sessions(db) == 0
    assert window.last("state")["history"]["count"] == 0


def test_settings_reports_where_the_sidebar_glass_goes(ui) -> None:
    window = _open_settings(ui)
    shapes = [{"id": "side", "x": 8, "y": 8, "w": 220, "h": 500, "r": 16, "glass": True}]
    ui.windows._settings_message({"t": "geo", "s": shapes})
    assert window.glass == [shapes]


def test_refresh_only_touches_open_windows(ui) -> None:
    ui.windows.refresh(history=True)  # nothing open: nothing to do
    window = _open_settings(ui)
    window.sent.clear()
    ui.windows.refresh()
    assert [m["t"] for m in window.sent] == ["state"]
    window.close()
    window.sent.clear()
    ui.windows.refresh()
    assert window.sent == []


def test_settings_state_carries_usage_only_while_history_is_saved(ui) -> None:
    _log(ui.paths.trace_db_path, at=__import__("time").time(), raw_asr_text="一句", refined_text="一句。",
         refine_model="gpt-mini", prompt_tokens=1000, cached_tokens=0, completion_tokens=50)
    ui.app.config.jarvis_config["llm"]["prices"] = {"gpt-mini": [1.0, 0.1, 4.0]}
    today = ui.windows.settings_state()["usage"]["today"]
    assert today["n"] == 1 and today["cost"] == pytest.approx((1000 * 1.0 + 50 * 4.0) / 1e6)
    ui.app.prefs = dataclasses.replace(ui.app.prefs, save_history=False)
    assert ui.windows.settings_state()["usage"] is None
    ui.windows.show_settings("usage")
    assert ui.windows.settings.last("pane") == {"t": "pane", "id": "usage"}


def test_reopening_a_closed_window_shows_what_changed_meanwhile(ui) -> None:
    # The menu bar switched the model while Settings was closed.
    window = _open_settings(ui)
    window.close()
    ui.app.config.refine = refine_config_for(ui.app.config.jarvis_config, "deep")
    ui.windows.refresh()
    window.sent.clear()
    ui.windows.show_settings("model")
    assert window.last("state")["active"] == "deep"
    assert [m["t"] for m in window.sent] == ["state", "pane"]


def test_reopening_history_and_the_guide_resends_them(ui) -> None:
    ui.windows.show_history()
    ui.windows._history_message({"t": "ready"})
    ui.windows.history.close()
    _log(ui.paths.trace_db_path, raw_asr_text="新的一条", refined_text="新的一条")
    ui.windows.show_history()
    assert ui.windows.history.last("items")["items"][0]["text"] == "新的一条"

    ui.windows.show_onboarding()
    ui.windows._onboarding_message({"t": "ready"})
    guide = ui.windows.onboarding
    guide.close()
    guide.sent.clear()
    ui.windows.show_onboarding()
    assert [m["t"] for m in guide.sent] == ["state"]


def test_the_first_open_waits_for_the_page_instead(ui) -> None:
    ui.windows.show_settings()
    assert ui.windows.settings.sent == []


# --------------------------------------------------------------- history


def test_history_sends_rows_and_the_vocabulary(ui) -> None:
    db = ui.paths.trace_db_path
    _log(db, raw_asr_text="用派 objc", refined_text="用 PyObjC", focus_app="Terminal", latency_total_ms=1800)
    vocab.save_user_terms(ui.paths.vocab_path, ["Claude"])
    ui.windows.show_history()
    ui.windows._history_message({"t": "ready"})
    items = ui.windows.history.last("items")
    assert items["enabled"] is True and items["vocab"] == ["Claude"]
    assert items["items"][0]["text"] == "用 PyObjC" and items["items"][0]["app"] == "Terminal"


def test_history_copy_delete_and_add_word(ui, monkeypatch) -> None:
    copied = []
    monkeypatch.setattr(windows, "set_clipboard_text", copied.append)
    db = ui.paths.trace_db_path
    _log(db, raw_asr_text="a", refined_text="A")
    ui.windows.show_history()
    window = ui.windows.history
    row = history.recent_sessions(db)[0]
    ui.windows._history_message({"t": "copy", "text": "A"})
    assert copied == ["A"] and window.last("toast")["msg"] == "已复制"
    ui.windows._history_message({"t": "vocab", "term": "PyObjC"})
    assert vocab.load_user_terms(ui.paths.vocab_path) == ["PyObjC"]
    assert window.last("items")["vocab"] == ["PyObjC"]
    ui.windows._history_message({"t": "delete", "id": row["id"]})
    assert history.recent_sessions(db) == []
    assert window.last("items")["items"] == []


def test_history_with_saving_off_says_so(ui) -> None:
    ui.app.prefs = dataclasses.replace(ui.app.prefs, save_history=False)
    assert ui.windows.history_payload()["enabled"] is False


# ------------------------------------------------------------ onboarding


def test_guide_state_reports_permissions_key_and_model(ui, monkeypatch) -> None:
    monkeypatch.setattr(ui.windows, "_model_cached", lambda: False)
    ui.app._download = (0.25, 0.0)
    state = ui.windows.onboarding_state()
    assert state["mic"] == "authorized" and state["ax"] is True
    assert state["key"] == {"env": "TEST_KEY_A", "service": "OpenAI", "preset": "mini", "has": False, "trial": False}
    assert state["model"] == {"name": "whisper-large-v3-turbo", "ready": False, "downloading": True, "p": 0.25, "mirror": False}
    ui.app._download = None  # the download at launch failed before the guide opened
    assert ui.windows.onboarding_state()["model"]["downloading"] is False


def test_guide_saves_and_tests_the_key(ui, monkeypatch) -> None:
    monkeypatch.setattr(ui.windows, "test_preset", lambda preset: (True, 800, ""))
    ui.windows.show_onboarding()
    ui.windows._onboarding_message({"t": "key", "env": "TEST_KEY_A", "value": "sk-test-aaaaaaaaaaaa1234"})
    result = ui.windows.onboarding.last("keyResult")
    assert result["ok"] is True and result["msg"] == "已连接 · 往返 0.8 秒"
    assert ("key", "TEST_KEY_A", "sk-test-aaaaaaaaaaaa1234") in ui.app.calls


def test_guide_asks_for_the_microphone_only_while_undecided(ui, monkeypatch) -> None:
    asked, opened, polled = [], [], []
    monkeypatch.setattr(permissions, "request_microphone", lambda: asked.append(True))
    monkeypatch.setattr(permissions, "open_url", opened.append)
    monkeypatch.setattr(ui.windows, "_poll", lambda name, done: polled.append(name))
    ui.windows.show_onboarding()
    monkeypatch.setattr(permissions, "microphone_status", lambda: "not_determined")
    ui.windows._onboarding_message({"t": "mic"})
    monkeypatch.setattr(permissions, "microphone_status", lambda: "denied")
    ui.windows._onboarding_message({"t": "mic"})
    assert asked == [True]
    assert opened == [permissions.MICROPHONE_SETTINGS]
    assert polled == ["mic", "mic"]


def test_guide_waits_for_accessibility_and_redraws_when_granted(ui, monkeypatch) -> None:
    trusted = iter([False, True])
    monkeypatch.setattr(windows, "request_accessibility_trust", lambda: False)
    monkeypatch.setattr(permissions, "open_url", lambda url: None)
    monkeypatch.setattr(windows, "POLL_S", 0)
    ui.windows.show_onboarding()
    window = ui.windows.onboarding
    monkeypatch.setattr(windows, "has_accessibility_trust", lambda: next(trusted, True))
    ui.windows._onboarding_message({"t": "a11y"})
    assert window.last("state")["ax"] is True
    assert ui.windows._polls == set()


def test_guide_retries_a_failed_download(ui, monkeypatch) -> None:
    monkeypatch.setattr(ui.windows, "_model_cached", lambda: False)
    ui.windows.show_onboarding()
    ui.windows._onboarding_message({"t": "download"})
    assert ("prefetch",) in ui.app.calls
    ui.windows.download(0.5, "约 30 秒")
    assert ui.windows.onboarding.last("download") == {"t": "download", "p": 0.5, "eta": "约 30 秒", "done": False, "error": False, "why": ""}


def test_finishing_the_guide_remembers_it_and_closes(ui) -> None:
    ui.windows.show_onboarding()
    window = ui.windows.onboarding
    ui.windows._onboarding_message({"t": "done"})
    assert ("pref", "onboarding_done", True) in ui.app.calls
    assert ("pref", "f5_hotkey", False) in ui.app.calls  # a new install is never read as one from before 0.4.0
    assert window.closed


def test_the_guide_switches_the_interface_language(ui) -> None:
    ui.windows.show_onboarding()
    ui.windows._onboarding_message({"t": "lang", "v": "en"})
    assert ("pref", "ui_language", "en") in ui.app.calls


def test_the_guide_retries_the_download_from_the_mirror(ui, monkeypatch) -> None:
    monkeypatch.setattr(ui.windows, "_model_cached", lambda: False)
    monkeypatch.setattr(reach, "in_mainland_china", lambda: False)
    monkeypatch.setattr(reach, "_USER_ENDPOINT", "")
    ui.windows.show_onboarding()
    assert ui.windows.onboarding_state()["model"]["mirror"] is False

    ui.windows._onboarding_message({"t": "source", "v": "mirror"})

    assert ("pref", "model_source", "mirror") in ui.app.calls and ("prefetch",) in ui.app.calls
    assert ui.windows.onboarding_state()["model"]["mirror"] is True


def test_settings_exports_diagnostics(ui) -> None:
    ui.windows._open("diagnostics")
    assert ("diagnostics",) in ui.app.calls


def test_feedback_goes_to_the_app_and_the_result_comes_back(ui) -> None:
    window = _open_settings(ui)
    ui.windows._settings_message({"t": "feedback", "message": " it crashed ", "email": "a@b.co", "diagnostics": True})
    assert ("feedback", "it crashed", "a@b.co", True) in ui.app.calls
    assert window.last("feedbackResult") == {"t": "feedbackResult", "ok": True, "msg": ""}
    ui.app.feedback_result = (False, "offline")
    ui.windows._settings_message({"t": "feedback", "message": "again"})
    assert window.last("feedbackResult") == {"t": "feedbackResult", "ok": False, "msg": "offline"}
    ui.windows._settings_message({"t": "feedback", "message": "  "})  # empty: nothing is sent
    assert [c for c in ui.app.calls if c[0] == "feedback"] == [("feedback", "it crashed", "a@b.co", True), ("feedback", "again", "", False)]


def test_about_state_carries_the_author_and_only_allow_listed_urls_open(ui, monkeypatch) -> None:
    window = _open_settings(ui)
    author = window.last("state")["author"]
    assert author["name"] == brand.AUTHOR_NAME == "Allen Shi" and author["github"] == brand.AUTHOR_GITHUB and "email" not in author
    opened = []
    monkeypatch.setattr(windows.permissions, "open_url", opened.append)
    ui.windows._open("releases")
    ui.windows._open("https://evil.example")
    assert opened == [brand.RELEASES_URL]
    assert "about" in windows.SETTINGS_PANES


# ----------------------------------------------------------------- pages


PAGES = {
    "settings": ({"ready", "set", "key", "migrate", "test", "vocab", "open", "count", "clear", "geo", "feedback"}, "_settings_message"),
    "history": ({"ready", "geo", "copy", "delete", "vocab", "open"}, "_history_message"),
    "onboarding": ({"ready", "mic", "a11y", "key", "download", "done", "lang", "source", "open", "meter"}, "_onboarding_message"),
}


@pytest.mark.parametrize("page", sorted(PAGES))
def test_each_page_loads_its_assets(page) -> None:
    html = (web_root() / f"{page}.html").read_text(encoding="utf-8")
    for name in ("kit.css", "win.css", "kit.js", f"{page}.js"):
        assert name in html
        assert (web_root() / name).is_file()


@pytest.mark.parametrize("page", sorted(PAGES))
def test_each_page_posts_only_what_its_controller_handles(page) -> None:
    import inspect

    source = (web_root() / f"{page}.js").read_text(encoding="utf-8")
    posted = set(re.findall(r"post\(\{ t: '([a-z0-9]+)'", source))
    expected, handler = PAGES[page]
    assert posted == expected
    body = inspect.getsource(getattr(windows.Windows, handler))
    handled = set(re.findall(r'kind == "([a-z0-9]+)"', body))
    assert posted <= handled


def test_settings_page_opens_the_panes_python_can_ask_for() -> None:
    source = (web_root() / "settings.js").read_text(encoding="utf-8")
    drawn = set(re.findall(r"\['([a-z]+)', \['[^']+', '[^']+'\], '[a-z]+', '#", source))
    assert drawn == set(windows.SETTINGS_PANES)


def test_the_guide_hears_keys_and_results_only_while_open(ui) -> None:
    ui.windows.guide({"t": "hotkey", "a": "primary_down"})  # never opened: nothing to tell
    ui.windows.show_onboarding()
    window = ui.windows.onboarding
    ui.windows.guide({"t": "result", "raw": "嗯明天开会", "text": "明天开会。"})
    assert window.last("result") == {"t": "result", "raw": "嗯明天开会", "text": "明天开会。"}
    window.close()
    window.sent.clear()
    ui.windows.guide({"t": "hotkey", "a": "primary_down"})
    assert window.sent == []


def test_the_level_meter_opens_the_microphone_only_while_asked(ui, monkeypatch) -> None:
    import sys

    streams = []

    class Stream:
        def __init__(self, callback, **kwargs) -> None:
            self.callback, self.open = callback, False
            streams.append(self)

        def start(self) -> None:
            self.open = True

        def stop(self) -> None:
            self.open = False

        def close(self) -> None:
            pass

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(InputStream=Stream))
    monkeypatch.setattr(permissions, "microphone_status", lambda: "authorized")
    ui.windows.show_onboarding()
    window = ui.windows.onboarding

    ui.windows._onboarding_message({"t": "meter", "on": True})
    ui.windows._onboarding_message({"t": "meter", "on": True})  # every redraw asks again
    assert len(streams) == 1
    import numpy as np

    streams[0].callback(np.array([[0.0], [0.25], [-0.5]]), 3, None, None)
    assert window.last("level") == {"t": "level", "v": 0.5}

    ui.windows._onboarding_message({"t": "meter", "on": False})
    assert not streams[0].open

    ui.windows._onboarding_message({"t": "meter", "on": True})
    window.close()  # the red button: the page never says stop
    streams[1].callback(np.array([[0.1]]), 1, None, None)
    assert not streams[1].open  # the next level finds the window gone and lets the microphone go
