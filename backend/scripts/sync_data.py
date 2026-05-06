"""命令行数据同步脚本

用法：
    python -m scripts.sync_data basic                    # A 股全量基本信息
    python -m scripts.sync_data daily-em                 # 东方财富批量行情（如可用）
    python -m scripts.sync_data pool [csi300|csi500|sse50]    # 雪球逐只行情 + 股息率
    python -m scripts.sync_data industry [pool]          # 补行业 + 上市时间
    python -m scripts.sync_data financial [pool]         # 补 ROE / 营收 / 净利等财务指标
    python -m scripts.sync_data full [pool]              # basic + pool + industry + financial（约 5 分钟）
"""
import sys

from app.database import Base, SessionLocal, engine
from app.services import data_sync


def main():
    Base.metadata.create_all(bind=engine)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "full"
    pool = sys.argv[2] if len(sys.argv) > 2 else "csi300"

    db = SessionLocal()
    try:
        if cmd == "basic":
            data_sync.sync_basic(db)
        elif cmd == "daily-em":
            data_sync.sync_daily_em(db)
        elif cmd == "pool":
            data_sync.sync_pool_xq(db, pool=pool)
        elif cmd == "industry":
            data_sync.sync_pool_industry(db, pool=pool)
        elif cmd == "financial":
            data_sync.sync_pool_financial(db, pool=pool)
        elif cmd == "full":
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
