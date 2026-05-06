"""定时任务：每个交易日收盘后自动同步行情/财务

策略：
- 每天 16:00 拉沪深300 行情（含 PE/PB/股息率）
- 每周一 17:00 补行业 + 财务摘要

调度器随 FastAPI 启动起，停服时自动关。
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from app.database import SessionLocal
from app.services import data_sync


_scheduler: BackgroundScheduler | None = None


def _job_daily():
    logger.info("[SCHED] 每日同步行情开始")
    db = SessionLocal()
    try:
        data_sync.sync_pool_xq(db, pool="csi300")
    except Exception as e:
        logger.exception("[SCHED] 每日同步失败: {}", e)
    finally:
        db.close()


def _job_weekly():
    logger.info("[SCHED] 每周同步行业 + 财务开始")
    db = SessionLocal()
    try:
        data_sync.sync_pool_industry(db, pool="csi300")
        data_sync.sync_pool_financial(db, pool="csi300")
    except Exception as e:
        logger.exception("[SCHED] 每周同步失败: {}", e)
    finally:
        db.close()


def start():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    # 周一到周五 16:00 同步行情
    _scheduler.add_job(_job_daily, CronTrigger(day_of_week="mon-fri", hour=16, minute=0), id="daily_xq")
    # 每周一 17:00 同步行业 + 财务
    _scheduler.add_job(_job_weekly, CronTrigger(day_of_week="mon", hour=17, minute=0), id="weekly_fin")
    _scheduler.start()
    logger.info("[SCHED] 已启动，已注册 {} 个任务", len(_scheduler.get_jobs()))


def stop():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[SCHED] 已停止")
