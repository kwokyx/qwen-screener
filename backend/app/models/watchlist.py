from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code: Mapped[str] = mapped_column(String(16), index=True)
    note: Mapped[str | None] = mapped_column(String(255))
    # 价格预警规则。结构 = [{id, type, threshold, enabled, lastTriggered}, ...]
    # 前端 stores/watchlist.js evaluateAlerts 解析。SQLite 用 TEXT + JSON 序列化。
    alerts: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    # 加入时的基准价（用于 pct_up / pct_down 类预警的"自加入起"计算）
    ref_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_user_code", "user_id", "code", unique=True),)
