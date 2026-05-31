from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.strategy import (
    StrategyAgentRequest,
    StrategyAgentResponse,
    StrategySelectRequest,
    StrategySelectResponse,
    StrategyTemplate,
    StrategyToolInfo,
)
from app.services import strategy_selector


router = APIRouter(prefix="/strategy", tags=["strategy"])


@router.get("/templates", response_model=list[StrategyTemplate])
def templates():
    """返回内置策略选股模板。"""
    return strategy_selector.list_templates()


@router.get("/tools", response_model=list[StrategyToolInfo])
def tools():
    """返回 Agent 当前可调用的选股工具和字段边界。"""
    return strategy_selector.list_agent_tools()


@router.post("/select", response_model=StrategySelectResponse)
def select(req: StrategySelectRequest, db: Session = Depends(get_db)):
    """执行策略选股，返回当前命中的股票列表。"""
    try:
        return strategy_selector.run_strategy_selection(db, req.strategy_id, req.limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/agent", response_model=StrategyAgentResponse)
def agent(req: StrategyAgentRequest, db: Session = Depends(get_db)):
    """Agent 选股：自然语言目标 -> 工具规划 -> 调用筛选/策略工具。"""
    try:
        return strategy_selector.run_agent_selection(db, req.query, req.limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
