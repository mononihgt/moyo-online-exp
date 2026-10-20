from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.models import GameTrial, Room
from app.schemas import MapPaymentInput
from app.services.payment_lists import parse_date_range, range_bounds
from app.services.payments import _payment_from_snapshot, compute_performance_cents


def _payment(**overrides) -> dict:
    data = {
        "basePayCents": 4500,
        "performanceRateCents": 1,
        "performanceFloorCents": 0,
        "performanceCapCents": 2000,
        "showupPayCents": 1000,
    }
    data.update(overrides)
    return data


def _trial(
    *,
    player1: int | None = None,
    player2: int | None = None,
    practice: bool = False,
    ended: bool = True,
    summary: dict | None = None,
) -> GameTrial:
    if summary is None:
        finals = {}
        if player1 is not None:
            finals["player1"] = player1
        if player2 is not None:
            finals["player2"] = player2
        summary = {"finalSoldiers": finals}
    return GameTrial(
        is_practice=practice,
        ended_at=datetime(2026, 10, 19, 12, 0, 0) if ended else None,
        summary_json=summary,
    )


def test_default_payment_parameters():
    payment = MapPaymentInput()
    assert payment.base_pay_cents == 1000
    assert payment.performance_rate_cents == 1
    assert payment.performance_floor_cents == 3500
    assert payment.performance_cap_cents == 5500
    assert payment.showup_pay_cents == 1000


def test_performance_floors_to_whole_yuan():
    # 平均 1000.5 士兵，单价 1 分，得到 10.005 元，按元向下取整为 10 元
    trials = [_trial(player1=1000), _trial(player1=1001)]
    assert compute_performance_cents(Room(), trials, 1, payment=_payment()) == 1000


def test_performance_floors_small_means_to_zero():
    trials = [_trial(player1=99), _trial(player1=100)]
    assert compute_performance_cents(Room(), trials, 1, payment=_payment()) == 0


def test_performance_is_capped():
    trials = [_trial(player1=1000), _trial(player1=1000)]
    payment = _payment(performanceRateCents=10, performanceCapCents=2000)
    assert compute_performance_cents(Room(), trials, 1, payment=payment) == 2000


def test_performance_uses_floor_and_cap():
    low = [_trial(player1=100)]
    middle = [_trial(player1=4000)]
    high = [_trial(player1=10000)]
    payment = _payment(
        performanceFloorCents=3500,
        performanceCapCents=5500,
    )
    assert compute_performance_cents(Room(), low, 1, payment=payment) == 3500
    assert compute_performance_cents(Room(), middle, 1, payment=payment) == 4000
    assert compute_performance_cents(Room(), high, 1, payment=payment) == 5500


def test_performance_floor_defaults_to_zero_for_legacy_snapshot():
    snapshot = {
        "mapGroup": {
            "payment": {
                "basePayCents": 4500,
                "performanceRateCents": 1,
                "performanceCapCents": 2000,
                "showupPayCents": 1000,
            }
        }
    }
    payment = _payment_from_snapshot(snapshot)
    assert payment is not None
    assert payment["performanceFloorCents"] == 0


def test_performance_uses_role_specific_totals():
    trials = [_trial(player1=1000, player2=300), _trial(player1=1001, player2=301)]
    assert compute_performance_cents(Room(), trials, 1, payment=_payment()) == 1000
    assert compute_performance_cents(Room(), trials, 2, payment=_payment()) == 300


def test_performance_excludes_practice_and_unfinished_trials():
    trials = [
        _trial(player1=999999, practice=True),
        _trial(player1=999999, ended=False),
        _trial(summary={"finalSoldiers": {}}),
        _trial(player1=200),
        _trial(player1=201),
    ]
    assert compute_performance_cents(Room(), trials, 1, payment=_payment()) == 200


def test_performance_requires_ended_formal_trials():
    assert compute_performance_cents(Room(), [], 1, payment=_payment()) is None
    practice_only = [_trial(player1=1000, practice=True)]
    assert compute_performance_cents(Room(), practice_only, 1, payment=_payment()) is None
    missing_role = [_trial(player2=1000)]
    assert compute_performance_cents(Room(), missing_role, 1, payment=_payment()) is None


def test_parse_date_range_accepts_iso_dates():
    assert parse_date_range("2026-10-01", "2026-10-02") == (
        date(2026, 10, 1),
        date(2026, 10, 2),
    )
    assert parse_date_range("2026-10-01", "2026-10-01") == (
        date(2026, 10, 1),
        date(2026, 10, 1),
    )


@pytest.mark.parametrize(
    ("from_value", "to_value"),
    [
        ("2026-1-01", "2026-01-02"),
        ("2026/01/01", "2026-01-02"),
        ("", "2026-01-02"),
        ("2026-01-01", ""),
        ("2026-02-30", "2026-03-01"),
        ("2026-13-01", "2026-13-02"),
        (None, "2026-01-02"),
    ],
)
def test_parse_date_range_rejects_invalid_format(from_value, to_value):
    with pytest.raises(HTTPException) as excinfo:
        parse_date_range(from_value, to_value)
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "日期格式必须为 YYYY-MM-DD"


def test_parse_date_range_rejects_reversed_order():
    with pytest.raises(HTTPException) as excinfo:
        parse_date_range("2026-10-02", "2026-10-01")
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "开始日期不能晚于结束日期"


def test_range_bounds_use_beijing_midnight():
    start, end = range_bounds(date(2026, 10, 1), date(2026, 10, 2))
    assert start == datetime(2026, 9, 30, 16, 0, 0)
    assert end == datetime(2026, 10, 2, 16, 0, 0)


def test_range_bounds_cover_single_day_inclusively():
    start, end = range_bounds(date(2026, 12, 31), date(2026, 12, 31))
    assert start == datetime(2026, 12, 30, 16, 0, 0)
    assert end == datetime(2026, 12, 31, 16, 0, 0)
    assert end - start == timedelta(days=1)
