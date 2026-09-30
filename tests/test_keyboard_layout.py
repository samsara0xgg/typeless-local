from __future__ import annotations

from typeless_local import keyboard_layout

# What each layout types at a few keycodes with Command held.
QWERTY = {6: "z", 9: "v", 13: "w"}
AZERTY = {6: "w", 9: "v", 13: "z"}
DVORAK = {6: ";", 9: "k", 44: "z", 47: "v"}
CYRILLIC = {6: "я", 9: "м"}


def _translate(table):
    return lambda code: table.get(code, "")


def test_finds_the_keys_that_type_v_and_z() -> None:
    assert keyboard_layout.find_letters(_translate(QWERTY)) == {"z": 6, "v": 9}
    assert keyboard_layout.find_letters(_translate(AZERTY)) == {"v": 9, "z": 13}
    assert keyboard_layout.find_letters(_translate(DVORAK)) == {"z": 44, "v": 47}


def test_capital_letters_count_and_the_first_key_wins() -> None:
    assert keyboard_layout.find_letters(_translate({3: "V", 9: "v", 6: "z"})) == {"v": 3, "z": 6}


def test_a_layout_without_latin_letters_falls_back_to_qwerty(monkeypatch) -> None:
    monkeypatch.setattr(keyboard_layout, "_read_layout", lambda: keyboard_layout.find_letters(_translate(CYRILLIC)))
    monkeypatch.setattr(keyboard_layout, "_codes", {"v": 47, "z": 44})

    assert keyboard_layout.refresh() == keyboard_layout.QWERTY
    assert keyboard_layout.keycode("v") == 9


def test_refresh_keeps_the_last_layout_when_it_cannot_read_one(monkeypatch) -> None:
    def broken():
        raise OSError("no Carbon here")

    monkeypatch.setattr(keyboard_layout, "_read_layout", broken)
    monkeypatch.setattr(keyboard_layout, "_codes", {"v": 47, "z": 44})

    keyboard_layout.refresh()

    assert (keyboard_layout.keycode("v"), keyboard_layout.keycode("z")) == (47, 44)


def test_refresh_uses_the_layout_it_reads(monkeypatch) -> None:
    monkeypatch.setattr(keyboard_layout, "_read_layout", lambda: keyboard_layout.find_letters(_translate(AZERTY)))
    monkeypatch.setattr(keyboard_layout, "_codes", dict(keyboard_layout.QWERTY))

    keyboard_layout.refresh()

    assert keyboard_layout.keycode("z") == 13
