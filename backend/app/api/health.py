from fastapi import APIRouter

from app.services import qwen_client


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/ai")
def ai_health():
    """前端启动时调用一次：判断 AI 上游是否可用。
    返回 {ok, latency_ms, reason}；前端据此控制 \"问千问\" 等按钮是否禁用。
    """
    return qwen_client.probe_health()
