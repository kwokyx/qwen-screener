"""命令行数据同步脚本

支持两种数据源（由 DATA_PROVIDER 环境变量控制，默认 baostock）。

baostock 命令：
    python -m scripts.sync_data basic                拉取全 A 股基本信息
    python -m scripts.sync_data daily [days_back]    拉取全市场日 K 线（默认最近 5 个自然日）
    python -m scripts.sync_data kline [code] [days]  拉取单只股票 K 线（code 如 600519.SH，days 默认 120）
    python -m scripts.sync_data financial [pool]     拉取财务指标（pool: csi300|csi500|all）
    python -m scripts.sync_data full                 全量: basic + daily(10d) + financial(all)

AKShare legacy 命令（DATA_PROVIDER=akshare 时可用）：
    python -m scripts.sync_data basic-ak              AKShare 全 A 股基本信息
    python -m scripts.sync_data daily-sina            AKShare 新浪全市场
    python -m scripts.sync_data pool [csi300|csi500]  AKShare 雪球逐只
    python -m scripts.sync_data industry [pool]       AKShare 行业补充
    python -m scripts.sync_data financial-ak [pool]   AKShare 财务指标
"""
import os
import sys

from app.database import Base, SessionLocal, engine
from app.services import data_sync
from app.config import settings


def main():
    Base.metadata.create_all(bind=engine)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "full"
    db = SessionLocal()

    try:
        if cmd == "basic":
            if settings.data_provider == "baostock":
                data_sync.sync_basic_bs(db)
            else:
                data_sync.sync_basic(db)

        elif cmd == "basic-ak":
            data_sync.sync_basic(db)

        elif cmd == "daily":
            days_back = int(sys.argv[2]) if len(sys.argv) > 2 else 5
            if settings.data_provider == "baostock":
                data_sync.sync_daily_bs(db, days_back=days_back)
            else:
                data_sync.sync_daily_sina(db)

        elif cmd == "daily-sina":
            data_sync.sync_daily_sina(db)

        elif cmd == "daily-em":
            data_sync.sync_full_valuation_em(db)

        elif cmd == "kline":
            code = sys.argv[2] if len(sys.argv) > 2 else "600519.SH"
            days = int(sys.argv[3]) if len(sys.argv) > 3 else 120
            if settings.data_provider == "baostock":
                data_sync.sync_kline_bs(db, code, days)
            else:
                data_sync.backfill_kline_single(db, code, days)

        elif cmd == "financial":
            pool = sys.argv[2] if len(sys.argv) > 2 else "csi300"
            if settings.data_provider == "baostock":
                data_sync.sync_financial_bs(db, pool=pool)
            else:
                data_sync.sync_pool_financial(db, pool=pool)

        elif cmd == "financial-ak":
            pool = sys.argv[2] if len(sys.argv) > 2 else "csi300"
            data_sync.sync_pool_financial(db, pool=pool)

        elif cmd == "pool":
            pool = sys.argv[2] if len(sys.argv) > 2 else "csi300"
            data_sync.sync_pool_xq(db, pool=pool)

        elif cmd == "industry":
            pool = sys.argv[2] if len(sys.argv) > 2 else "csi300"
            data_sync.sync_pool_industry(db, pool=pool)

        elif cmd == "full":
            if settings.data_provider == "baostock":
                print("[BAOSTOCK] 全量同步：基本信息 → 日K线(10d) → 财务指标(all)")
                data_sync.sync_basic_bs(db)
                data_sync.sync_daily_bs(db, days_back=10)
                data_sync.sync_financial_bs(db, pool="all")
            else:
                pool = sys.argv[2] if len(sys.argv) > 2 else "csi300"
                print("[AKShare] 全量同步：basic → pool → industry → financial")
                data_sync.sync_basic(db)
                data_sync.sync_pool_xq(db, pool=pool)
                data_sync.sync_pool_industry(db, pool=pool)
                data_sync.sync_pool_financial(db, pool=pool)

        else:
            print(__doc__)
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
