"""通知中心持久化模型。

alertEngine 触发的价格预警 + 系统消息都通过这张表跨刷新 / 跨设备保留。
dismissed_at IS NULL 表示未读；用户点了"标记已读"或后端 push 走 PATCH 把它置为
当前时间。删除则物理 delete。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))    # alert / system
    tone: Mapped[str | None] = mapped_column(String(16), nullable=True)  # up / down / qwen / amber
    stock_code: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    stock_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(128))
    desc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    fired_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
