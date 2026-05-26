"""Chat 对话历史持久化模型。

每条 ChatSession 对应"一次完整 NL 筛选"的快照：用户原 query + 解析后的条件 +
返回前 N 只命中股票 + 总数 + 筛选 meta。点历史能一键还原结果视图，不需要重跑 AI。

字段在 schemas/chat.py 对应 ChatSessionOut 暴露给前端。
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    query: Mapped[str] = mapped_column(String(512))
    parsed_conditions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    items: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 前 N 只命中股票快照
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
