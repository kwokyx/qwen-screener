"""轻量 SQLite migrations。

为什么不用 Alembic：本项目只有少量 schema 演进，每条只是给已有表加列。
Alembic 配置 + 版本文件比这些 ALTER 重得多，等表数量真上去再换。

策略：try ALTER TABLE ADD COLUMN，已存在的列 SQLite 抛 "duplicate column name"，
吞掉视为已应用。其它错误 log warning，不中断启动。
"""
from loguru import logger
from sqlalchemy import text


# 顺序追加新条目；不要修改/删除已存在的条目（无版本表，重复执行靠 SQLite 报错兜底）
_MIGRATIONS: list[str] = [
    # P0-3 watchlist 后端同步：alerts JSON + 加入时的基准价
    "ALTER TABLE watchlist ADD COLUMN alerts JSON",
    "ALTER TABLE watchlist ADD COLUMN ref_price FLOAT",
    # 旧版 baostock K 线把原本单位为元的成交额错误除以 10000。
    # 用成交额 / (收盘价 * 成交量) 比例识别并幂等修复，不影响正常行情。
    "UPDATE stock_daily SET amount = amount * 10000 "
    "WHERE amount IS NOT NULL AND close > 0 AND volume > 0 "
    "AND amount / (close * volume) BETWEEN 0.000001 AND 0.001",
    # Agent 对话结果后端持久化：Results 页可通过 ctx 恢复当前用户的筛选快照。
    "ALTER TABLE chat_sessions ADD COLUMN context_id VARCHAR(128)",
    "ALTER TABLE chat_sessions ADD COLUMN agent_plan JSON",
    "ALTER TABLE chat_sessions ADD COLUMN agent_answer TEXT",
    "ALTER TABLE chat_sessions ADD COLUMN tool_trace JSON",
    "ALTER TABLE chat_sessions ADD COLUMN tool_calls JSON",
    "ALTER TABLE chat_sessions ADD COLUMN result_snapshot JSON",
    "ALTER TABLE chat_sessions ADD COLUMN updated_at DATETIME",
    "CREATE INDEX IF NOT EXISTS ix_chat_sessions_context_id ON chat_sessions(context_id)",
    "CREATE INDEX IF NOT EXISTS ix_chat_sessions_updated_at ON chat_sessions(updated_at)",
]


def apply_sqlite_migrations(engine) -> int:
    applied = 0
    with engine.begin() as conn:
        for stmt in _MIGRATIONS:
            try:
                conn.execute(text(stmt))
                logger.info("[MIGRATE] applied: {}", stmt)
                applied += 1
            except Exception as e:
                msg = str(e).lower()
                if "duplicate column" in msg or "already exists" in msg:
                    continue
                logger.warning("[MIGRATE] {} 失败: {}", stmt, str(e)[:200])
    return applied
