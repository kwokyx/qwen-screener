import threading
import time
from datetime import date, timedelta

from app.models.stock import StockBasic, StockDaily, StockFinancial
from app.services import scheduler


def _wait_until(predicate, timeout=2.0):
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
