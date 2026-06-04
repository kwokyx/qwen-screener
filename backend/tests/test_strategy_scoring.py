from datetime import date, timedelta

import pytest

from app.models.stock import StockBasic, StockDaily
from app.services import strategy_selector


def _point(
    index: int,
    *,
    close=10.0,
    high=None,
    low=None,
    open_=9.8,
    volume=1e7,
    amount=2e8,
):
    return strategy_selector.DailyPoint(
        code="000001.SZ",
        name="测试股票",
        industry="银行",
        market="主板",
        trade_date=date(2026, 5, 1) + timedelta(days=index),
        open=open_,
        high=high if high is not None else close,
        low=low if low is not None else min(9.5, close),
        close=close,
        volume=volume,
        amount=amount,
    )


def test_amount_yi_converts_yuan_to_hundred_million():
    assert strategy_selector._amount_yi(_point(0, amount=12e9)) == 120


def test_turtle_breakout_score_is_bounded_and_keeps_amount_metric():
    points = [_point(i) for i in range(20)]
    points.append(_point(20, close=11, high=11, open_=10.5, amount=12e9))

    items = strategy_selector._eval_turtle_breakout({"000001.SZ": points})

    assert len(items) == 1
    assert items[0].score == 100
    assert items[0].metrics["成交额(亿)"] == 120


def test_turtle_breakout_requires_amount_strictly_above_hundred_million():
    points = [_point(i) for i in range(20)]
    points.append(_point(20, close=11, high=11, open_=10.5, amount=1e8))

    assert strategy_selector._eval_turtle_breakout({"000001.SZ": points}) == []


def test_ma_volume_requires_strict_golden_cross():
    points = [_point(i, close=10, volume=100) for i in range(20)]
    points.append(_point(20, close=12, volume=1000))

    assert strategy_selector._eval_ma_volume({"000001.SZ": points}) == []


def test_ma_volume_selects_strict_cross_with_current_day_volume_window():
    points = [
        *[_point(i, close=11, high=11, volume=100) for i in range(15)],
        *[_point(i, close=9, high=9, volume=100) for i in range(15, 20)],
        _point(20, close=50, high=50, volume=1000),
    ]

    items = strategy_selector._eval_ma_volume({"000001.SZ": points})

    assert len(items) == 1
    assert items[0].signals == ["5日均线上穿20日均线", "成交量放大"]
    assert items[0].metrics["量比20日"] > 1.5


def test_rps_rank_matches_average_pct_rank_for_ties():
    assert strategy_selector._pct_rank([1, 2, 2, 4], 2) == pytest.approx(62.5)


def test_limit_up_shakeout_selects_support_hold_pattern():
    points = [
        _point(0, close=10, high=10.2, low=9.8, open_=9.9, volume=100),
        _point(1, close=10.95, high=10.95, low=10.5, open_=10.4, volume=100),
        _point(2, close=11.2, high=11.8, low=10.95, open_=11.6, volume=250),
    ]

    items = strategy_selector._eval_limit_up_shakeout({"000001.SZ": points})

    assert len(items) == 1
    assert items[0].signals == ["昨日强势涨停", "今日放量收阴", "支撑不破"]


def test_limit_up_shakeout_rejects_broken_support():
    points = [
        _point(0, close=10, high=10.2, low=9.8, open_=9.9, volume=100),
        _point(1, close=10.95, high=10.95, low=10.5, open_=10.4, volume=100),
        _point(2, close=11.2, high=11.8, low=10.94, open_=11.6, volume=250),
    ]

    assert strategy_selector._eval_limit_up_shakeout({"000001.SZ": points}) == []


def test_uptrend_limit_down_selects_volume_drop_in_uptrend():
    points = [
        _point(i, close=10 + i * 0.1, high=10.5 + i * 0.1, low=9.5 + i * 0.1, volume=100)
        for i in range(60)
    ]
    prev_close = points[-1].close
    points.append(_point(60, close=prev_close * 0.9, high=prev_close, low=prev_close * 0.88, volume=1000))

    items = strategy_selector._eval_uptrend_limit_down({"000001.SZ": points})

    assert len(items) == 1
    assert items[0].signals == ["上升趋势", "放量急跌", "修复观察"]
    assert items[0].metrics["量比20日"] > 2


def test_strategy_templates_include_six_daily_strategies():
    ids = {template.id for template in strategy_selector.list_templates()}

    assert {
        "turtle_breakout",
        "ma_volume",
        "rps_breakout",
        "high_tight_flag",
        "limit_up_shakeout",
        "uptrend_limit_down",
    } <= ids


def test_base_item_clamps_score_to_display_range():
    points = [_point(0), _point(1)]

    assert strategy_selector._base_item(points, 999999, [], {}).score == 100
    assert strategy_selector._base_item(points, -1, [], {}).score == 0


def test_load_histories_excludes_stocks_with_recent_gaps(db):
    start = date(2026, 5, 27)
    db.add_all([
        StockBasic(code="000001.SZ", name="完整股票"),
        StockBasic(code="000002.SZ", name="缺口股票"),
    ])
    for offset in range(3):
        trade_date = start + timedelta(days=offset)
        db.add(StockDaily(
            code="000001.SZ", trade_date=trade_date, close=10 + offset,
            high=10 + offset, low=9 + offset, amount=2e8,
        ))
    db.add(StockDaily(
        code="000002.SZ", trade_date=start + timedelta(days=2),
        close=12, high=12, low=11, amount=3e8,
    ))
    db.commit()

    histories = strategy_selector._load_histories(db, days=3)

    assert list(histories) == ["000001.SZ"]
