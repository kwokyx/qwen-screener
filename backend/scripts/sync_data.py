"""命令行数据同步脚本

用法：
    python -m scripts.sync_data basic                    # A 股全量基本信息
    python -m scripts.sync_data daily-em                 # 东方财富批量行情（含 PE/PB/市值，部分网络易超时）
    python -m scripts.sync_data daily-sina               # 新浪批量行情（5500 只全市场，不含 PE/市值）
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
            try:
                data_sync.sync_full_valuation_em(db)
            except Exception as e:
                print(
                    "\n[失败] 东方财富全市场接口不可用（限流/网络断开）。\n"
                    "  1) 稍后重试: docker exec qwen-backend python -m scripts.sync_data daily-em\n"
                    "  2) 备用（仅沪深300+500 PE/市值/换手）:\n"
                    "     docker exec qwen-backend python -m scripts.sync_data pool csi300\n"
                    "     docker exec qwen-backend python -m scripts.sync_data pool csi500\n"
                    f"\n原始错误: {e}\n",
                    file=sys.stderr,
                )
                sys.exit(1)
        elif cmd == "daily-sina":
            data_sync.sync_daily_sina(db)
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
