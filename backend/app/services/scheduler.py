"""定时任务：每个交易日收盘后自动同步行情/财务。

数据源由 DATA_PROVIDER 环境变量控制（默认 baostock）。
    DATA_PROVIDER=baostock  → 使用 baostock（推荐）
    DATA_PROVIDER=akshare   → 使用 AKShare（legacy）

时间表（东八区）：
    周一-周五 15:30   sync_daily       全市场日K线（OHLCV + PE/PB/换手率）
    周一-周五 16:00   sync_daily_value  估值面（bs: 同 daily 已有 PE/PB；ak: 东财+雪球 PE/股息率）
    周六     02:00   sync_fundamentals  财务指标
    周六     03:00   weekly_dividend    已实施现金分红 + 本地 TTM 股息率
    周日     02:00   sync_basic        全 A 股代码列表（新股 / 退市更新）
    周日     03:00   weekly_kline_backfill  全市场 60 天历史 K 线回填
    每 6h            db_backup         冷备份 stock.db → /app/data/backups/

调度器随 FastAPI 启动起，停服时自动关。每次任务的执行时间会写到 sync_meta 表，
供前端 /health/data 显示"最后更新于..."。
"""
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, engine
from app.models.stock import StockBasic, StockDaily, StockDividend, StockFinancial
from app.services import data_sync, db_backup

USE_BAOSTOCK = settings.data_provider == "baostock"
logger.info("[SCHED] data_provider={}", settings.data_provider)


_scheduler: BackgroundScheduler | None = None
_running_jobs: set[str] = set()
_running_lock = threading.Lock()
_meta_revision = 0
_meta_revision_lock = threading.Lock()


_DEFAULT_STUCK_MINUTES = 60
_JOB_STUCK_MINUTES = {
    "daily_market": 45,
    "daily_value": 45,
    "weekly_fundamentals": 180,
    "weekly_dividend": 120,
    "weekly_basic": 30,
    "weekly_kline_backfill": 180,
    "db_backup": 15,
}
_FINANCIAL_COVERAGE_THRESHOLD = 0.90
_VALUATION_COVERAGE_THRESHOLD = 0.90
_DIVIDEND_YIELD_COVERAGE_THRESHOLD = 0.90
_KLINE_BACKFILL_LOOKBACK_DAYS = 90
_KLINE_BACKFILL_MIN_COVERED_DAYS = 40
_STRATEGY_CACHE_INVALIDATING_JOBS = {
    "daily_market",
    "daily_value",
    "weekly_fundamentals",
    "weekly_dividend",
    "weekly_basic",
    "weekly_kline_backfill",
}


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


def _bump_meta_revision():
    global _meta_revision
    with _meta_revision_lock:
        _meta_revision += 1


def meta_revision() -> int:
    with _meta_revision_lock:
        return _meta_revision


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
    _bump_meta_revision()


def _clear_runtime_caches_after_data_job(name: str, status: str):
    if status != "success" or name not in _STRATEGY_CACHE_INVALIDATING_JOBS:
        return
    try:
        from app.services import strategy_selector

        strategy_selector.clear_strategy_cache()
    except Exception as exc:
        logger.warning("[SCHED] 策略缓存清理失败: {}", str(exc)[:120])
    try:
        from app.api import market

        market.clear_market_cache()
        threading.Thread(
            target=market.warm_market_cache,
            name=f"market-cache-rewarm-{name}",
            daemon=True,
        ).start()
    except Exception as exc:
        logger.warning("[SCHED] 行情概览缓存清理失败: {}", str(exc)[:120])


def _reserve_job(name: str) -> bool:
    """Reserve a job name so manual triggers cannot stack duplicates."""
    with _running_lock:
        if name in _running_jobs:
            return False
        _running_jobs.add(name)
        return True


def _release_job(name: str):
    with _running_lock:
        _running_jobs.discard(name)


def _mark_interrupted_jobs():
    """Mark stale queued/running rows from a previous backend process."""
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE sync_meta "
            "SET last_run_at = :t, status = 'failed', duration_ms = 0, detail = :d "
            "WHERE status IN ('queued', 'running')"
        ), {
            "t": datetime.utcnow(),
            "d": "服务重启，上一轮后台任务未完成",
        })
    _bump_meta_revision()


def get_meta() -> dict[str, dict]:
    _ensure_meta_table()
    now = datetime.utcnow()
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT name, last_run_at, status, duration_ms, detail FROM sync_meta"
        )).all()
    out = {}
    for r in rows:
        ts = r.last_run_at
        ts_str = _format_meta_datetime_utc(ts)
        age_minutes = _age_minutes(now, ts)
        stale_after = _JOB_STUCK_MINUTES.get(r.name, _DEFAULT_STUCK_MINUTES)
        stuck = r.status in ("queued", "running") and age_minutes is not None and age_minutes > stale_after
        detail = r.detail
        if stuck:
            detail = f"任务已{status_label(r.status)}超过 {stale_after} 分钟，请重试或检查日志"
        out[r.name] = {
            "last_run_at": ts_str,
            "status": r.status,
            "duration_ms": r.duration_ms,
            "detail": detail,
            "age_minutes": age_minutes,
            "stale_after_minutes": stale_after,
            "stuck": stuck,
            "display_status": "stuck" if stuck else r.status,
        }
    return out


def _age_minutes(now: datetime, ts) -> int | None:
    dt = _parse_meta_datetime(ts)
    if dt is None:
        return None
    return max(0, int((now - dt).total_seconds() // 60))


def _format_meta_datetime_utc(ts) -> str | None:
    dt = _parse_meta_datetime(ts)
    if dt is None:
        return None
    return f"{dt.isoformat(timespec='microseconds')}Z"


def _parse_meta_datetime(ts) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is not None:
            return ts.astimezone(timezone.utc).replace(tzinfo=None)
        return ts.replace(tzinfo=None)
    if isinstance(ts, str):
        try:
            text = ts.strip().replace(" ", "T", 1)
            if text.endswith(("Z", "z")):
                text = f"{text[:-1]}+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt.replace(tzinfo=None)
        except ValueError:
            return None
    return None


def status_label(status: str | None) -> str:
    if status == "queued":
        return "排队"
    if status == "running":
        return "运行"
    return "执行"


def _market_row_threshold(basic_cnt: int) -> int:
    return max(100, int(basic_cnt * 0.5)) if basic_cnt else 100


def _latest_expected_weekday(day=None) -> date:
    """Match /health/data's market-close freshness basis without importing it."""
    now = day or datetime.now(ZoneInfo("Asia/Shanghai"))
    current = now.date() if isinstance(now, datetime) else now
    if isinstance(now, datetime) and now.hour < 16:
        current -= timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def _covered_latest_trade_date(db: Session, basic_cnt: int, latest_allowed: date | None = None):
    min_rows = _market_row_threshold(basic_cnt)
    cnt = func.count(StockDaily.id)
    query = db.query(StockDaily.trade_date, cnt.label("n"))
    if latest_allowed is not None:
        query = query.filter(StockDaily.trade_date <= latest_allowed)
    row = (
        query.group_by(StockDaily.trade_date)
        .having(cnt >= min_rows)
        .order_by(StockDaily.trade_date.desc())
        .first()
    )
    if row:
        return row[0]
    fallback = db.query(func.max(StockDaily.trade_date))
    if latest_allowed is not None:
        fallback = fallback.filter(StockDaily.trade_date <= latest_allowed)
    return fallback.scalar()


def _latest_expected_financial_report_date(day=None) -> date:
    """Latest report period that should normally be available for A-shares."""
    today = day or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if isinstance(today, datetime):
        today = today.date()
    checkpoints = (
        (date(today.year, 10, 31), date(today.year, 9, 30)),
        (date(today.year, 8, 31), date(today.year, 6, 30)),
        (date(today.year, 4, 30), date(today.year, 3, 31)),
    )
    for cutoff, report_date in checkpoints:
        if today >= cutoff:
            return report_date
    return date(today.year - 1, 12, 31)


def _daily_market_status(db: Session) -> dict:
    basic_cnt = db.query(StockBasic).count()
    if not basic_cnt:
        return {"ready": False, "reason": "股票基础列表为空", "data_impact": "needs_sync"}
    expected = _latest_expected_weekday()
    latest = _covered_latest_trade_date(db, basic_cnt, latest_allowed=expected)
    latest_cnt = 0
    if latest:
        latest_cnt = db.query(StockDaily).filter(StockDaily.trade_date == latest).count()
    threshold = _market_row_threshold(basic_cnt)
    ready = bool(latest and latest >= expected and latest_cnt >= threshold)
    detail = (
        f"数据已达标，跳过远程同步：日线覆盖 {latest_cnt}/{basic_cnt}，"
        f"latest={latest}，expected={expected}"
    )
    return {
        "ready": ready,
        "reason": detail if ready else f"日线覆盖未达标：{latest_cnt}/{basic_cnt}，latest={latest}，expected={expected}",
        "detail": detail,
        "data_impact": "data_available" if ready else "needs_sync",
        "latest_trade_date": str(latest) if latest else None,
        "expected_trade_date": str(expected),
        "covered_rows": latest_cnt,
        "basic_rows": basic_cnt,
        "coverage_threshold": threshold,
    }


def _weekly_fundamentals_status(db: Session) -> dict:
    basic_cnt = db.query(StockBasic).count()
    if not basic_cnt:
        return {"ready": False, "reason": "股票基础列表为空", "data_impact": "needs_sync"}
    expected_report = _latest_expected_financial_report_date()
    fresh_fin_cnt = (
        db.query(StockFinancial.code)
        .filter(StockFinancial.report_date >= expected_report)
        .distinct()
        .count()
    )
    latest_report = db.query(func.max(StockFinancial.report_date)).scalar()
    required = max(1, int(basic_cnt * _FINANCIAL_COVERAGE_THRESHOLD))
    ready = bool(latest_report and latest_report >= expected_report and fresh_fin_cnt >= required)
    detail = (
        f"数据已达标，跳过远程同步：财务覆盖 {fresh_fin_cnt}/{basic_cnt}，"
        f"最新报告期 {latest_report}，应至 {expected_report}"
    )
    return {
        "ready": ready,
        "reason": detail if ready else f"财务覆盖未达标：{fresh_fin_cnt}/{basic_cnt}，最新报告期 {latest_report}，应至 {expected_report}",
        "detail": detail,
        "data_impact": "data_available" if ready else "needs_sync",
        "latest_report_date": str(latest_report) if latest_report else None,
        "expected_report_date": str(expected_report),
        "covered_rows": fresh_fin_cnt,
        "basic_rows": basic_cnt,
        "coverage_threshold": required,
    }


def _latest_daily_counts(db: Session) -> tuple[int, date | None, date, int, int]:
    basic_cnt = db.query(StockBasic).count()
    expected = _latest_expected_weekday()
    latest = _covered_latest_trade_date(db, basic_cnt, latest_allowed=expected) if basic_cnt else None
    latest_cnt = 0
    if latest:
        latest_cnt = db.query(StockDaily).filter(StockDaily.trade_date == latest).count()
    return basic_cnt, latest, expected, latest_cnt, _market_row_threshold(basic_cnt)


def _daily_value_status(db: Session) -> dict:
    basic_cnt, latest, expected, latest_cnt, market_threshold = _latest_daily_counts(db)
    if not basic_cnt:
        return {"ready": False, "reason": "股票基础列表为空", "data_impact": "needs_sync"}
    if not latest:
        return {"ready": False, "reason": "还没有日线行情数据", "data_impact": "needs_sync"}

    valuation_cnt = db.query(StockDaily).filter(
        StockDaily.trade_date == latest,
        (
            StockDaily.pe.isnot(None)
            | StockDaily.pb.isnot(None)
            | StockDaily.market_cap.isnot(None)
        ),
    ).count()
    dividend_yield_cnt = db.query(StockDaily).filter(
        StockDaily.trade_date == latest,
        StockDaily.dividend_yield.isnot(None),
    ).count()
    required = max(1, int(latest_cnt * _VALUATION_COVERAGE_THRESHOLD)) if latest_cnt else market_threshold
    ready = bool(
        latest >= expected
        and latest_cnt >= market_threshold
        and valuation_cnt >= required
        and dividend_yield_cnt >= required
    )
    detail = (
        f"数据已达标，跳过远程同步：估值覆盖 {valuation_cnt}/{latest_cnt}，"
        f"股息率覆盖 {dividend_yield_cnt}/{latest_cnt}，latest={latest}，expected={expected}"
    )
    return {
        "ready": ready,
        "reason": detail if ready else (
            f"估值覆盖未达标：估值 {valuation_cnt}/{latest_cnt}，"
            f"股息率 {dividend_yield_cnt}/{latest_cnt}，latest={latest}，expected={expected}"
        ),
        "detail": detail,
        "data_impact": "data_available" if ready else "needs_sync",
        "latest_trade_date": str(latest),
        "expected_trade_date": str(expected),
        "covered_rows": latest_cnt,
        "valuation_rows": valuation_cnt,
        "dividend_yield_rows": dividend_yield_cnt,
        "coverage_threshold": required,
    }


def _weekly_dividend_status(db: Session) -> dict:
    basic_cnt, latest, expected, latest_cnt, market_threshold = _latest_daily_counts(db)
    if not basic_cnt:
        return {"ready": False, "reason": "股票基础列表为空", "data_impact": "needs_sync"}
    if not latest:
        return {"ready": False, "reason": "还没有日线行情数据", "data_impact": "needs_sync"}

    dividend_records = db.query(StockDividend).count()
    dividend_yield_cnt = db.query(StockDaily).filter(
        StockDaily.trade_date == latest,
        StockDaily.dividend_yield.isnot(None),
    ).count()
    required = max(1, int(latest_cnt * _DIVIDEND_YIELD_COVERAGE_THRESHOLD)) if latest_cnt else market_threshold
    ready = bool(
        latest >= expected
        and latest_cnt >= market_threshold
        and dividend_records > 0
        and dividend_yield_cnt >= required
    )
    detail = (
        f"数据已达标，跳过远程同步：现金分红记录 {dividend_records} 条，"
        f"最新股息率覆盖 {dividend_yield_cnt}/{latest_cnt}，latest={latest}"
    )
    return {
        "ready": ready,
        "reason": detail if ready else (
            f"分红数据未达标：现金分红记录 {dividend_records} 条，"
            f"最新股息率覆盖 {dividend_yield_cnt}/{latest_cnt}，latest={latest}，expected={expected}"
        ),
        "detail": detail,
        "data_impact": "data_available" if ready else "needs_sync",
        "latest_trade_date": str(latest),
        "expected_trade_date": str(expected),
        "covered_rows": latest_cnt,
        "dividend_records": dividend_records,
        "dividend_yield_rows": dividend_yield_cnt,
        "coverage_threshold": required,
    }


def _weekly_kline_backfill_status(db: Session) -> dict:
    basic_cnt = db.query(StockBasic).count()
    if not basic_cnt:
        return {"ready": False, "reason": "股票基础列表为空", "data_impact": "needs_sync"}
    expected = _latest_expected_weekday()
    latest = _covered_latest_trade_date(db, basic_cnt, latest_allowed=expected)
    threshold = _market_row_threshold(basic_cnt)
    lookback_start = expected - timedelta(days=_KLINE_BACKFILL_LOOKBACK_DAYS)
    cnt = func.count(StockDaily.id)
    covered_days = (
        db.query(StockDaily.trade_date, cnt.label("n"))
        .filter(StockDaily.trade_date >= lookback_start)
        .group_by(StockDaily.trade_date)
        .having(cnt >= threshold)
        .count()
    )
    ready = bool(latest and latest >= expected and covered_days >= _KLINE_BACKFILL_MIN_COVERED_DAYS)
    detail = (
        f"数据已达标，跳过远程同步：近 {_KLINE_BACKFILL_LOOKBACK_DAYS} 天"
        f"全市场K线覆盖交易日 {covered_days}/{_KLINE_BACKFILL_MIN_COVERED_DAYS}，latest={latest}"
    )
    return {
        "ready": ready,
        "reason": detail if ready else (
            f"近期K线覆盖未达标：覆盖交易日 {covered_days}/{_KLINE_BACKFILL_MIN_COVERED_DAYS}，latest={latest}"
        ),
        "detail": detail,
        "data_impact": "data_available" if ready else "needs_sync",
        "latest_trade_date": str(latest) if latest else None,
        "expected_trade_date": str(expected),
        "covered_days": covered_days,
        "required_days": _KLINE_BACKFILL_MIN_COVERED_DAYS,
        "coverage_threshold": threshold,
    }


_JOB_DATA_STATUS = {
    "daily_market": _daily_market_status,
    "daily_value": _daily_value_status,
    "weekly_fundamentals": _weekly_fundamentals_status,
    "weekly_dividend": _weekly_dividend_status,
    "weekly_kline_backfill": _weekly_kline_backfill_status,
}


def job_data_status(name: str, db: Session | None = None) -> dict:
    """Return whether a heavy job can be repaired without remote sync."""
    checker = _JOB_DATA_STATUS.get(name)
    if checker is None:
        return {
            "ready": False,
            "reason": "该任务没有可短路的数据达标检查",
            "data_impact": "unknown",
        }
    if db is not None:
        return checker(db)
    session = SessionLocal()
    try:
        return checker(session)
    finally:
        session.close()


def _shortcut_detail_if_ready(name: str) -> str | None:
    repair_detail = None
    if name in {"daily_market", "daily_value", "weekly_dividend"}:
        repair_detail = _refresh_latest_dividend_yield_if_needed()
    status = job_data_status(name)
    if not status.get("ready"):
        return None
    detail = status.get("detail") or status.get("reason") or "数据已达标，跳过远程同步"
    if repair_detail:
        detail = f"{detail}；{repair_detail}"
    return detail


def _refresh_latest_dividend_yield_if_needed() -> str | None:
    db = SessionLocal()
    try:
        _basic_cnt, latest, _expected, latest_cnt, market_threshold = _latest_daily_counts(db)
        if not latest or latest_cnt < market_threshold:
            return None
        if db.query(StockDividend.id).first() is None:
            return None
        required = max(1, int(latest_cnt * _DIVIDEND_YIELD_COVERAGE_THRESHOLD))
        before = db.query(StockDaily).filter(
            StockDaily.trade_date == latest,
            StockDaily.dividend_yield.isnot(None),
        ).count()
        if before >= required:
            return None
        updated = data_sync.refresh_dividend_yield_bs(db, as_of=latest)
        after = db.query(StockDaily).filter(
            StockDaily.trade_date == latest,
            StockDaily.dividend_yield.isnot(None),
        ).count()
        return f"本地股息率重算 {after}/{latest_cnt}，更新 {updated} 行"
    finally:
        db.close()


def _run_with_meta(name: str, fn, *, reserved: bool = False, allow_shortcut: bool = True):
    _ensure_meta_table()
    if not reserved and not _reserve_job(name):
        logger.info("[SCHED] {} 已在执行中，跳过重复触发", name)
        return get_meta().get(name, {"status": "running", "detail": "任务已在执行中"})

    t0 = datetime.utcnow()
    detail = ""
    status = "success"
    try:
        _record(name, "running", 0, "任务执行中")
        shortcut_detail = _shortcut_detail_if_ready(name) if allow_shortcut else None
        if shortcut_detail:
            detail = shortcut_detail
            logger.info("[SCHED] {} {}", name, shortcut_detail)
        else:
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
            _clear_runtime_caches_after_data_job(name, status)
        except Exception:
            logger.exception("[SCHED] 写入 sync_meta 失败")
        _release_job(name)
    return get_meta().get(name, {})


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
        if USE_BAOSTOCK:
            try:
                data_sync.refresh_dividend_yield_bs(db)
            except Exception as e:
                logger.warning("[SCHED] daily_market 本地股息率重算失败: {}", str(e)[:120])
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


def job_weekly_dividend():
    """从 baostock 更新已实施现金分红，并重算最新 TTM 股息率。"""
    logger.info("[SCHED] weekly_dividend 开始 (provider={})", settings.data_provider)
    if not USE_BAOSTOCK:
        return 0
    db = SessionLocal()
    try:
        return data_sync.sync_dividend_yield_bs(db)
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
    "weekly_dividend":        job_weekly_dividend,
    "weekly_basic":           job_weekly_basic,
    "weekly_kline_backfill":  job_weekly_kline_backfill,
    "db_backup":              job_db_backup,
}


def run_now(job_name: str) -> dict:
    """同步执行一个任务，返回 meta 信息。"""
    _ensure_meta_table()
    fn = JOBS.get(job_name)
    if not fn:
        raise ValueError(f"未知任务: {job_name}，支持 {list(JOBS)}")
    if not _reserve_job(job_name):
        meta = get_meta().get(job_name, {})
        return {"already_running": True, **meta}
    return _run_with_meta(job_name, fn, reserved=True)


def run_async(job_name: str) -> dict:
    """非阻塞触发：开个守护线程跑，HTTP 立即返回。

    全市场 K 线回填 ≈ 45 分钟，比 HTTP 默认 timeout（10 分钟）长得多，必须 async。
    前端可以隔几秒拉 /health/data 看 sync_meta 里这个任务的最新状态。
    """
    _ensure_meta_table()
    fn = JOBS.get(job_name)
    if not fn:
        raise ValueError(f"未知任务: {job_name}，支持 {list(JOBS)}")
    if not _reserve_job(job_name):
        meta = get_meta().get(job_name, {})
        return {"queued": False, "running": True, "job": job_name, "meta": meta}

    shortcut_started = datetime.utcnow()
    try:
        shortcut_detail = _shortcut_detail_if_ready(job_name)
    except Exception as exc:
        shortcut_detail = None
        logger.warning("[SCHED] {} 数据达标检查失败，转入后台同步: {}", job_name, str(exc)[:120])
    if shortcut_detail:
        dur = int((datetime.utcnow() - shortcut_started).total_seconds() * 1000)
        try:
            _record(job_name, "success", dur, shortcut_detail)
            _clear_runtime_caches_after_data_job(job_name, "success")
            meta = get_meta().get(job_name, {})
            return {
                "queued": False,
                "running": False,
                "job": job_name,
                "shortcut": True,
                "meta": meta,
            }
        finally:
            _release_job(job_name)

    _record(job_name, "queued", 0, "任务已排队，后台执行")
    t = threading.Thread(
        target=_run_with_meta,
        args=(job_name, fn),
        kwargs={"reserved": True},
        name=f"sync-{job_name}",
        daemon=True,
    )
    t.start()
    return {"queued": True, "running": False, "job": job_name, "meta": get_meta().get(job_name, {})}


def start():
    global _scheduler
    if _scheduler is not None:
        return
    _ensure_meta_table()
    _mark_interrupted_jobs()
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    # 周一-周五 15:30：日K线快照（bs: OHLCV+PE+PB；ak: 新浪 OHLC）
    _scheduler.add_job(
        lambda: _run_with_meta("daily_market", job_daily_market, allow_shortcut=False),
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30),
        id="daily_market",
    )
    # 周一-周五 16:00：估值/财务面
    _scheduler.add_job(
        lambda: _run_with_meta("daily_value", job_daily_value, allow_shortcut=False),
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0),
        id="daily_value",
    )
    # 周六 02:00：全量财务指标
    _scheduler.add_job(
        lambda: _run_with_meta("weekly_fundamentals", job_weekly_fundamentals, allow_shortcut=False),
        CronTrigger(day_of_week="sat", hour=2, minute=0),
        id="weekly_fundamentals",
    )
    # 周六 03:00：现金分红记录 + 本地 TTM 股息率
    _scheduler.add_job(
        lambda: _run_with_meta("weekly_dividend", job_weekly_dividend, allow_shortcut=False),
        CronTrigger(day_of_week="sat", hour=3, minute=0),
        id="weekly_dividend",
    )
    # 周日 02:00：代码列表刷新
    _scheduler.add_job(
        lambda: _run_with_meta("weekly_basic", job_weekly_basic, allow_shortcut=False),
        CronTrigger(day_of_week="sun", hour=2, minute=0),
        id="weekly_basic",
    )
    # 每 6h 冷备份
    _scheduler.add_job(
        lambda: _run_with_meta("db_backup", job_db_backup, allow_shortcut=False),
        CronTrigger(hour="*/6", minute=0),
        id="db_backup",
    )
    # 周日 03:00：全市场 60 天 K 线回填
    _scheduler.add_job(
        lambda: _run_with_meta("weekly_kline_backfill", job_weekly_kline_backfill, allow_shortcut=False),
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="weekly_kline_backfill",
    )
    _scheduler.start()
    logger.info("[SCHED] 已启动 {} 个任务 (provider={})", len(_scheduler.get_jobs()), settings.data_provider)

    # 启动后后台做一次冷备份，避免 90MB+ SQLite 文件复制阻塞首屏请求。
    try:
        run_async("db_backup")
    except Exception:
        logger.exception("[SCHED] 启动备份失败（不影响启动）")


def stop():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[SCHED] 已停止")
