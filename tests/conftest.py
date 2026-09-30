from __future__ import annotations

import pytest

from typeless_local import i18n


@pytest.fixture(autouse=True)
def _chinese_by_default():
    """Every test starts in Chinese, whatever the machine's language or the last test chose."""

    i18n.use("zh")
    yield
    i18n.use("zh")
