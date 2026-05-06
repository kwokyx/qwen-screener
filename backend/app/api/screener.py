from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.screener import NLScreenRequest, ScreenRequest, ScreenResponse
from app.services import qwen_client, screener_engine


router = APIRouter(prefix="/screener", tags=["screener"])


@router.post("", response_model=ScreenResponse)
def run_screen(req: ScreenRequest, db: Session = Depends(get_db)):
    """传统多条件筛选"""
    try:
        return screener_engine.screen(db, req)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/nl", response_model=ScreenResponse)
def run_nl_screen(req: NLScreenRequest, db: Session = Depends(get_db)):
    """自然语言筛选：千问解析 → 引擎执行"""
    try:
        parsed = qwen_client.parse_nl_query(req.query)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    try:
        result = screener_engine.screen(db, parsed)
    except ValueError as e:
        raise HTTPException(400, f"千问解析的条件无效: {e}")
    result.parsed_conditions = parsed.conditions
    return result
