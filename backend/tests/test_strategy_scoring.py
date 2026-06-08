import threading
from datetime import date, timedelta

import pytest

from app.models.stock import StockBasic, StockDaily
from app.services import strategy_selector
from app.services.strategies import STRATEGIES, STRATEGY_REGISTRY


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


def _seed_latest_daily(db, trade_date=date(2026, 6, 4)):
    db.add(StockBasic(code="000001.SZ", name="测试股票", industry="银行"))
    db.add(StockDaily(
        code="000001.SZ",
        trade_date=trade_date,
        close=10,
        high=10,
        low=9,
        amount=2e8,
    ))
    db.commit()


def _pick(code: str, score: float = 80):
    return strategy_selector.StrategyPickItem(
        code=code,
        name=f"测试{code[-2:]}",
        trade_date=date(2026, 6, 4),
        close=10,
        score=score,
        signals=["测试信号"],
        metrics={},
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


def test_strategy_classes_return_empty_for_empty_histories():
    for strategy in STRATEGIES:
        assert strategy.run({}) == []


def test_strategy_registry_matches_templates_and_history_options():
    template_ids = [template.id for template in strategy_selector.list_templates()]

    assert template_ids == [strategy.id for strategy in STRATEGIES]
    assert set(STRATEGY_REGISTRY) == set(template_ids)
    for strategy in STRATEGIES:
        assert strategy_selector._STRATEGY_HISTORY_OPTIONS[strategy.id] == (
            strategy.history_days,
            strategy.max_codes,
        )


def test_run_strategy_selection_supports_all_registered_strategies(db, monkeypatch):
    strategy_selector.clear_strategy_cache()
    monkeypatch.setattr(strategy_selector, "_latest_strategy_trade_date", lambda _db: date(2026, 6, 4))
    monkeypatch.setattr(strategy_selector, "_load_histories", lambda *_args, **_kwargs: {})

    for strategy in STRATEGIES:
        response = strategy_selector.run_strategy_selection(db, strategy.id, limit=5)

        assert response.strategy.id == strategy.id
        assert response.total == 0
        assert response.items == []


def test_run_strategy_selection_rejects_unknown_strategy(db):
    with pytest.raises(ValueError, match="未知策略"):
        strategy_selector.run_strategy_selection(db, "unknown_strategy", limit=5)


def test_strategy_notes_explain_score_is_internal_strength(db, monkeypatch):
    strategy_selector.clear_strategy_cache()
    monkeypatch.setattr(strategy_selector, "_latest_strategy_trade_date", lambda _db: date(2026, 6, 4))
    monkeypatch.setattr(strategy_selector, "_load_histories", lambda *_args, **_kwargs: {})

    response = strategy_selector.run_strategy_selection(db, "turtle_breakout", limit=5)
    notes = " ".join(response.notes)

    assert "命中强度" in notes
    assert "综合评分" not in notes


def test_strategy_cache_reuses_full_result_across_limits(db, monkeypatch):
    strategy_selector.clear_strategy_cache()
    _seed_latest_daily(db)
    load_calls = 0

    def fake_load(_db, days, max_codes):
        nonlocal load_calls
        load_calls += 1
        assert days == 35
        assert max_codes == strategy_selector._STRATEGY_CANDIDATE_LIMIT
        return {}

    monkeypatch.setattr(strategy_selector, "_load_histories", fake_load)
    monkeypatch.setattr(
        strategy_selector,
        "_eval_turtle_breakout",
        lambda _histories: [_pick("000001.SZ", 90), _pick("000002.SZ", 80), _pick("000003.SZ", 70)],
    )

    first = strategy_selector.run_strategy_selection(db, "turtle_breakout", limit=1)
    second = strategy_selector.run_strategy_selection(db, "turtle_breakout", limit=3)

    assert load_calls == 1
    assert first.total == 3
    assert [item.code for item in first.items] == ["000001.SZ"]
    assert [item.code for item in second.items] == ["000001.SZ", "000002.SZ", "000003.SZ"]


def test_strategy_singleflight_coalesces_same_cache_key(db, monkeypatch):
    strategy_selector.clear_strategy_cache()
    started = threading.Event()
    release = threading.Event()
    load_calls = 0
    results = []
    errors = []

    monkeypatch.setattr(strategy_selector, "_latest_strategy_trade_date", lambda _db: date(2026, 6, 4))

    def fake_load(_db, days, max_codes):
        nonlocal load_calls
        load_calls += 1
        started.set()
        assert release.wait(timeout=2)
        return {}

    monkeypatch.setattr(strategy_selector, "_load_histories", fake_load)
    monkeypatch.setattr(strategy_selector, "_eval_turtle_breakout", lambda _histories: [_pick("000001.SZ", 90)])

    def run(limit):
        try:
            results.append(strategy_selector.run_strategy_selection(db, "turtle_breakout", limit=limit))
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=run, args=(1,))
    second = threading.Thread(target=run, args=(2,))
    first.start()
    assert started.wait(timeout=1)
    second.start()
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert load_calls == 1
    assert [res.total for res in results] == [1, 1]


def test_strategy_singleflight_failure_releases_inflight_and_allows_retry(db, monkeypatch):
    strategy_selector.clear_strategy_cache()
    _seed_latest_daily(db)
    calls = 0

    monkeypatch.setattr(strategy_selector, "_load_histories", lambda *_args, **_kwargs: {})

    def flaky_eval(_histories):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        return [_pick("000001.SZ", 90)]

    monkeypatch.setattr(strategy_selector, "_eval_turtle_breakout", flaky_eval)

    with pytest.raises(RuntimeError, match="boom"):
        strategy_selector.run_strategy_selection(db, "turtle_breakout", limit=1)

    retry = strategy_selector.run_strategy_selection(db, "turtle_breakout", limit=1)

    assert retry.total == 1
    assert calls == 2
    assert strategy_selector._RESULT_INFLIGHT == {}


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
