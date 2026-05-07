from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock import StockBasic, StockDaily, StockFinancial
from app.services import cache, qwen_client, scheduler


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
def trigger_sync(job_name: str):
    """手动触发一个 sync 任务（前端"立即更新"按钮用）。
    可选 job_name：daily_market / daily_value / weekly_fundamentals / weekly_basic
    """
    try:
        meta = scheduler.run_now(job_name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"job": job_name, "meta": meta}
