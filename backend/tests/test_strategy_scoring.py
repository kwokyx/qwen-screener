from datetime import date, timedelta

from app.models.stock import StockBasic, StockDaily
from app.services import strategy_selector


def _point(index: int, *, close=10.0, high=10.0, open_=9.8, amount=2e8):
    return strategy_selector.DailyPoint(
        code="000001.SZ",
        name="测试股票",
        industry="银行",
        market="主板",
        trade_date=date(2026, 5, 1) + timedelta(days=index),
        open=open_,
        high=high,
        low=9.5,
        close=close,
        volume=1e7,
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
