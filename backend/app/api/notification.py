"""通知中心路由。前端 alertEngine 触发后写入；GET 读回；POST /read 标记已读。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import NotificationIn, NotificationOut


router = APIRouter(prefix="/notifications", tags=["notifications"])


MAX_KEEP = 100


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=MAX_KEEP, ge=1, le=500),
):
    return (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(desc(Notification.fired_at))
        .limit(limit)
        .all()
    )


@router.post("", response_model=NotificationOut, status_code=201)
def create_notification(
    payload: NotificationIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = Notification(
        user_id=user.id,
        kind=payload.kind,
        tone=payload.tone,
        stock_code=payload.stock_code,
        title=payload.title,
        desc=payload.desc,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    # 单用户保留最近 MAX_KEEP 条，超出删最旧
    overflow = (
        db.query(Notification.id)
        .filter(Notification.user_id == user.id)
        .order_by(desc(Notification.fired_at))
        .offset(MAX_KEEP)
        .all()
    )
    if overflow:
        db.query(Notification).filter(
            Notification.id.in_([r.id for r in overflow])
        ).delete(synchronize_session=False)
        db.commit()

    return item


@router.post("/{notif_id}/read", response_model=NotificationOut)
def mark_read(
    notif_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(Notification)
        .filter(Notification.id == notif_id, Notification.user_id == user.id)
        .first()
    )
    if not item:
        raise HTTPException(404, "通知不存在")
    if item.dismissed_at is None:
        item.dismissed_at = datetime.utcnow()
        db.commit()
        db.refresh(item)
    return item


@router.post("/read-all", status_code=204)
def mark_all_read(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.dismissed_at.is_(None),
    ).update({"dismissed_at": now}, synchronize_session=False)
    db.commit()


@router.delete("/{notif_id}", status_code=204)
def delete_notification(
    notif_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(Notification)
        .filter(Notification.id == notif_id, Notification.user_id == user.id)
        .first()
    )
    if not item:
        raise HTTPException(404, "通知不存在")
    db.delete(item)
    db.commit()


@router.delete("", status_code=204)
def clear_all(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(Notification).filter(Notification.user_id == user.id).delete()
    db.commit()


@router.post("/push-alert", status_code=204)
def push_alert(
    payload: dict,
    db: Session = Depends(get_db),
):
    """前端预警触发后推飞书。不需要登录。"""
    from app.services.feishu import notifier as feishu

    tone = payload.get("tone", "up")
    stock = payload.get("stock", "")
    code = payload.get("code", "")
    desc = payload.get("desc", "")
    tag = payload.get("tag", "")

    feishu.push_strategy_result(
        strategy_name=f"预警触发{'📈' if tone == 'up' else '📉'}",
        items=[{"code": code, "name": f"{tag}: {stock}", "close": None, "change_pct": None}],
    )
