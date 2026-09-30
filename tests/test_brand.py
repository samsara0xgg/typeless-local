from __future__ import annotations

from typeless_local import brand


def test_join_spaces_chinese_copy_like_the_style_guide() -> None:
    assert brand.join("退出", "言字") == "退出言字"
    assert brand.join("退出", "Yancy") == "退出 Yancy"
    assert brand.join("言字", "0.2.0") == "言字 0.2.0"
    assert brand.join("GPT-5.6", "Terra") == "GPT-5.6 Terra"
    assert brand.join("", "言字", None) == "言字"


def test_quit_label_uses_the_display_name() -> None:
    assert brand.quit_label() == f"退出{brand.DISPLAY_NAME}"


def test_bundle_id_is_unchanged_so_granted_permissions_survive_the_rename() -> None:
    assert brand.BUNDLE_ID == "com.alllllenshi.typlus"
