from datetime import date, timedelta

import pandas as pd
import pytest

from app.services import strategy_selector
from app.services.strategies import STRATEGIES, STRATEGY_REGISTRY


def _make_df(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount", "name", "industry", "market"])
    defaults = {
        "symbol": "000001.SZ",
        "date": date(2026, 5, 1),
        "open": 9.8,
        "high": 10.0,
        "low": 9.5,
        "close": 10.0,
        "volume": 1e7,
        "amount": 2e8,
        "name": "测试股票",
        "industry": "银行",
        "market": "主板",
    }
    rows = []
    for i, rec in enumerate(records):
        row = {**defaults, **rec}
        if "date" not in rec:
            row["date"] = date(2026, 5, 1) + timedelta(days=i)
        rows.append(row)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _build_turtle_points(n=21, *, final_close=11.0, final_high=11.0, final_open=10.5, final_amount=12e9):
    pts = []
    for i in range(n - 1):
        pts.append({"close": 10.0, "high": 10.0, "low": 9.5, "open": 9.8, "volume": 1e7, "amount": 2e8})
    pts.append({
        "close": final_close, "high": final_high, "low": 10.0,
        "open": final_open, "volume": 1e7, "amount": final_amount,
    })
    return _make_df(pts)


def test_turtle_breakout_score_is_bounded_and_keeps_amount_metric():
    df = _build_turtle_points()
    items = STRATEGY_REGISTRY["turtle_breakout"].run(df)
    assert len(items) == 1
    assert items[0].score == 100
    assert items[0].metrics["成交额(亿)"] == 120


def test_turtle_breakout_requires_amount_strictly_above_hundred_million():
    df = _build_turtle_points(final_amount=1e8)
    assert STRATEGY_REGISTRY["turtle_breakout"].run(df) == []


def test_ma_volume_requires_strict_golden_cross():
    pts = [{"close": 10.0, "volume": 100} for _ in range(21)]
    pts[-1] = {"close": 12.0, "volume": 1000}
    df = _make_df(pts)
    assert STRATEGY_REGISTRY["ma_volume"].run(df) == []


def test_ma_volume_selects_strict_cross_with_current_day_volume_window():
    pts = (
        [{"close": 11.0, "high": 11.0, "volume": 100} for _ in range(15)]
        + [{"close": 9.0, "high": 9.0, "volume": 100} for _ in range(5)]
    )
    pts.append({"close": 50.0, "high": 50.0, "volume": 1000})
    df = _make_df(pts)
    items = STRATEGY_REGISTRY["ma_volume"].run(df)
    assert len(items) == 1
    assert items[0].signals == ["5日均线上穿20日均线", "成交量放大"]
    assert items[0].metrics["量比20日"] > 1.5


def test_limit_up_shakeout_selects_support_hold_pattern():
    pts = [
        {"close": 10.0, "high": 10.2, "low": 9.8, "open": 9.9, "volume": 100},
        {"close": 10.95, "high": 10.95, "low": 10.5, "open": 10.4, "volume": 100},
        {"close": 11.2, "high": 11.8, "low": 10.95, "open": 11.6, "volume": 250},
    ]
    df = _make_df(pts)
    items = STRATEGY_REGISTRY["limit_up_shakeout"].run(df)
    assert len(items) == 1
    assert items[0].signals == ["昨日强势涨停", "今日放量收阴", "支撑不破"]


def test_limit_up_shakeout_rejects_broken_support():
    pts = [
        {"close": 10.0, "high": 10.2, "low": 9.8, "open": 9.9, "volume": 100},
        {"close": 10.95, "high": 10.95, "low": 10.5, "open": 10.4, "volume": 100},
        {"close": 11.2, "high": 11.8, "low": 10.94, "open": 11.6, "volume": 250},
    ]
    df = _make_df(pts)
    assert STRATEGY_REGISTRY["limit_up_shakeout"].run(df) == []


def test_uptrend_limit_down_selects_volume_drop_in_uptrend():
    pts = [{"close": 10.0 + i * 0.1, "high": 10.5 + i * 0.1, "low": 9.5 + i * 0.1, "volume": 100} for i in range(60)]
    prev_close = pts[-1]["close"]
    pts.append({"close": prev_close * 0.9, "high": prev_close, "low": prev_close * 0.88, "volume": 1000})
    df = _make_df(pts)
    items = STRATEGY_REGISTRY["uptrend_limit_down"].run(df)
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


def test_strategy_classes_return_empty_for_empty_histories():
    for strategy in STRATEGIES:
        assert strategy.run(_make_df([])) == []


def test_strategy_registry_matches_templates_and_history_options():
    template_ids = [template.id for template in strategy_selector.list_templates()]
    assert template_ids == [strategy.id for strategy in STRATEGIES]
    assert set(STRATEGY_REGISTRY) == set(template_ids)
    for strategy in STRATEGIES:
        assert strategy_selector._STRATEGY_HISTORY_OPTIONS[strategy.id] == strategy.history_days


def test_run_strategy_selection_supports_all_registered_strategies(db, monkeypatch):
    strategy_selector.clear_strategy_cache()
    monkeypatch.setattr(strategy_selector, "_latest_strategy_trade_date", lambda _db: date(2026, 6, 4))
    monkeypatch.setattr(strategy_selector, "_load_histories", lambda *_args, **_kwargs: _make_df([]))

    for strategy in STRATEGIES:
        response = strategy_selector.run_strategy_selection(db, strategy.id, limit=5)
        assert response.strategy.id == strategy.id
        assert response.total == 0
        assert response.items == []


def test_run_strategy_selection_rejects_unknown_strategy(db):
    with pytest.raises(ValueError, match="未知策略"):
        strategy_selector.run_strategy_selection(db, "unknown_strategy", limit=5)


def test_strategy_cache_reuses_full_result_across_limits(db, monkeypatch):
    from app.models.stock import StockBasic, StockDaily

    strategy_selector.clear_strategy_cache()
    db.add(StockBasic(code="000001.SZ", name="测试股票", industry="银行"))
    db.add(StockDaily(code="000001.SZ", trade_date=date(2026, 6, 4), close=10, high=10, low=9, amount=2e8))
    db.commit()
    load_calls = 0

    def fake_load(_db, days):
        nonlocal load_calls
        load_calls += 1
        return _make_df([])

    monkeypatch.setattr(strategy_selector, "_load_histories", fake_load)
    monkeypatch.setattr(
        STRATEGY_REGISTRY["turtle_breakout"],
        "run",
        lambda _df: [
            strategy_selector.StrategyPickItem(code="000001.SZ", name="A", trade_date=date(2026, 6, 4), close=10, score=90, signals=["a"], metrics={}),
            strategy_selector.StrategyPickItem(code="000002.SZ", name="B", trade_date=date(2026, 6, 4), close=10, score=80, signals=["b"], metrics={}),
            strategy_selector.StrategyPickItem(code="000003.SZ", name="C", trade_date=date(2026, 6, 4), close=10, score=70, signals=["c"], metrics={}),
        ],
    )

    first = strategy_selector.run_strategy_selection(db, "turtle_breakout", limit=1)
    second = strategy_selector.run_strategy_selection(db, "turtle_breakout", limit=3)

    assert load_calls == 1
    assert first.total == 3
    assert [item.code for item in first.items] == ["000001.SZ"]
    assert [item.code for item in second.items] == ["000001.SZ", "000002.SZ", "000003.SZ"]


def test_strategy_selection_pushes_feishu_for_each_call_including_cache(db, monkeypatch):
    from app.models.stock import StockBasic, StockDaily

    strategy_selector.clear_strategy_cache()
    db.add(StockBasic(code="000001.SZ", name="测试股票", industry="银行"))
    db.add(StockDaily(code="000001.SZ", trade_date=date(2026, 6, 4), close=10, high=10, low=9, amount=2e8))
    db.commit()
    load_calls = 0
    pushes = []

    def fake_load(_db, days):
        nonlocal load_calls
        load_calls += 1
        return _make_df([])

    monkeypatch.setattr(strategy_selector, "_load_histories", fake_load)
    monkeypatch.setattr(strategy_selector, "_start_daemon_thread", lambda target, *args: target(*args))
    monkeypatch.setattr(strategy_selector.feishu, "push_strategy_result", lambda name, items: pushes.append((name, items)))
    monkeypatch.setattr(
        STRATEGY_REGISTRY["turtle_breakout"],
        "run",
        lambda _df: [
            strategy_selector.StrategyPickItem(code="000001.SZ", name="A", trade_date=date(2026, 6, 4), close=10, score=90, signals=["a"], metrics={}),
            strategy_selector.StrategyPickItem(code="000002.SZ", name="B", trade_date=date(2026, 6, 4), close=10, score=80, signals=["b"], metrics={}),
        ],
    )

    first = strategy_selector.run_strategy_selection(db, "turtle_breakout", limit=1)
    second = strategy_selector.run_strategy_selection(db, "turtle_breakout", limit=2)
    third = strategy_selector.run_strategy_selection(db, "turtle_breakout", limit=2, notify=False)

    assert load_calls == 1
    assert [item.code for item in first.items] == ["000001.SZ"]
    assert [item.code for item in second.items] == ["000001.SZ", "000002.SZ"]
    assert [item.code for item in third.items] == ["000001.SZ", "000002.SZ"]
    assert len(pushes) == 2
    assert [item["code"] for item in pushes[0][1]] == ["000001.SZ"]
    assert [item["code"] for item in pushes[1][1]] == ["000001.SZ", "000002.SZ"]


def test_strategy_singleflight_failure_releases_inflight_and_allows_retry(db, monkeypatch):
    from app.models.stock import StockBasic, StockDaily

    strategy_selector.clear_strategy_cache()
    db.add(StockBasic(code="000001.SZ", name="测试股票", industry="银行"))
    db.add(StockDaily(code="000001.SZ", trade_date=date(2026, 6, 4), close=10, high=10, low=9, amount=2e8))
    db.commit()
    calls = 0

    monkeypatch.setattr(strategy_selector, "_load_histories", lambda *_args, **_kwargs: _make_df([]))

    def flaky_run(_df):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        return [strategy_selector.StrategyPickItem(code="000001.SZ", name="A", trade_date=date(2026, 6, 4), close=10, score=90, signals=["a"], metrics={})]

    monkeypatch.setattr(STRATEGY_REGISTRY["turtle_breakout"], "run", flaky_run)

    with pytest.raises(RuntimeError, match="boom"):
        strategy_selector.run_strategy_selection(db, "turtle_breakout", limit=1)

    retry = strategy_selector.run_strategy_selection(db, "turtle_breakout", limit=1)

    assert retry.total == 1
    assert calls == 2
    assert strategy_selector._RESULT_INFLIGHT == {}
