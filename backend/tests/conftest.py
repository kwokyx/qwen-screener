"""pytest 公共 fixture：独立测试 DB + 一组种子股票，避免污染开发库。

⚠️ 关键：必须在 import app.* 之前强制覆盖 DATABASE_URL（不能用 setdefault）。
docker exec 容器内跑 pytest 时，DATABASE_URL 已经被 docker-compose env 设成
sqlite:////app/data/stock.db。如果 setdefault 不覆盖，conftest 的 db fixture
就会 drop_all() 把生产数据全清掉。这条踩过坑，别改。

为什么不用 sqlite:///:memory:：
内存 SQLite 是 per-connection 的——SQLAlchemy 每开新连接就是新库。db fixture
建好表后，TestClient 的 lifespan / 路由处理用的是不同连接，看不到那些表。
用一个独立的临时文件就稳了，drop_all + create_all 仍然每个测试一刷。
"""
import os
import sys

# 用独立文件，跟 /app/data/stock.db 完全隔离
os.environ["DATABASE_URL"] = "sqlite:////tmp/pytest_qwen.db"
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-chars-long-xxxx")
os.environ.setdefault("REDIS_URL", "")  # 关闭缓存，避免连真 redis

import pytest
from datetime import date, timedelta
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app import models  # noqa: F401  注册 ORM
from app.models.stock import StockBasic, StockDaily, StockFinancial


@pytest.fixture(scope="function")
def db():
    """每个测试一个全新的 in-memory DB。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def seed_stocks(db: Session):
    """5 只代表性股票：覆盖银行 / 白酒 / 半导体 / 家电 / 食品。"""
    today = date.today()
    yesterday = today - timedelta(days=1)
    rows = [
        # (code, name, industry, pe, pb, roe, mc)
        ("600036.SH", "招商银行",   "银行",       6.5,  0.85,  16.5,  9000),
        ("600519.SH", "贵州茅台",   "白酒",       24.0, 8.0,   28.0,  21000),
        ("688981.SH", "中芯国际",   "半导体",     45.0, 2.9,   8.0,   6200),
        ("000333.SZ", "美的集团",   "白色家电",   13.5, 2.3,   22.0,  4500),
        ("000596.SZ", "古井贡酒",   "饮料",       18.5, 4.0,   24.0,  900),
    ]
    for code, name, industry, pe, pb, roe, mc in rows:
        db.add(StockBasic(code=code, name=name, industry=industry, market="主板"))
        db.add(StockDaily(code=code, trade_date=yesterday, close=10.0, pe=pe, pb=pb, market_cap=mc))
        db.add(StockDaily(code=code, trade_date=today,     close=11.0, pe=pe, pb=pb, market_cap=mc))
        db.add(StockFinancial(code=code, report_date=today, roe=roe))
    db.commit()
    return rows
