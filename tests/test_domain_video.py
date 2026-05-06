from __future__ import annotations

# 尺調整とffmpeg atempo分解の計算を確認する。
import pytest

from domain.errors import AppError
from domain.video import atempo_filter, calc_duration_scale, max_duration_sec


def test_max_duration_sec() -> None:
    assert max_duration_sec(10.0, 30.0) == 10.0
    assert max_duration_sec(None, 30.0) == 30.0
    assert max_duration_sec(None, 0.0) is None
    assert max_duration_sec(-1.0, 30.0) is None


def test_calc_duration_scale() -> None:
    assert calc_duration_scale(10.0, None) == 1.0
    assert calc_duration_scale(0.0, 5.0) == 1.0
    assert calc_duration_scale(5.0, 10.0) == 1.0
    assert calc_duration_scale(10.0, 5.0) == 0.5


def test_atempo_filter() -> None:
    assert atempo_filter(1.0) == "atempo=1.000000"
    assert atempo_filter(4.0) == "atempo=2.0,atempo=2.000000"
    assert atempo_filter(0.25) == "atempo=0.5,atempo=0.500000"
    with pytest.raises(AppError, match="Invalid speed for atempo"):
        atempo_filter(0.0)
