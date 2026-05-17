from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock import StockBasic, StockDaily, StockFinancial
from app.services import cache, db_backup, qwen_client, scheduler


router = APIRouter(prefix="/health", tags=["health"])


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
    latest_trade_date = db.query(func.max(StockDaily.trade_date)).scalar()

    sync_meta = scheduler.get_meta()

    # 简单"新鲜度"判断：今日有交易日数据 + 最近一次同步在 24h 内
    fresh = False
    if latest_trade_date:
        fresh = latest_trade_date >= (datetime.utcnow().date() - timedelta(days=1))

    return {
        "fresh": fresh,
        "latest_trade_date": str(latest_trade_date) if latest_trade_date else None,
        "counts": {
            "basic": basic_cnt,
            "daily": daily_cnt,
            "financial": fin_cnt,
            "with_industry": industry_cnt,
        },
        "sync_meta": sync_meta,
    }


@router.get("/cache")
def cache_health():
    """Redis 缓存健康度 + 命中率。"""
    return cache.stats()


@router.post("/sync/{job_name}")
def trigger_sync(job_name: str, wait: bool = False):
    """手动触发一个 sync 任务（前端"立即更新"按钮用）。

    默认 async（守护线程后台跑，立即返回）。对全市场 60d K 线回填这种 45 分钟级别
    的任务必须 async，否则 HTTP 会超时。前端可隔几秒查 /health/data 看 sync_meta
    里该任务的状态。
    可选 job_name：daily_market / daily_value / weekly_fundamentals / weekly_basic
                / weekly_kline_backfill / db_backup
    传 ?wait=true 退回同步模式（短任务用，比如 db_backup 几秒就完）。
    """
    try:
        if wait:
            meta = scheduler.run_now(job_name)
            return {"job": job_name, "meta": meta}
        rv = scheduler.run_async(job_name)
        return {"job": job_name, "queued": True, "meta": rv}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/backups")
def list_backups():
    """列出 /app/data/backups/ 下的 SQLite 冷备份文件，时间倒序。"""
    return {"items": db_backup.list_backups()}
