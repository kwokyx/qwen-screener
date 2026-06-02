import threading
import time

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
