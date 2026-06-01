"""Chat 对话历史持久化路由。

设计原则：
- 服务端只做对自然语言筛选结果的"快照存储"，不参与 AI 调用
- 上限 MAX_KEEP 条 / 用户：写入时若超限，删最旧的，避免 chat_sessions 无限膨胀
- 删除单条 / 清空 全部 都支持，前端 store 在登录态下同步调用
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.chat import ChatSession
from app.models.user import User
from app.schemas.chat import ChatSessionIn, ChatSessionOut


router = APIRouter(prefix="/chat", tags=["chat"])


MAX_KEEP = 50


@router.get("/sessions", response_model=list[ChatSessionOut])
def list_sessions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=MAX_KEEP, ge=1, le=200),
):
    """按时间倒序返回当前用户最近 limit 条会话快照。"""
    return (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id)
        .order_by(desc(ChatSession.created_at))
        .limit(limit)
        .all()
    )


@router.post("/sessions", response_model=ChatSessionOut, status_code=201)
def create_session(
    payload: ChatSessionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = ChatSession(
        user_id=user.id,
        query=payload.query,
        parsed_conditions=payload.parsed_conditions,
        items=payload.items,
        total=payload.total,
        screen_meta=payload.screen_meta,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    # 单用户保留最近 MAX_KEEP 条，多出来的从最旧开始删
    overflow = (
        db.query(ChatSession.id)
        .filter(ChatSession.user_id == user.id)
        .order_by(desc(ChatSession.created_at))
        .offset(MAX_KEEP)
        .all()
    )
    if overflow:
        db.query(ChatSession).filter(
            ChatSession.id.in_([r.id for r in overflow])
        ).delete(synchronize_session=False)
        db.commit()

    return item


@router.put("/sessions/{session_id}", response_model=ChatSessionOut)
def update_session(
    session_id: int,
    payload: ChatSessionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """覆盖更新一条会话快照。

    前端把多轮 thread 放在 screen_meta.thread 中；这里保持 JSON 透传，
    兼容旧的单轮快照结构。
    """
    item = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == user.id)
        .first()
    )
    if not item:
        raise HTTPException(404, "会话不存在")

    item.query = payload.query
    item.parsed_conditions = payload.parsed_conditions
    item.items = payload.items
    item.total = payload.total
    item.screen_meta = payload.screen_meta
    db.commit()
    db.refresh(item)
    return item


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == user.id)
        .first()
    )
    if not item:
        raise HTTPException(404, "会话不存在")
    db.delete(item)
    db.commit()


@router.delete("/sessions", status_code=204)
def clear_sessions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(ChatSession).filter(ChatSession.user_id == user.id).delete()
    db.commit()
