import threading
import time
from datetime import date, datetime, timedelta

from sqlalchemy import text

from app.models.stock import StockBasic, StockDaily, StockDividend, StockFinancial
from app.api import market as market_api
from app.services import scheduler, strategy_selector


def _wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_scheduler_records_failed_job(db):
    scheduler._running_jobs.clear()

    def fail():
        raise RuntimeError("baostock probe failed")

    meta = scheduler._run_with_meta("unit_fail", fail)

    assert meta["status"] == "failed"
    assert "baostock probe failed" in meta["detail"]
    assert "unit_fail" not in scheduler._running_jobs


def test_startup_marks_stale_active_jobs_failed(db):
    scheduler._ensure_meta_table()
    scheduler._record("unit_stale", "running", 0, "任务执行中")

    scheduler._mark_interrupted_jobs()

    meta = scheduler.get_meta()["unit_stale"]
    assert meta["status"] == "failed"
    assert "服务重启" in meta["detail"]


def test_get_meta_returns_timezone_qualified_utc_timestamp(db):
    scheduler._ensure_meta_table()
    ts = datetime(2026, 6, 4, 7, 42, 46, 871898)
    with scheduler.engine.begin() as conn:
        conn.execute(text("DELETE FROM sync_meta"))
        conn.execute(
            text(
                "INSERT INTO sync_meta (name, last_run_at, status, duration_ms, detail) "
                "VALUES (:n, :t, :s, :d, :x)"
            ),
            {
                "n": "unit_time",
                "t": ts,
                "s": "success",
                "d": 0,
                "x": "",
            },
        )

    meta = scheduler.get_meta()["unit_time"]

    assert meta["last_run_at"] == "2026-06-04T07:42:46.871898Z"
    assert meta["age_minutes"] >= 0


def test_run_async_marks_queued_and_blocks_duplicate(db, monkeypatch):
    scheduler._running_jobs.clear()
    started = threading.Event()
    release = threading.Event()

    def slow_job():
        started.set()
        release.wait(timeout=2)
        return 3

    monkeypatch.setitem(scheduler.JOBS, "unit_slow", slow_job)

    first = scheduler.run_async("unit_slow")
    assert first["queued"] is True
    assert first["meta"]["status"] in {"queued", "running"}
    assert started.wait(timeout=1)

    duplicate = scheduler.run_async("unit_slow")
    assert duplicate["queued"] is False
    assert duplicate["running"] is True

    release.set()
    assert _wait_until(lambda: scheduler.get_meta().get("unit_slow", {}).get("status") == "success")
    assert scheduler.get_meta()["unit_slow"]["detail"] == "affected=3"
    assert "unit_slow" not in scheduler._running_jobs


def test_successful_data_job_clears_runtime_caches(db, monkeypatch):
    scheduler._running_jobs.clear()
    cleared_strategy = []
    cleared_market = []
    rewarmed_market = []

    class ImmediateThread:
        def __init__(self, target, name=None, daemon=None):
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self):
            rewarmed_market.append({"name": self.name, "daemon": self.daemon})
            self.target()

    monkeypatch.setattr(strategy_selector, "clear_strategy_cache", lambda: cleared_strategy.append(True))
    monkeypatch.setattr(market_api, "clear_market_cache", lambda: cleared_market.append(True))
    monkeypatch.setattr(market_api, "warm_market_cache", lambda: rewarmed_market.append("ran"))
    monkeypatch.setattr(scheduler.threading, "Thread", ImmediateThread)

    meta = scheduler._run_with_meta("daily_market", lambda: 3, allow_shortcut=False)

    assert meta["status"] == "success"
    assert cleared_strategy == [True]
    assert cleared_market == [True]
    assert rewarmed_market == [
        {"name": "market-cache-rewarm-daily_market", "daemon": True},
        "ran",
    ]


def _seed_basic(db, n=120):
    for i in range(n):
        db.add(StockBasic(code=f"60{i:04d}.SH", name=f"测试股{i}", industry="测试"))
    db.commit()


def test_run_now_short_circuits_daily_market_when_data_ready(db, monkeypatch):
    scheduler._running_jobs.clear()
    expected = date(2026, 6, 3)
    monkeypatch.setattr(scheduler, "_latest_expected_weekday", lambda day=None: expected)
    _seed_basic(db, 120)
    for code, in db.query(StockBasic.code).all():
        db.add(StockDaily(code=code, trade_date=expected, close=10, volume=100))
    db.commit()

    def should_not_call():
        raise AssertionError("remote daily sync should be skipped")

    monkeypatch.setitem(scheduler.JOBS, "daily_market", should_not_call)

    meta = scheduler.run_now("daily_market")

    assert meta["status"] == "success"
    assert "数据已达标" in meta["detail"]
    assert "跳过远程同步" in meta["detail"]


def test_run_async_short_circuits_ready_data_and_repairs_failed_meta(db, monkeypatch):
    scheduler._running_jobs.clear()
    expected = date(2026, 6, 3)
    monkeypatch.setattr(scheduler, "_latest_expected_weekday", lambda day=None: expected)
    _seed_basic(db, 120)
    for code, in db.query(StockBasic.code).all():
        db.add(StockDaily(code=code, trade_date=expected, close=10, volume=100))
    db.commit()

    def should_not_call():
        raise AssertionError("ready data should not queue remote daily sync")

    monkeypatch.setitem(scheduler.JOBS, "daily_market", should_not_call)
    scheduler._ensure_meta_table()
    old = datetime.utcnow() - timedelta(hours=8)
    with scheduler.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO sync_meta (name, last_run_at, status, duration_ms, detail) "
            "VALUES (:n, :t, :s, :d, :x)"
        ), {
            "n": "daily_market",
            "t": old,
            "s": "failed",
            "d": 0,
            "x": "服务重启，上一轮后台任务未完成",
        })

    rv = scheduler.run_async("daily_market")

    assert rv["queued"] is False
    assert rv["running"] is False
    assert rv["shortcut"] is True
    assert rv["meta"]["status"] == "success"
    assert "数据已达标" in rv["meta"]["detail"]
    assert "跳过远程同步" in rv["meta"]["detail"]
    assert rv["meta"]["age_minutes"] == 0
    assert "daily_market" not in scheduler._running_jobs


def test_run_async_repairs_stuck_ready_job_even_when_reserved(db, monkeypatch):
    scheduler._running_jobs.clear()
    report_date = date(2026, 3, 31)
    monkeypatch.setattr(scheduler, "_latest_expected_financial_report_date", lambda day=None: report_date)
    _seed_basic(db, 100)
    for code, in db.query(StockBasic.code).limit(90).all():
        db.add(StockFinancial(code=code, report_date=report_date, roe=12.3))
    db.commit()

    def should_not_call():
        raise AssertionError("ready data should repair stuck meta without remote sync")

    monkeypatch.setitem(scheduler.JOBS, "weekly_fundamentals", should_not_call)
    scheduler._ensure_meta_table()
    old = datetime.utcnow() - timedelta(hours=4)
    with scheduler.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO sync_meta (name, last_run_at, status, duration_ms, detail) "
            "VALUES (:n, :t, :s, :d, :x)"
        ), {
            "n": "weekly_fundamentals",
            "t": old,
            "s": "running",
            "d": 0,
            "x": "任务执行中",
        })

    scheduler._running_jobs.add("weekly_fundamentals")
    try:
        rv = scheduler.run_async("weekly_fundamentals")
    finally:
        scheduler._running_jobs.discard("weekly_fundamentals")

    assert rv["queued"] is False
    assert rv["running"] is False
    assert rv["shortcut"] is True
    assert rv["repaired"] is True
    assert rv["meta"]["status"] == "success"
    assert "财务覆盖 90/100" in rv["meta"]["detail"]
    assert "weekly_fundamentals" not in scheduler._running_jobs


def test_run_async_repairs_stuck_weekly_basic_when_stock_list_ready(db, monkeypatch):
    scheduler._running_jobs.clear()
    _seed_basic(db, 120)

    def should_not_call():
        raise AssertionError("ready stock list should repair stuck meta without remote sync")

    monkeypatch.setitem(scheduler.JOBS, "weekly_basic", should_not_call)
    scheduler._ensure_meta_table()
    old = datetime.utcnow() - timedelta(hours=2)
    with scheduler.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO sync_meta (name, last_run_at, status, duration_ms, detail) "
            "VALUES (:n, :t, :s, :d, :x)"
        ), {
            "n": "weekly_basic",
            "t": old,
            "s": "running",
            "d": 0,
            "x": "任务执行中",
        })

    scheduler._running_jobs.add("weekly_basic")
    try:
        rv = scheduler.run_async("weekly_basic")
    finally:
        scheduler._running_jobs.discard("weekly_basic")

    assert rv["queued"] is False
    assert rv["running"] is False
    assert rv["shortcut"] is True
    assert rv["repaired"] is True
    assert rv["meta"]["status"] == "success"
    assert "股票列表 120 只" in rv["meta"]["detail"]
    assert "weekly_basic" not in scheduler._running_jobs


def test_failed_job_state_does_not_block_retry(db, monkeypatch):
    scheduler._running_jobs.clear()

    def fail():
        raise RuntimeError("temporary upstream failure")

    monkeypatch.setitem(scheduler.JOBS, "unit_retry", fail)
    first = scheduler.run_now("unit_retry")

    assert first["status"] == "failed"
    assert "temporary upstream failure" in first["detail"]
    assert "unit_retry" not in scheduler._running_jobs

    monkeypatch.setitem(scheduler.JOBS, "unit_retry", lambda: 5)
    second = scheduler.run_now("unit_retry")

    assert second["status"] == "success"
    assert second["detail"] == "affected=5"
    assert "unit_retry" not in scheduler._running_jobs


def test_run_now_repairs_latest_dividend_yield_before_daily_value_shortcut(db, monkeypatch):
    scheduler._running_jobs.clear()
    expected = date(2026, 6, 3)
    monkeypatch.setattr(scheduler, "_latest_expected_weekday", lambda day=None: expected)
    _seed_basic(db, 120)
    for code, in db.query(StockBasic.code).all():
        db.add(StockDaily(
            code=code,
            trade_date=expected,
            close=10,
            pe=12,
            pb=1.2,
            market_cap=100,
            volume=100,
        ))
        db.add(StockDividend(code=code, operate_date=expected, cash_per_share=0.5))
    db.commit()

    def should_not_call():
        raise AssertionError("daily_value remote sync should be skipped after local dividend repair")

    monkeypatch.setitem(scheduler.JOBS, "daily_value", should_not_call)

    meta = scheduler.run_now("daily_value")

    assert meta["status"] == "success"
    assert "本地股息率重算" in meta["detail"]
    assert "股息率覆盖 120/120" in meta["detail"]


def test_run_with_meta_can_disable_shortcut_for_scheduled_jobs(db, monkeypatch):
    scheduler._running_jobs.clear()
    expected = date(2026, 6, 3)
    monkeypatch.setattr(scheduler, "_latest_expected_weekday", lambda day=None: expected)
    _seed_basic(db, 120)
    for code, in db.query(StockBasic.code).all():
        db.add(StockDaily(code=code, trade_date=expected, close=10, volume=100))
    db.commit()

    meta = scheduler._run_with_meta("daily_market", lambda: 11, allow_shortcut=False)

    assert meta["status"] == "success"
    assert meta["detail"] == "affected=11"


def test_run_now_executes_daily_market_when_data_not_ready(db, monkeypatch):
    scheduler._running_jobs.clear()
    monkeypatch.setattr(scheduler, "_latest_expected_weekday", lambda day=None: date(2026, 6, 3))
    _seed_basic(db, 120)

    monkeypatch.setitem(scheduler.JOBS, "daily_market", lambda: 7)

    meta = scheduler.run_now("daily_market")

    assert meta["status"] == "success"
    assert meta["detail"] == "affected=7"


def test_run_now_short_circuits_weekly_fundamentals_when_data_ready(db, monkeypatch):
    scheduler._running_jobs.clear()
    report_date = date(2026, 3, 31)
    monkeypatch.setattr(scheduler, "_latest_expected_financial_report_date", lambda day=None: report_date)
    _seed_basic(db, 100)
    for code, in db.query(StockBasic.code).limit(90).all():
        db.add(StockFinancial(code=code, report_date=report_date, roe=12.3))
    db.commit()

    def should_not_call():
        raise AssertionError("remote fundamentals sync should be skipped")

    monkeypatch.setitem(scheduler.JOBS, "weekly_fundamentals", should_not_call)

    meta = scheduler.run_now("weekly_fundamentals")

    assert meta["status"] == "success"
    assert "财务覆盖 90/100" in meta["detail"]
    assert "跳过远程同步" in meta["detail"]


def test_run_now_short_circuits_daily_value_when_valuation_ready(db, monkeypatch):
    scheduler._running_jobs.clear()
    expected = date(2026, 6, 3)
    monkeypatch.setattr(scheduler, "_latest_expected_weekday", lambda day=None: expected)
    _seed_basic(db, 120)
    for code, in db.query(StockBasic.code).all():
        db.add(StockDaily(
            code=code,
            trade_date=expected,
            close=10,
            volume=100,
            pe=8.5,
            pb=0.9,
            market_cap=300,
            dividend_yield=3.2,
        ))
    db.commit()

    def should_not_call():
        raise AssertionError("remote valuation sync should be skipped")

    monkeypatch.setitem(scheduler.JOBS, "daily_value", should_not_call)

    meta = scheduler.run_now("daily_value")

    assert meta["status"] == "success"
    assert "估值覆盖 120/120" in meta["detail"]
    assert "跳过远程同步" in meta["detail"]


def test_run_now_short_circuits_weekly_dividend_when_yield_ready(db, monkeypatch):
    scheduler._running_jobs.clear()
    expected = date(2026, 6, 3)
    monkeypatch.setattr(scheduler, "_latest_expected_weekday", lambda day=None: expected)
    _seed_basic(db, 120)
    for code, in db.query(StockBasic.code).all():
        db.add(StockDaily(
            code=code,
            trade_date=expected,
            close=10,
            volume=100,
            dividend_yield=3.2,
        ))
    db.add(StockDividend(
        code="600000.SH",
        operate_date=expected,
        cash_per_share=0.3,
    ))
    db.commit()

    def should_not_call():
        raise AssertionError("remote dividend sync should be skipped")

    monkeypatch.setitem(scheduler.JOBS, "weekly_dividend", should_not_call)

    meta = scheduler.run_now("weekly_dividend")

    assert meta["status"] == "success"
    assert "最新股息率覆盖 120/120" in meta["detail"]
    assert "跳过远程同步" in meta["detail"]


def test_weekly_dividend_status_ignores_newer_unexpected_day(db, monkeypatch):
    expected = date(2026, 6, 3)
    newer = date(2026, 6, 4)
    monkeypatch.setattr(scheduler, "_latest_expected_weekday", lambda day=None: expected)
    _seed_basic(db, 120)
    for code, in db.query(StockBasic.code).all():
        db.add(StockDaily(
            code=code,
            trade_date=expected,
            close=10,
            volume=100,
            dividend_yield=3.2,
        ))
        db.add(StockDaily(
            code=code,
            trade_date=newer,
            close=10,
            volume=100,
        ))
    db.add(StockDividend(
        code="600000.SH",
        operate_date=expected,
        cash_per_share=0.3,
    ))
    db.commit()

    status = scheduler.job_data_status("weekly_dividend", db=db)

    assert status["ready"] is True
    assert status["latest_trade_date"] == str(expected)
    assert "最新股息率覆盖 120/120" in status["detail"]


def test_run_now_short_circuits_weekly_kline_backfill_when_recent_kline_ready(db, monkeypatch):
    scheduler._running_jobs.clear()
    expected = date(2026, 6, 3)
    monkeypatch.setattr(scheduler, "_latest_expected_weekday", lambda day=None: expected)
    _seed_basic(db, 120)
    codes = [code for code, in db.query(StockBasic.code).all()]
    for day_offset in range(scheduler._KLINE_BACKFILL_MIN_COVERED_DAYS):
        trade_date = expected - timedelta(days=day_offset)
        for code in codes:
            db.add(StockDaily(code=code, trade_date=trade_date, close=10, volume=100))
    db.commit()

    def should_not_call():
        raise AssertionError("remote kline backfill should be skipped")

    monkeypatch.setitem(scheduler.JOBS, "weekly_kline_backfill", should_not_call)

    meta = scheduler.run_now("weekly_kline_backfill")

    assert meta["status"] == "success"
    assert "全市场K线覆盖交易日" in meta["detail"]
    assert "跳过远程同步" in meta["detail"]
