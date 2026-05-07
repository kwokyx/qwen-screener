"""定时任务：每个交易日收盘后自动同步行情/财务。

时间表（东八区）：
    周一-周五 15:30   sync_daily_sina   全市场 5800 只 OHLC + 成交量
    周一-周五 16:00   sync_pool_xq      csi300 + csi500 共 800 只价值面（PE/PB/股息率）
    周六     02:00   sync_pool_industry + sync_pool_financial  行业 + 财务
    周日     02:00   sync_basic        全 A 股代码列表（新股 / 退市更新）

调度器随 FastAPI 启动起，停服时自动关。每次任务的执行时间会写到 sync_meta 表，
供前端 /health/data 显示"最后更新于..."。
"""
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.services import data_sync


_scheduler: BackgroundScheduler | None = None


_META_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS sync_meta (
    name VARCHAR(64) PRIMARY KEY,
    last_run_at DATETIME NOT NULL,
    status VARCHAR(16),
    duration_ms INT,
    detail VARCHAR(256)
)
"""


def _ensure_meta_table():
    with engine.begin() as conn:
        conn.execute(text(_META_TABLE_DDL))


def _record(name: str, status: str, duration_ms: int, detail: str = ""):
    """upsert 一行 sync_meta。"""
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT name FROM sync_meta WHERE name = :n"), {"n": name}).first()
        params = {"n": name, "t": datetime.utcnow(), "s": status, "d": duration_ms, "x": detail[:256]}
        if exists:
            conn.execute(text(
                "UPDATE sync_meta SET last_run_at = :t, status = :s, duration_ms = :d, detail = :x "
                "WHERE name = :n"
            ), params)
        else:
            conn.execute(text(
                "INSERT INTO sync_meta (name, last_run_at, status, duration_ms, detail) "
                "VALUES (:n, :t, :s, :d, :x)"
            ), params)


def get_meta() -> dict[str, dict]:
    _ensure_meta_table()
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT name, last_run_at, status, duration_ms, detail FROM sync_meta"
        )).all()
    out = {}
    for r in rows:
        ts = r.last_run_at
        if ts is None:
            ts_str = None
        elif isinstance(ts, str):
            ts_str = ts
        else:
            ts_str = ts.isoformat()
        out[r.name] = {
            "last_run_at": ts_str,
            "status": r.status,
            "duration_ms": r.duration_ms,
            "detail": r.detail,
        }
    return out


def _run_with_meta(name: str, fn):
    t0 = datetime.utcnow()
    detail = ""
    status = "success"
    try:
        rv = fn()
        if rv is not None:
            detail = f"affected={rv}"
    except Exception as e:
        status = "failed"
        detail = str(e)[:240]
        logger.exception("[SCHED] {} 失败: {}", name, e)
    finally:
        dur = int((datetime.utcnow() - t0).total_seconds() * 1000)
        try:
            _record(name, status, dur, detail)
        except Exception:
            logger.exception("[SCHED] 写入 sync_meta 失败")


# ---- 各任务 ----

def job_daily_market():
    """全市场行情（新浪 5500+ 只 OHLC + 成交量）。"""
    logger.info("[SCHED] daily_market 开始")
    db = SessionLocal()
    try:
        return data_sync.sync_daily_sina(db)
    finally:
        db.close()


def job_daily_value():
    """价值面：csi300 + csi500（雪球，含股息率）+ 北交所（东方财富，无股息率）。
    单条失败不影响整体，写 sync_meta 时取累计 affected。
    """
    logger.info("[SCHED] daily_value 开始")
    db = SessionLocal()
    try:
        cnt = 0
        for pool in ("csi300", "csi500"):
            try:
                cnt += data_sync.sync_pool_xq(db, pool=pool) or 0
            except Exception as e:
                logger.warning("[SCHED] daily_value pool={} 失败: {}", pool, str(e)[:120])
        try:
            cnt += data_sync.sync_bj_valuation_em(db) or 0
        except Exception as e:
            logger.warning("[SCHED] daily_value bj-em 失败: {}", str(e)[:120])
        return cnt
    finally:
        db.close()


def job_weekly_fundamentals():
    """行业 + 财务（季度数据不每天变）。覆盖 csi300/csi500/bj。"""
    logger.info("[SCHED] weekly_fundamentals 开始")
    db = SessionLocal()
    try:
        cnt = 0
        for pool in ("csi300", "csi500", "bj"):
            try:
                cnt += data_sync.sync_pool_industry(db, pool=pool) or 0
                cnt += data_sync.sync_pool_financial(db, pool=pool) or 0
            except Exception as e:
                logger.warning("[SCHED] weekly_fundamentals pool={} 失败: {}", pool, str(e)[:120])
        return cnt
    finally:
        db.close()


def job_weekly_basic():
    """全 A 股代码刷新（新股 / 退市）。"""
    logger.info("[SCHED] weekly_basic 开始")
    db = SessionLocal()
    try:
        return data_sync.sync_basic(db)
    finally:
        db.close()


JOBS = {
    "daily_market":        job_daily_market,
    "daily_value":         job_daily_value,
    "weekly_fundamentals": job_weekly_fundamentals,
    "weekly_basic":        job_weekly_basic,
}


def run_now(job_name: str) -> dict:
    """同步执行一个任务，返回 meta 信息。"""
    fn = JOBS.get(job_name)
    if not fn:
        raise ValueError(f"未知任务: {job_name}，支持 {list(JOBS)}")
    _run_with_meta(job_name, fn)
    return get_meta().get(job_name, {})


def start():
    global _scheduler
    if _scheduler is not None:
        return
    _ensure_meta_table()
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(
        lambda: _run_with_meta("daily_market", job_daily_market),
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30),
        id="daily_market",
    )
    _scheduler.add_job(
        lambda: _run_with_meta("daily_value", job_daily_value),
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0),
        id="daily_value",
    )
    _scheduler.add_job(
        lambda: _run_with_meta("weekly_fundamentals", job_weekly_fundamentals),
        CronTrigger(day_of_week="sat", hour=2, minute=0),
        id="weekly_fundamentals",
    )
    _scheduler.add_job(
        lambda: _run_with_meta("weekly_basic", job_weekly_basic),
        CronTrigger(day_of_week="sun", hour=2, minute=0),
        id="weekly_basic",
    )
    _scheduler.start()
    logger.info("[SCHED] 已启动，{} 个任务", len(_scheduler.get_jobs()))


def stop():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[SCHED] 已停止")
