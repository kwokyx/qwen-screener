"""定时任务：每个交易日收盘后自动同步行情/财务。

数据源由 DATA_PROVIDER 环境变量控制（默认 baostock）。
    DATA_PROVIDER=baostock  → 使用 baostock（推荐）
    DATA_PROVIDER=akshare   → 使用 AKShare（legacy）

时间表（东八区）：
    周一-周五 15:30   sync_daily       全市场日K线（OHLCV + PE/PB/换手率）
    周一-周五 16:00   sync_daily_value  估值面（bs: 同 daily 已有 PE/PB；ak: 东财+雪球 PE/股息率）
    周六     02:00   sync_fundamentals  财务指标
    周日     02:00   sync_basic        全 A 股代码列表（新股 / 退市更新）
    周日     03:00   weekly_kline_backfill  全市场 60 天历史 K 线回填
    每 6h            db_backup         冷备份 stock.db → /app/data/backups/

调度器随 FastAPI 启动起，停服时自动关。每次任务的执行时间会写到 sync_meta 表，
供前端 /health/data 显示"最后更新于..."。
"""
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal, engine
from app.services import data_sync, db_backup

USE_BAOSTOCK = settings.data_provider == "baostock"
logger.info("[SCHED] data_provider={}", settings.data_provider)


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


# ---- 各任务（统一入口，内部按 provider 分发）----

def job_daily_market():
    """全市场日K线（baostock: OHLCV+PE+PB；akshare: 新浪 OHLC 无 PE）。"""
    logger.info("[SCHED] daily_market 开始 (provider={})", settings.data_provider)
    db = SessionLocal()
    try:
        if USE_BAOSTOCK:
            affected = data_sync.sync_daily_bs(db, days_back=3)
        else:
            affected = data_sync.sync_daily_sina(db)
        if not affected:
            raise RuntimeError("daily_market 未写入任何行情数据")
        return affected
    finally:
        db.close()


def job_daily_value():
    """价值面补全。

    baostock 的日 K 线只稳定提供 PE/PB/换手率，市值和股息率仍需要补充源。
    如果补充源和 baostock 财务都失败，显式抛错，避免 sync_meta 记录成
    success affected=0，让前端误以为数据已更新。
    """
    logger.info("[SCHED] daily_value 开始 (provider={})", settings.data_provider)
    db = SessionLocal()
    try:
        if USE_BAOSTOCK:
            cnt = 0
            errors: list[str] = []
            try:
                cnt += data_sync.sync_full_valuation_tx(db) or 0
            except Exception as e:
                errors.append(f"tx-valuation: {str(e)[:100]}")
                logger.warning("[SCHED] daily_value tx-full 失败: {}", str(e)[:120])
            try:
                cnt += data_sync.sync_full_valuation_em(db) or 0
            except Exception as e:
                errors.append(f"em-valuation: {str(e)[:100]}")
                logger.warning("[SCHED] daily_value em-full 失败: {}", str(e)[:120])
            try:
                cnt += data_sync.sync_financial_bs(db, pool="csi300") or 0
            except Exception as e:
                errors.append(f"bs-financial: {str(e)[:100]}")
                logger.warning("[SCHED] daily_value bs-financial 失败: {}", str(e)[:120])
            if errors and cnt == 0:
                raise RuntimeError("; ".join(errors))
            return cnt
        else:
            cnt = 0
            try:
                cnt += data_sync.sync_full_valuation_tx(db) or 0
            except Exception as e:
                logger.warning("[SCHED] daily_value tx-full 失败: {}", str(e)[:120])
            try:
                cnt += data_sync.sync_full_valuation_em(db) or 0
            except Exception as e:
                logger.warning("[SCHED] daily_value em-full 失败: {}", str(e)[:120])
            for pool in ("csi300", "csi500"):
                try:
                    cnt += data_sync.sync_pool_xq(db, pool=pool) or 0
                except Exception as e:
                    logger.warning("[SCHED] daily_value pool={} 失败: {}", pool, str(e)[:120])
            return cnt
    finally:
        db.close()


def job_weekly_fundamentals():
    """行业 + 财务指标（baostock: 直接拉财务；akshare: 雪球逐只）。"""
    logger.info("[SCHED] weekly_fundamentals 开始 (provider={})", settings.data_provider)
    db = SessionLocal()
    try:
        if USE_BAOSTOCK:
            cnt = 0
            try:
                cnt += data_sync.sync_industry_ths(db) or 0
            except Exception as e:
                logger.warning("[SCHED] weekly_fundamentals ths-industry 失败: {}", str(e)[:120])
            try:
                cnt += data_sync.sync_exchange_basic_info(db) or 0
            except Exception as e:
                logger.warning("[SCHED] weekly_fundamentals exchange-basic 失败: {}", str(e)[:120])
            try:
                cnt += data_sync.sync_financial_bs(db, pool="all") or 0
            except Exception as e:
                logger.warning("[SCHED] weekly_fundamentals bs-financial 失败: {}", str(e)[:120])
            return cnt
        else:
            cnt = 0
            try:
                cnt += data_sync.sync_industry_ths(db) or 0
            except Exception as e:
                logger.warning("[SCHED] weekly_fundamentals ths-industry 失败: {}", str(e)[:120])
            try:
                cnt += data_sync.sync_exchange_basic_info(db) or 0
            except Exception as e:
                logger.warning("[SCHED] weekly_fundamentals exchange-basic 失败: {}", str(e)[:120])
            try:
                cnt += data_sync.sync_pool_industry(db, pool="bj") or 0
            except Exception as e:
                logger.warning("[SCHED] weekly_fundamentals bj-industry 失败: {}", str(e)[:120])
            try:
                cnt += data_sync.sync_pool_industry(db, pool="all") or 0
            except Exception as e:
                logger.warning("[SCHED] weekly_fundamentals all-industry 失败: {}", str(e)[:120])
            try:
                cnt += data_sync.sync_pool_financial(db, pool="all") or 0
            except Exception as e:
                logger.warning("[SCHED] weekly_fundamentals all-financial 失败: {}", str(e)[:120])
            return cnt
    finally:
        db.close()


def job_weekly_basic():
    """全 A 股代码刷新（新股 / 退市）。"""
    logger.info("[SCHED] weekly_basic 开始 (provider={})", settings.data_provider)
    db = SessionLocal()
    try:
        if USE_BAOSTOCK:
            return data_sync.sync_basic_bs(db)
        else:
            return data_sync.sync_basic(db)
    finally:
        db.close()


def job_db_backup():
    """冷备份 stock.db → /app/data/backups/。每 6h 触发一次。"""
    logger.info("[SCHED] db_backup 开始")
    rv = db_backup.backup_now()
    # 把状态写回 sync_meta，前端 /health/data 能看到
    status = rv.get("status", "?")
    if status == "ok":
        return f"{rv.get('file')} ({rv.get('size', 0)} bytes), removed {rv.get('removed', 0)}"
    return f"{status}: {rv.get('reason', '')}"


def job_weekly_kline_backfill():
    """全市场 60 天历史 K 线回填（bs: ~30-50分；akshare: ~30-50分）。"""
    logger.info("[SCHED] weekly_kline_backfill 开始 (provider={})", settings.data_provider)
    db = SessionLocal()
    try:
        if USE_BAOSTOCK:
            return data_sync.backfill_kline_all_bs(db, days=60)
        else:
            return data_sync.backfill_kline_all(db, days=60)
    finally:
        db.close()


JOBS = {
    "daily_market":           job_daily_market,
    "daily_value":            job_daily_value,
    "weekly_fundamentals":    job_weekly_fundamentals,
    "weekly_basic":           job_weekly_basic,
    "weekly_kline_backfill":  job_weekly_kline_backfill,
    "db_backup":              job_db_backup,
}


def run_now(job_name: str) -> dict:
    """同步执行一个任务，返回 meta 信息。"""
    fn = JOBS.get(job_name)
    if not fn:
        raise ValueError(f"未知任务: {job_name}，支持 {list(JOBS)}")
    _run_with_meta(job_name, fn)
    return get_meta().get(job_name, {})


def run_async(job_name: str) -> dict:
    """非阻塞触发：开个守护线程跑，HTTP 立即返回。

    全市场 K 线回填 ≈ 45 分钟，比 HTTP 默认 timeout（10 分钟）长得多，必须 async。
    前端可以隔几秒拉 /health/data 看 sync_meta 里这个任务的最新状态。
    """
    fn = JOBS.get(job_name)
    if not fn:
        raise ValueError(f"未知任务: {job_name}，支持 {list(JOBS)}")
    t = threading.Thread(
        target=_run_with_meta,
        args=(job_name, fn),
        name=f"sync-{job_name}",
        daemon=True,
    )
    t.start()
    return {"queued": True, "job": job_name}


def start():
    global _scheduler
    if _scheduler is not None:
        return
    _ensure_meta_table()
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    # 周一-周五 15:30：日K线快照（bs: OHLCV+PE+PB；ak: 新浪 OHLC）
    _scheduler.add_job(
        lambda: _run_with_meta("daily_market", job_daily_market),
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30),
        id="daily_market",
    )
    # 周一-周五 16:00：估值/财务面
    _scheduler.add_job(
        lambda: _run_with_meta("daily_value", job_daily_value),
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0),
        id="daily_value",
    )
    # 周六 02:00：全量财务指标
    _scheduler.add_job(
        lambda: _run_with_meta("weekly_fundamentals", job_weekly_fundamentals),
        CronTrigger(day_of_week="sat", hour=2, minute=0),
        id="weekly_fundamentals",
    )
    # 周日 02:00：代码列表刷新
    _scheduler.add_job(
        lambda: _run_with_meta("weekly_basic", job_weekly_basic),
        CronTrigger(day_of_week="sun", hour=2, minute=0),
        id="weekly_basic",
    )
    # 每 6h 冷备份
    _scheduler.add_job(
        lambda: _run_with_meta("db_backup", job_db_backup),
        CronTrigger(hour="*/6", minute=0),
        id="db_backup",
    )
    # 周日 03:00：全市场 60 天 K 线回填
    _scheduler.add_job(
        lambda: _run_with_meta("weekly_kline_backfill", job_weekly_kline_backfill),
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="weekly_kline_backfill",
    )
    _scheduler.start()
    logger.info("[SCHED] 已启动 {} 个任务 (provider={})", len(_scheduler.get_jobs()), settings.data_provider)

    # 启动时立刻做一次冷备份
    try:
        _run_with_meta("db_backup", job_db_backup)
    except Exception:
        logger.exception("[SCHED] 启动备份失败（不影响启动）")


def stop():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[SCHED] 已停止")
