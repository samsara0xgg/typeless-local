from __future__ import annotations

from types import SimpleNamespace

from typeless_local import app as app_module, feedback

KEY = "sk-proj-abcdefghijklmnop1234"


def test_build_has_the_fixed_fields_and_diagnostics_only_when_given(monkeypatch) -> None:
    monkeypatch.setattr(feedback, "mac_model", lambda: "Mac14,2")
    body = feedback.build(" hi ", " a@b.co ", version="1.0", spoken_language="", ui_language="en")
    assert body["message"] == "hi" and body["email"] == "a@b.co" and body["spoken_language"] == "auto"
    assert {"version", "macos", "model", "ui_language"} <= set(body) and "diagnostics" not in body
    assert feedback.build("x" * 5000, "", version="1", spoken_language="zh", ui_language="zh", extra="d")["diagnostics"] == "d"
    assert len(body["message"]) <= feedback.MAX_MESSAGE
    assert len(feedback.build("x" * 5000, "", version="1", spoken_language="", ui_language="en")["message"]) == 4000


def test_diagnostics_redact_keys_keep_the_last_lines_and_stay_under_the_limit(tmp_path) -> None:
    log = tmp_path / "app.log"
    log.write_text("".join(f"line {i} {'x' * 400}\n" for i in range(1000)) + f"newest key {KEY}\n")
    text = feedback.diagnostics_text({"keys_set": {"A": True}, "note": KEY}, log, [KEY])
    assert KEY not in text
    assert "newest key [key removed]" in text and "line 0 " not in text
    assert len(text.encode()) <= feedback.MAX_DIAGNOSTICS_BYTES
    # A summary that alone is too big is cut rather than refused.
    huge = feedback.diagnostics_text({"big": "y" * 60_000}, log, [])
    assert len(huge.encode()) <= feedback.MAX_DIAGNOSTICS_BYTES


def test_send_feedback_posts_to_the_worker_and_reports_failure(tmp_path, monkeypatch) -> None:
    app = object.__new__(app_module.TypelessLocalApp)
    app.config = SimpleNamespace(jarvis_config={"asr": {"language": "zh"}}, user_paths=SimpleNamespace(log_path=tmp_path / "app.log"))
    app._worker_url = lambda path: f"https://w.example/{path}"
    app._diagnostic_summary = lambda: {"k": KEY}
    monkeypatch.setattr(app_module, "api_key_names", lambda config: [])
    monkeypatch.setattr(app_module.threading, "Thread", lambda target, **kw: SimpleNamespace(start=target))
    (tmp_path / "app.log").write_text(f"hello {KEY}\n")
    sent, results = [], []
    monkeypatch.setattr(feedback, "post", lambda url, body: sent.append((url, body)))

    app.send_feedback("it broke", "a@b.co", True, lambda ok, msg: results.append((ok, msg)))
    url, body = sent[0]
    assert url == "https://w.example/feedback" and results == [(True, "")]
    assert body["message"] == "it broke" and body["spoken_language"] == "zh" and "[key removed]" in body["diagnostics"]
    assert KEY not in body["diagnostics"]

    app.send_feedback("plain", "", False, lambda ok, msg: results.append((ok, msg)))
    assert "diagnostics" not in sent[1][1]

    def boom(url, body):
        raise OSError("down")

    monkeypatch.setattr(feedback, "post", boom)
    app.send_feedback("again", "", False, lambda ok, msg: results.append((ok, msg)))
    assert results[-1][0] is False and results[-1][1]
    app._worker_url = lambda path: ""  # no server configured
    app.send_feedback("again", "", False, lambda ok, msg: results.append((ok, msg)))
    assert results[-1][0] is False
