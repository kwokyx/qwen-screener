from datetime import datetime, timedelta
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
    min_rows = max(100, int(basic_cnt * 0.5)) if basic_cnt else 100
    cnt = func.count(StockDaily.id)
    row = (
        db.query(StockDaily.trade_date, cnt.label("n"))
        .group_by(StockDaily.trade_date)
        .having(cnt >= min_rows)
        .order_by(StockDaily.trade_date.desc())
        .first()
    )
    return row[0] if row else db.query(func.max(StockDaily.trade_date)).scalar()


@router.get("/ai")
def ai_health():
    """前端启动时调用一次：判断 AI 上游是否可用。"""
    return qwen_client.probe_health()


@router.get("/data")
def data_health(db: Session = Depends(get_db)):
    """数据健康度：各类数据的覆盖度 + 最后一次定时同步的时间。"""
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
    sync_warnings = _sync_warnings(sync_meta)

    # 简单"新鲜度"判断：覆盖全市场的最新日期已达到最近工作日。
    expected_trade_date = _latest_expected_weekday()
    fresh = False
    if latest_trade_date:
        fresh = latest_trade_date >= expected_trade_date

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
    }


def _sync_warnings(sync_meta: dict[str, dict]) -> list[dict[str, str]]:
    labels = {
        "daily_market": "日线行情",
        "daily_value": "估值数据",
        "weekly_fundamentals": "财务指标",
        "weekly_dividend": "分红数据",
        "weekly_basic": "股票列表",
        "weekly_kline_backfill": "K线回填",
        "db_backup": "数据备份",
    }
    warnings: list[dict[str, str]] = []
    for name, meta in (sync_meta or {}).items():
        status = meta.get("display_status") or meta.get("status")
        if status not in {"failed", "stuck"}:
            continue
        warnings.append({
            "job": name,
            "label": labels.get(name, name),
            "status": status,
            "message": meta.get("detail") or ("任务异常" if status == "stuck" else "同步失败"),
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
