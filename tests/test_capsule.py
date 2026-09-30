from __future__ import annotations

from typeless_local.capsule import RESUME_MIN_S, Capsule


class _Overlay:
    def __init__(self) -> None:
        self.calls = []

    def show(self, state, **data) -> None:
        self.calls.append((state, data))

    def hide(self) -> None:
        self.calls.append(("hidden", {}))


class _Timer:
    made: list["_Timer"] = []

    def __init__(self, delay, callback) -> None:
        self.delay, self.callback, self.cancelled, self.daemon = delay, callback, False, False
        _Timer.made.append(self)

    def start(self) -> None:
        pass

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


def _capsule(clock=lambda: 0.0):
    _Timer.made = []
    overlay = _Overlay()
    return Capsule(overlay, lambda fn, *a, **k: fn(*a, **k), timer=_Timer, clock=clock), overlay


def test_finished_states_go_away_by_themselves() -> None:
    capsule, overlay = _capsule()
    capsule.show("copied")

    (timer,) = _Timer.made
    assert timer.delay == 1.4
    timer.fire()

    assert overlay.calls == [("copied", {}), ("hidden", {})]
    assert capsule.state == "hidden"


def test_states_in_progress_stay_until_replaced() -> None:
    capsule, _ = _capsule()
    capsule.show("rec", mode="click")
    capsule.show("transcribing")
    assert _Timer.made == []


def test_inserted_follows_the_users_setting() -> None:
    capsule, _ = _capsule()
    capsule.inserted_dismiss_s = 10.0
    capsule.show("inserted", n=3)
    assert _Timer.made[-1].delay == 10.0


def test_a_late_timer_never_takes_down_a_newer_state() -> None:
    capsule, overlay = _capsule()
    capsule.show("empty")
    capsule.show("rec", mode="click")

    _Timer.made[0].callback()  # even if cancel() lost the race

    assert overlay.calls[-1] == ("rec", {"mode": "click"})
    assert capsule.state == "rec"


def test_hover_holds_and_resumes_with_time_to_read() -> None:
    now = [0.0]
    capsule, overlay = _capsule(clock=lambda: now[0])
    capsule.show("inserted", n=5)  # 4 s
    now[0] = 3.5
    capsule.set_hover(True)
    assert _Timer.made[0].cancelled
    now[0] = 30.0
    capsule.set_hover(False)

    resumed = _Timer.made[-1]
    assert resumed.delay == RESUME_MIN_S
    resumed.fire()
    assert overlay.calls[-1] == ("hidden", {})


def test_a_state_shown_while_hovering_waits_for_the_pointer_to_leave() -> None:
    capsule, _ = _capsule()
    capsule.set_hover(True)
    capsule.show("undone")
    assert _Timer.made == []
    capsule.set_hover(False)
    assert _Timer.made[-1].delay == 1.2


def test_hide_if_only_hides_the_named_states() -> None:
    capsule, overlay = _capsule()
    capsule.show("edit-modify", text="x")
    assert capsule.hide_if("inserted") is False
    assert capsule.hide_if("edit-modify") is True
    assert overlay.calls[-1] == ("hidden", {})


def test_without_an_overlay_it_only_keeps_state() -> None:
    capsule = Capsule(None, lambda fn, *a, **k: fn(*a, **k), timer=_Timer)
    capsule.show("inserted", n=1)
    capsule.update_level(0.5)
    capsule.set_handle(True)
    capsule.hide()
    assert capsule.state == "hidden"
