import copy
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import get_current_user
from app.database import get_db
from app.models.stock import StockBasic, StockDaily, StockDividend, StockFinancial
from app.models.user import User
from app.services import cache, db_backup, qwen_client, scheduler


router = APIRouter(prefix="/health", tags=["health"])
_DATA_HEALTH_CACHE_TTL_SECONDS = 5.0
_AI_HEALTH_CACHE_TTL_SECONDS = 30.0
_data_health_cache_lock = threading.Lock()
_data_health_cache: dict[str, object] = {
    "database_url": None,
    "revision": None,
    "expires_at": 0.0,
    "payload": None,
}
_ai_health_cache_lock = threading.Lock()
_ai_health_probe_lock = threading.Lock()
_ai_health_cache: dict[str, object] = {
    "backend": None,
    "model": None,
    "expires_at": 0.0,
    "payload": None,
}


def _market_row_threshold(basic_cnt: int) -> int:
    return max(100, int(basic_cnt * 0.5)) if basic_cnt else 100


def _latest_expected_weekday(day=None):
    """Return the latest weekday expected to have A-share closing data.

    This intentionally handles weekends only. Public-holiday awareness needs a
    maintained trading calendar and should not be guessed here.
    """
    now = day or datetime.now(ZoneInfo("Asia/Shanghai"))
    current = now.date() if isinstance(now, datetime) else now
    if isinstance(now, datetime) and now.hour < 16:
        current -= timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def _covered_latest_trade_date(db: Session, basic_cnt: int):
    """Latest date with enough rows to represent the whole market.

    Individual detail pages may backfill one stock to a newer date; reporting
    that sparse date as "latest data" makes the health page look fresher than
    the market-wide dataset actually is.
    """
    min_rows = _market_row_threshold(basic_cnt)
    cnt = func.count(StockDaily.id)
    row = (
        db.query(StockDaily.trade_date, cnt.label("n"))
        .group_by(StockDaily.trade_date)
        .having(cnt >= min_rows)
        .order_by(StockDaily.trade_date.desc())
        .first()
    )
    return row[0] if row else db.query(func.max(StockDaily.trade_date)).scalar()


def _active_sync_jobs(sync_meta: dict[str, dict]) -> list[str]:
    active = []
    for name, meta in (sync_meta or {}).items():
        status = meta.get("display_status") or meta.get("status")
        if status in {"queued", "running"}:
            active.append(name)
    return active


def _freshness_diagnostics(
    *,
    latest_trade_date: date | None,
    newest_trade_date: date | None,
    expected_trade_date: date,
    latest_daily_cnt: int,
    basic_cnt: int,
    sync_meta: dict[str, dict],
    sync_warnings: list[dict],
) -> dict:
    """Explain data freshness without weakening the actual freshness check."""
    threshold = _market_row_threshold(basic_cnt)
    active_jobs = _active_sync_jobs(sync_meta)
    lag_days = (expected_trade_date - latest_trade_date).days if latest_trade_date else None
    sparse_newer = bool(newest_trade_date and latest_trade_date and newest_trade_date > latest_trade_date)
    coverage = round(latest_daily_cnt / basic_cnt, 4) if basic_cnt else 0

    if not basic_cnt:
        reason_code = "empty_basic"
        label = "未建股票池"
        severity = "stale"
        message = "股票基础列表为空，请先同步股票列表。"
        recommended_jobs = ["weekly_basic"]
    elif not latest_trade_date:
        reason_code = "empty_daily"
        label = "未同步行情"
        severity = "stale"
        message = "还没有日线行情数据，请先同步日线行情。"
        recommended_jobs = ["daily_market"]
    elif latest_trade_date >= expected_trade_date:
        reason_code = "fresh"
        label = "已最新"
        severity = "fresh"
        message = "全市场日线已覆盖到最近应有交易日。"
        recommended_jobs = []
    elif sparse_newer:
        reason_code = "partial_newer_data"
        label = f"全市场至 {latest_trade_date}"
        severity = "meh"
        message = (
            f"数据库存在 {newest_trade_date} 的少量个股日线，但全市场覆盖仍停留在 "
            f"{latest_trade_date}；这通常来自详情页懒加载或同步尚未完成。"
        )
        recommended_jobs = ["daily_market", "daily_value"]
    elif active_jobs:
        reason_code = "sync_running"
        label = "同步中"
        severity = "meh"
        message = "全市场行情尚未达到最近应有交易日，相关同步任务正在后台执行。"
        recommended_jobs = []
    else:
        reason_code = "stale"
        label = f"落后 {max(lag_days or 0, 1)} 天"
        severity = "stale"
        if sync_warnings:
            message = "全市场行情落后于最近应有交易日，且有同步任务异常；请查看异常任务后重新同步。"
        else:
            message = "全市场行情落后于最近应有交易日，请优先运行日线行情同步。"
        recommended_jobs = ["daily_market", "daily_value"]

    return {
        "reason_code": reason_code,
        "label": label,
        "severity": severity,
        "message": message,
        "lag_days": lag_days,
        "expected_basis": "weekday_close_after_16_no_holidays",
        "coverage_threshold": threshold,
        "latest_coverage_rows": latest_daily_cnt,
        "latest_coverage": coverage,
        "has_sparse_newer_data": sparse_newer,
        "active_jobs": active_jobs,
        "recommended_jobs": recommended_jobs,
    }


@router.get("/ai")
def ai_health():
    """前端启动时调用一次：判断 AI 上游是否可用。"""
    cached = _cached_ai_health_payload(require_fresh=True)
    if cached is not None:
        return cached

    if not _ai_health_probe_lock.acquire(blocking=False):
        cached = _cached_ai_health_payload(require_fresh=False)
        if cached is not None:
            cached["stale"] = True
            return cached
        return _pending_ai_health_payload()

    try:
        payload = qwen_client.probe_health(3.0)
    finally:
        _ai_health_probe_lock.release()

    if _health_runtime_cache_enabled():
        with _ai_health_cache_lock:
            _ai_health_cache.update({
                "backend": settings.ai_backend,
                "model": settings.openai_model if settings.ai_backend == "openai" else settings.qwen_model,
                "expires_at": time.monotonic() + _AI_HEALTH_CACHE_TTL_SECONDS,
                "payload": copy.deepcopy(payload),
            })
    return payload


def _current_ai_health_identity() -> tuple[str, str]:
    backend = settings.ai_backend
    model = settings.openai_model if backend == "openai" else settings.qwen_model
    return backend, model


def _cached_ai_health_payload(*, require_fresh: bool) -> dict | None:
    if not _health_runtime_cache_enabled():
        return None
    now = time.monotonic()
    backend, model = _current_ai_health_identity()
    with _ai_health_cache_lock:
        if (
            _ai_health_cache["backend"] == backend
            and _ai_health_cache["model"] == model
            and _ai_health_cache["payload"] is not None
            and (not require_fresh or _ai_health_cache["expires_at"] > now)
        ):
            return copy.deepcopy(_ai_health_cache["payload"])
    return None


def _pending_ai_health_payload() -> dict:
    backend, model = _current_ai_health_identity()
    configured = bool(settings.openai_api_key) if backend == "openai" else bool(settings.dashscope_api_key)
    return {
        "ok": True,
        "latency_ms": None,
        "reason": "AI 健康检测中",
        "backend": backend,
        "model": model,
        "configured": configured,
        "fallback": False,
        "mode": "ai_agent" if configured else "local_rules",
        "pending": True,
    }


@router.get("/data")
def data_health(db: Session = Depends(get_db)):
    """数据健康度：各类数据的覆盖度 + 最后一次定时同步的时间。"""
    if _data_health_cache_enabled():
        revision = scheduler.meta_revision()
        now = time.monotonic()
        with _data_health_cache_lock:
            if (
                _data_health_cache["database_url"] == settings.database_url
                and _data_health_cache["revision"] == revision
                and _data_health_cache["expires_at"] > now
                and _data_health_cache["payload"] is not None
            ):
                return copy.deepcopy(_data_health_cache["payload"])

    payload = _data_health_payload(db)
    if _data_health_cache_enabled():
        with _data_health_cache_lock:
            _data_health_cache.update({
                "database_url": settings.database_url,
                "revision": scheduler.meta_revision(),
                "expires_at": time.monotonic() + _DATA_HEALTH_CACHE_TTL_SECONDS,
                "payload": copy.deepcopy(payload),
            })
    return payload


def _health_runtime_cache_enabled() -> bool:
    # Pytest uses a shared temp DB and calls this function directly after data
    # mutations; disabling the cache there keeps tests deterministic.
    return "pytest_qwen" not in settings.database_url


def _data_health_cache_enabled() -> bool:
    return _health_runtime_cache_enabled()


def _data_health_payload(db: Session):
    """Build the uncached data-health response."""
    daily_cnt = db.query(StockDaily).count()
    fin_cnt = db.query(StockFinancial).count()
    basic_cnt = db.query(StockBasic).count()
    industry_cnt = db.query(StockBasic).filter(StockBasic.industry.isnot(None)).count()
    newest_trade_date = db.query(func.max(StockDaily.trade_date)).scalar()
    latest_trade_date = _covered_latest_trade_date(db, basic_cnt)
    latest_daily_cnt = 0
    valuation_cnt = 0
    dividend_yield_cnt = 0
    if latest_trade_date:
        latest_daily_cnt = db.query(StockDaily).filter(
            StockDaily.trade_date == latest_trade_date,
        ).count()
        valuation_cnt = db.query(StockDaily).filter(
            StockDaily.trade_date == latest_trade_date,
            (
                StockDaily.pe.isnot(None)
                | StockDaily.pb.isnot(None)
                | StockDaily.market_cap.isnot(None)
            ),
        ).count()
        dividend_yield_cnt = db.query(StockDaily).filter(
            StockDaily.trade_date == latest_trade_date,
            StockDaily.dividend_yield.isnot(None),
        ).count()

    sync_meta = scheduler.get_meta()
    # 简单"新鲜度"判断：覆盖全市场的最新日期已达到最近工作日。
    expected_trade_date = _latest_expected_weekday()
    fresh = False
    if latest_trade_date:
        fresh = latest_trade_date >= expected_trade_date
    sync_warnings = _sync_warnings(sync_meta, db=db, fresh=fresh)
    freshness = _freshness_diagnostics(
        latest_trade_date=latest_trade_date,
        newest_trade_date=newest_trade_date,
        expected_trade_date=expected_trade_date,
        latest_daily_cnt=latest_daily_cnt,
        basic_cnt=basic_cnt,
        sync_meta=sync_meta,
        sync_warnings=sync_warnings,
    )

    return {
        "fresh": fresh,
        "expected_trade_date": str(expected_trade_date),
        "latest_trade_date": str(latest_trade_date) if latest_trade_date else None,
        "newest_trade_date": str(newest_trade_date) if newest_trade_date else None,
        "data_provider": settings.data_provider,
        "counts": {
            "basic": basic_cnt,
            "daily": daily_cnt,
            "financial": fin_cnt,
            "with_industry": industry_cnt,
            "latest_daily": latest_daily_cnt,
            "market_coverage_threshold": _market_row_threshold(basic_cnt),
            "latest_valuation": valuation_cnt,
            "dividend_records": db.query(StockDividend).count(),
            "latest_dividend_yield": dividend_yield_cnt,
        },
        "coverage": {
            "industry": round(industry_cnt / basic_cnt, 4) if basic_cnt else 0,
            "financial": round(fin_cnt / basic_cnt, 4) if basic_cnt else 0,
            "latest_daily": round(latest_daily_cnt / basic_cnt, 4) if basic_cnt else 0,
            "latest_valuation": round(valuation_cnt / latest_daily_cnt, 4) if latest_daily_cnt else 0,
            "latest_dividend_yield": round(dividend_yield_cnt / latest_daily_cnt, 4) if latest_daily_cnt else 0,
        },
        "sync_meta": sync_meta,
        "sync_warnings": sync_warnings,
        "sync_has_issue": bool(sync_warnings),
        "freshness": freshness,
    }


def _sync_warnings(sync_meta: dict[str, dict], *, db: Session | None = None, fresh: bool = False) -> list[dict]:
    labels = {
        "daily_market": "日线行情",
        "daily_value": "估值数据",
        "weekly_fundamentals": "财务指标",
        "weekly_dividend": "分红数据",
        "weekly_basic": "股票列表",
        "weekly_kline_backfill": "K线回填",
        "db_backup": "数据备份",
    }
    warnings: list[dict] = []
    for name, meta in (sync_meta or {}).items():
        status = meta.get("display_status") or meta.get("status")
        if status not in {"failed", "stuck"}:
            continue
        readiness = scheduler.job_data_status(name, db=db)
        data_ready = bool(readiness.get("ready"))
        data_impact = readiness.get("data_impact") or ("data_available" if data_ready else "needs_sync")
        if data_ready:
            warning_kind = "task_failed_data_ready"
            recommended_action = "修复异常状态；当前数据已达标，不会重新拉取全市场"
        elif fresh:
            warning_kind = "task_failed_data_fresh"
            recommended_action = "按顺序重试异常任务；数据当前仍可用于基础筛选"
        else:
            warning_kind = "task_failed_needs_sync"
            recommended_action = "重新同步该任务，完成后再检查数据新鲜度"
        warnings.append({
            "job": name,
            "label": labels.get(name, name),
            "status": status,
            "message": meta.get("detail") or ("任务异常" if status == "stuck" else "同步失败"),
            "warning_kind": warning_kind,
            "data_impact": data_impact,
            "can_fast_retry": data_ready,
            "recommended_action": recommended_action,
            "readiness": readiness,
        })
    return warnings


@router.get("/cache")
def cache_health():
    """Redis 缓存健康度 + 命中率。"""
    return cache.stats()


@router.post("/sync/{job_name}")
def trigger_sync(
    job_name: str,
    wait: bool = False,
    _user: User = Depends(get_current_user),
):
    """手动触发一个 sync 任务（前端"立即更新"按钮用）。

    需要登录。默认 async（守护线程后台跑，立即返回）。对全市场 60d K 线回填这种 45 分钟级别
    的任务必须 async，否则 HTTP 会超时。前端可隔几秒查 /health/data 看 sync_meta
    里该任务的状态。
    可选 job_name：daily_market / daily_value / weekly_fundamentals / weekly_dividend
                / weekly_basic / weekly_kline_backfill / db_backup
    传 ?wait=true 退回同步模式（短任务用，比如 db_backup 几秒就完）。
    """
    try:
        if wait:
            meta = scheduler.run_now(job_name)
            return {
                "job": job_name,
                "queued": False,
                "running": meta.get("already_running") is True or meta.get("status") == "running",
                "meta": meta,
            }
        rv = scheduler.run_async(job_name)
        queued = rv.get("queued", False) or rv.get("status") == "queued"
        running = rv.get("running", False) or rv.get("status") == "running"
        return {
            "job": job_name,
            "queued": queued,
            "running": running,
            "meta": rv.get("meta") or scheduler.get_meta().get(job_name, {}),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/backups")
def list_backups():
    """列出 /app/data/backups/ 下的 SQLite 冷备份文件，时间倒序。"""
    return {"items": db_backup.list_backups()}


@router.get("/baostock")
def baostock_health():
    """检查 baostock 数据源连通性。"""
    try:
        from app.services.providers.baostock_provider import probe_baostock
        return probe_baostock()
    except ImportError:
        return {"status": "not_installed", "error": "baostock 未安装"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:200]}


@router.get("/providers")
def providers_health():
    """汇总当前主要数据源状态，便于前端/调试页一次性展示。"""
    baostock = baostock_health()
    return {
        "active": settings.data_provider,
        "baostock": baostock,
    }
