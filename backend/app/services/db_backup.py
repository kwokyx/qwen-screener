"""SQLite 自动备份。

容器内数据库挂在卷 backend_data 上（/app/data/stock.db）。
卷虽然会跟着 docker compose down -v 一起被删，但更常见的事故是误删 / 误改表，
或者 sync_basic 拿到上游空数据把 stock_basic 写残。一次冷备份够回滚到 6h 前。

策略：
- 每 6h 一次，scheduler 调度
- 启动时立刻拍一次（防止启动后立刻被新 bug 写坏）
- 复制到 /app/data/backups/stock-YYYYMMDDHHMM.db
- 保留最近 BACKUP_KEEP 份，自动清理
- 用 sqlite3.Connection.backup() 在线快照，比 shutil.copy 安全（不抓写入中状态）
- 单元测试用 in-memory DB，_resolve_db_path 返回 None 直接 skip，不污染测试
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from loguru import logger

from app.config import settings


BACKUP_KEEP = 10


def _resolve_db_path() -> Path | None:
    """从 settings.database_url 解析 sqlite 文件路径。

    非 sqlite / 内存库 / 空路径返回 None，调用方应跳过备份。
    """
    url = settings.database_url or ""
    if not url.startswith("sqlite"):
        return None
    # sqlite:///./stock.db    → "./stock.db"        (相对路径，3 斜杠)
    # sqlite:////app/stock.db → "/app/stock.db"     (绝对路径，4 斜杠)
    # sqlite:///:memory:      → ":memory:"
    tail = url.split("sqlite:///", 1)[-1]
    if not tail or tail.startswith(":memory:"):
        return None
    return Path(tail)


def _backup_dir(db_path: Path) -> Path:
    return db_path.parent / "backups"


def backup_now() -> dict:
    """在线快照一份当前 SQLite，到 backups/stock-YYYYMMDDHHMM.db。

    返回 {status, file?, size?, removed?, reason?}。
    任何异常都吞掉并以 status=failed 返回，不让备份失败拖垮调用方。
    """
    db_path = _resolve_db_path()
    if db_path is None:
        return {"status": "skipped", "reason": "non-file-sqlite"}
    if not db_path.exists():
        return {"status": "skipped", "reason": "db-not-exists", "path": str(db_path)}

    bk_dir = _backup_dir(db_path)
    try:
        bk_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.exception("[BACKUP] 创建目录失败: {}", e)
        return {"status": "failed", "reason": f"mkdir: {e}"}

    ts = datetime.now().strftime("%Y%m%d%H%M")
    target = bk_dir / f"stock-{ts}.db"

    try:
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(target))
        try:
            with dst:
                src.backup(dst)
        finally:
            src.close()
            dst.close()
    except Exception as e:
        logger.exception("[BACKUP] sqlite backup 失败: {}", e)
        # 兜底 shutil.copy2，避免极端情况下完全没备份
        try:
            import shutil
            shutil.copy2(db_path, target)
        except Exception as e2:
            return {"status": "failed", "reason": f"backup: {e}; copy: {e2}"}

    # 保留最近 BACKUP_KEEP 份
    files = sorted(
        bk_dir.glob("stock-*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for old in files[BACKUP_KEEP:]:
        try:
            old.unlink()
            removed += 1
        except Exception as e:
            logger.warning("[BACKUP] 删除旧备份失败 {}: {}", old, e)

    size = target.stat().st_size if target.exists() else 0
    logger.info(
        "[BACKUP] 完成：{} ({:.1f} MB)，保留 {} 份，清理 {} 份",
        target.name, size / 1e6, min(len(files), BACKUP_KEEP), removed,
    )
    return {
        "status": "ok",
        "file": target.name,
        "size": size,
        "removed": removed,
    }


def list_backups() -> list[dict]:
    """列出当前所有备份文件，按时间倒序。"""
    db_path = _resolve_db_path()
    if db_path is None:
        return []
    bk_dir = _backup_dir(db_path)
    if not bk_dir.exists():
        return []
    out: list[dict] = []
    for p in sorted(bk_dir.glob("stock-*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = p.stat()
        out.append({
            "file": p.name,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        })
    return out
