from __future__ import annotations

from typeless_local import brand


def test_join_spaces_chinese_copy_like_the_style_guide() -> None:
    assert brand.join("退出", "言字") == "退出言字"
    assert brand.join("退出", "Yana") == "退出 Yana"
    assert brand.join("言字", "0.2.0") == "言字 0.2.0"
    assert brand.join("GPT-5.6", "Terra") == "GPT-5.6 Terra"
    assert brand.join("", "言字", None) == "言字"


def test_quit_label_uses_the_display_name() -> None:
    assert brand.quit_label() == f"退出{brand.DISPLAY_NAME}"


def test_bundle_id_is_unchanged_so_granted_permissions_survive_the_rename() -> None:
    assert brand.BUNDLE_ID == "com.alllllenshi.typlus"


def test_the_english_interface_uses_the_english_name() -> None:
    from typeless_local import i18n

    i18n.use("en")
    assert brand.display_name() == brand.ENGLISH_NAME
    assert brand.quit_label() == f"Quit {brand.ENGLISH_NAME}"
    i18n.use("zh")
    assert brand.display_name() == brand.DISPLAY_NAME


def test_auto_follows_the_macs_language(monkeypatch) -> None:
    from typeless_local import i18n

    monkeypatch.setattr(i18n, "system_language", lambda: "en")
    assert i18n.use("auto") == "en"
    monkeypatch.setattr(i18n, "system_language", lambda: "zh")
    assert i18n.use("auto") == "zh"
    assert i18n.use("klingon") == "zh"
