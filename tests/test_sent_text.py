from __future__ import annotations

from typeless_local.sent_text import FIND_S, MAX_CHARS, POLL_S, WATCH_S, SentTextWatcher


class Field:
    """A text field that changes on schedule: [(after seconds, value, front pid)]."""

    def __init__(self, script) -> None:
        self.script = script
        self.t = 0.0
        self.sent: list[tuple[int, str]] = []

    def _now(self):
        state = self.script[0]
        for step in self.script:
            if step[0] <= self.t:
                state = step
        return state

    def read(self, pid):
        return self._now()[1]

    def front(self):
        return self._now()[2]

    def sleep(self, s):
        self.t += s

    def clock(self):
        return self.t

    def watcher(self):
        return SentTextWatcher(self.read, self.front, lambda row, text: self.sent.append((row, text)), sleep=self.sleep, clock=self.clock)


PASTED = "明天下午四点开会，记得带电脑。"


def test_an_edit_then_enter_is_kept_as_sent() -> None:
    field = Field([(0, "", 7), (0.3, PASTED, 7), (5, "明天下午三点开会，记得带电脑。", 7), (9, "", 7)])
    field.watcher().watch(11, PASTED, 7, background=False)
    assert field.sent == [(11, "明天下午三点开会，记得带电脑。")]


def test_sent_unchanged_is_kept_too() -> None:
    field = Field([(0, PASTED, 7), (3, "", 7)])
    field.watcher().watch(11, PASTED, 7, background=False)
    assert field.sent == [(11, PASTED)]


def test_moving_to_another_app_keeps_an_edited_field_only() -> None:
    edited = Field([(0, PASTED, 7), (2, PASTED + "谢谢", 7), (4, None, 9)])
    edited.watcher().watch(11, PASTED, 7, background=False)
    assert edited.sent == [(11, PASTED + "谢谢")]

    untouched = Field([(0, PASTED, 7), (4, None, 9)])
    untouched.watcher().watch(11, PASTED, 7, background=False)
    assert untouched.sent == []


def test_a_field_that_cannot_be_read_or_is_a_document_is_left_alone() -> None:
    unreadable = Field([(0, None, 7)])
    unreadable.watcher().watch(11, PASTED, 7, background=False)
    assert unreadable.sent == [] and unreadable.t < FIND_S + 2 * POLL_S

    document = Field([(0, "x" * MAX_CHARS + PASTED, 7), (3, "", 7)])
    document.watcher().watch(11, PASTED, 7, background=False)
    assert document.sent == []


def test_it_gives_up_after_the_watch_window() -> None:
    field = Field([(0, PASTED, 7), (WATCH_S + 5, "", 7)])
    field.watcher().watch(11, PASTED, 7, background=False)
    assert field.sent == []


def test_a_new_dictation_cancels_the_watch() -> None:
    field = Field([(0, PASTED, 7), (3, "", 7)])
    watcher = field.watcher()
    original = field.sleep

    def sleep(s):
        original(s)
        if field.t > 1:
            watcher.cancel()

    watcher._sleep = sleep
    watcher.watch(11, PASTED, 7, background=False)
    assert field.sent == []


def test_nothing_to_watch_without_a_row_or_a_process() -> None:
    field = Field([(0, PASTED, 7)])
    watcher = field.watcher()
    watcher.watch(None, PASTED, 7, background=False)
    watcher.watch(11, PASTED, 0, background=False)
    watcher.watch(11, "  ", 7, background=False)
    assert field.t == 0 and field.sent == []
