"""轻量 SQLite migrations。

为什么不用 Alembic：本项目只有少量 schema 演进，每条只是给已有表加列。
Alembic 配置 + 版本文件比这些 ALTER 重得多，等表数量真上去再换。

策略：每条 migration 写入 schema_migrations。历史库中已存在的列/索引仍视为
已应用，但大表 UPDATE 不再每次启动重复扫描。
"""
from loguru import logger
from sqlalchemy import text


_MIGRATION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id VARCHAR(128) PRIMARY KEY,
    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


# 顺序追加新条目；不要修改/删除已存在 id。
_MIGRATIONS: list[tuple[str, str]] = [
    # P0-3 watchlist 后端同步：alerts JSON + 加入时的基准价
    ("001_watchlist_alerts", "ALTER TABLE watchlist ADD COLUMN alerts JSON"),
    ("002_watchlist_ref_price", "ALTER TABLE watchlist ADD COLUMN ref_price FLOAT"),
    # 旧版 baostock K 线把原本单位为元的成交额错误除以 10000。
    # 用成交额 / (收盘价 * 成交量) 比例识别并幂等修复，不影响正常行情。
    (
        "003_normalize_baostock_amount_unit",
        "UPDATE stock_daily SET amount = amount * 10000 "
        "WHERE amount IS NOT NULL AND close > 0 AND volume > 0 "
        "AND amount / (close * volume) BETWEEN 0.000001 AND 0.001",
    ),
    # Agent 对话结果后端持久化：Results 页可通过 ctx 恢复当前用户的筛选快照。
    ("004_chat_sessions_context_id", "ALTER TABLE chat_sessions ADD COLUMN context_id VARCHAR(128)"),
    ("005_chat_sessions_agent_plan", "ALTER TABLE chat_sessions ADD COLUMN agent_plan JSON"),
    ("006_chat_sessions_agent_answer", "ALTER TABLE chat_sessions ADD COLUMN agent_answer TEXT"),
    ("007_chat_sessions_tool_trace", "ALTER TABLE chat_sessions ADD COLUMN tool_trace JSON"),
    ("008_chat_sessions_tool_calls", "ALTER TABLE chat_sessions ADD COLUMN tool_calls JSON"),
    ("009_chat_sessions_result_snapshot", "ALTER TABLE chat_sessions ADD COLUMN result_snapshot JSON"),
    ("010_chat_sessions_updated_at", "ALTER TABLE chat_sessions ADD COLUMN updated_at DATETIME"),
    (
        "011_chat_sessions_context_id_index",
        "CREATE INDEX IF NOT EXISTS ix_chat_sessions_context_id ON chat_sessions(context_id)",
    ),
    (
        "012_chat_sessions_updated_at_index",
        "CREATE INDEX IF NOT EXISTS ix_chat_sessions_updated_at ON chat_sessions(updated_at)",
    ),
]


def _mark_applied(conn, migration_id: str):
    conn.execute(
        text("INSERT OR IGNORE INTO schema_migrations (id) VALUES (:id)"),
        {"id": migration_id},
    )


def apply_sqlite_migrations(engine) -> int:
    applied = 0
    with engine.begin() as conn:
        conn.execute(text(_MIGRATION_TABLE_DDL))
        applied_ids = {
            row[0]
            for row in conn.execute(text("SELECT id FROM schema_migrations")).all()
        }
        for migration_id, stmt in _MIGRATIONS:
            if migration_id in applied_ids:
                continue
            try:
                conn.execute(text(stmt))
                _mark_applied(conn, migration_id)
                logger.info("[MIGRATE] applied {}: {}", migration_id, stmt)
                applied += 1
            except Exception as e:
                msg = str(e).lower()
                if "duplicate column" in msg or "already exists" in msg:
                    _mark_applied(conn, migration_id)
                    continue
                logger.warning("[MIGRATE] {} 失败: {}", stmt, str(e)[:200])
    return applied
