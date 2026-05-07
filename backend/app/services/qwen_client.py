"""AI 大模型封装 (OpenAI 兼容 / Responses API)

两个核心能力：
1. parse_nl_query：自然语言 → 结构化筛选条件（JSON 模式）
2. analyze_stock：基于基本面数据生成投资分析文本

通过环境变量配置：
- OPENAI_API_KEY     必填
- OPENAI_BASE_URL    可选，默认 https://api2.up.railway.app
- OPENAI_MODEL       可选，默认 gpt-5.4
- OPENAI_REASONING   可选，默认 high
- AI_BACKEND         可选 'openai' (默认) / 'dashscope'

调用失败时抛 RuntimeError，由上层路由层转成 HTTP 503。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import settings
from app.schemas.screener import ScreenRequest


PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"

# 上游中转网络偶发抖动（Connection reset / Timeout），自动重试可消除大部分用户感知
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.8  # 第 N 次失败后等 0.8、1.6、3.2 秒
_TRANSIENT_KEYWORDS = (
    "connection reset", "connection aborted", "remotedisconnect",
    "timeout", "timed out", "broken pipe", "errno 54", "errno 60",
    "max retries exceeded", "apiconnection",
)


def _is_transient(exc: Exception) -> bool:
    s = str(exc).lower()
    name = exc.__class__.__name__.lower()
    return any(k in s for k in _TRANSIENT_KEYWORDS) or "connection" in name or "timeout" in name


def _user_friendly_error(exc: Exception) -> str:
    """把内部错误（errno、Connection reset 等）翻译成产品级提示。"""
    if _is_transient(exc):
        return "AI 服务暂时不可达，已自动重试若干次仍失败。请稍后再试。"
    s = str(exc)
    if "API_KEY" in s or "api_key" in s or "401" in s or "Unauthorized" in s:
        return "AI 服务凭证无效，请联系管理员检查配置"
    if "rate" in s.lower() and "limit" in s.lower():
        return "AI 服务请求过于频繁，请稍后再试"
    # 其他情况：给一句中文，不带 errno
    return "AI 服务调用失败，请稍后再试"


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


# ---------------------- OpenAI / Responses API 调用 ----------------------

def probe_health(timeout: float = 4.0) -> dict:
    """轻量探测上游 AI 是否可用。
    只发一个 4s 超时的 HEAD /v1/models（比真的发对话便宜得多），
    返回 {ok: bool, latency_ms: int|None, reason: str|None}。
    被 /api/v1/health/ai 调用，结果可被前端缓存几秒。
    """
    import time as _t
    if not settings.openai_api_key:
        return {"ok": False, "latency_ms": None, "reason": "未配置 OPENAI_API_KEY"}
    try:
        import httpx
        base = (settings.openai_base_url or "https://api.openai.com").rstrip("/")
        url = f"{base}/v1/models"
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        t0 = _t.time()
        # 用 GET 而非 HEAD：有些中转不实现 HEAD
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(2.0, timeout))) as c:
            r = c.get(url, headers=headers)
        latency_ms = int((_t.time() - t0) * 1000)
        if r.status_code in (200, 401, 403):
            # 401/403 也认为 reachable（说明上游能处理鉴权，只是 key 错），不是网络挂
            return {"ok": r.status_code == 200, "latency_ms": latency_ms,
                    "reason": None if r.status_code == 200 else "鉴权失败"}
        return {"ok": False, "latency_ms": latency_ms, "reason": f"HTTP {r.status_code}"}
    except Exception as e:
        msg = str(e).lower()
        if "reset" in msg or "refused" in msg or "timed out" in msg or "timeout" in msg:
            return {"ok": False, "latency_ms": None, "reason": "上游网络不可达"}
        return {"ok": False, "latency_ms": None, "reason": "服务暂时不可用"}


def _openai_client():
    if not settings.openai_api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，请在 backend/.env 中填入")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai 未安装，请 pip install -r requirements.txt") from e
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)


def _openai_call(prompt: str, *, json_mode: bool = False) -> str:
    """调用模型并取出纯文本输出。
    Responses API → 失败回退 Chat Completions；瞬时网络错误自动指数退避重试。
    最终失败抛 RuntimeError，错误消息已经过产品化措辞清洗。
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return _openai_call_once(prompt, json_mode=json_mode)
        except Exception as e:
            last_exc = e
            if not _is_transient(e) or attempt == _MAX_RETRIES - 1:
                break
            wait = _BACKOFF_BASE * (2 ** attempt)
            logger.warning("AI 调用失败 (#{}/{}, {} 秒后重试): {}", attempt + 1, _MAX_RETRIES, wait, e)
            time.sleep(wait)
    raise RuntimeError(_user_friendly_error(last_exc) if last_exc else "AI 服务调用失败")


def _openai_call_once(prompt: str, *, json_mode: bool = False) -> str:
    client = _openai_client()
    model = settings.openai_model
    effort = settings.openai_reasoning or "high"

    # ---- 1. 尝试 Responses API ----
    try:
        kwargs: dict[str, Any] = {"model": model, "input": prompt}
        if effort:
            kwargs["reasoning"] = {"effort": effort}
        if json_mode:
            kwargs["text"] = {"format": {"type": "json_object"}}
        resp = client.responses.create(**kwargs, timeout=60.0)
        text = getattr(resp, "output_text", None)
        if not text and getattr(resp, "output", None):
            chunks = []
            for item in resp.output:
                for c in getattr(item, "content", []) or []:
                    t = getattr(c, "text", None)
                    if t:
                        chunks.append(t)
            text = "\n".join(chunks)
        if text:
            return text
        logger.warning("Responses API 返回空文本，回退 chat.completions")
    except Exception as e:
        # 配置 / 鉴权类错误直接抛，不要回退
        if "401" in str(e) or "Unauthorized" in str(e):
            raise
        logger.warning("Responses API 失败，回退 chat.completions: {}", e)

    # ---- 2. 回退 Chat Completions ----
    cc_kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "timeout": 60.0,
    }
    if json_mode:
        cc_kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**cc_kwargs)
    return resp.choices[0].message.content or ""


# ---------------------- DashScope 兜底（保留以备切换） ----------------------

def _dashscope_call(prompt: str, *, json_mode: bool = False) -> str:
    if not settings.dashscope_api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY")
    try:
        import dashscope
    except ImportError as e:
        raise RuntimeError("dashscope 未安装") from e
    dashscope.api_key = settings.dashscope_api_key
    extra = {"response_format": {"type": "json_object"}} if json_mode else {}
    resp = dashscope.Generation.call(
        model=settings.qwen_model,
        prompt=prompt,
        result_format="message",
        **extra,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"千问调用失败: {resp.message}")
    return resp.output.choices[0].message.content


def _call(prompt: str, *, json_mode: bool = False) -> str:
    backend = (settings.ai_backend or "openai").lower()
    if backend == "dashscope":
        return _dashscope_call(prompt, json_mode=json_mode)
    return _openai_call(prompt, json_mode=json_mode)


# ---------------------- 流式调用 ----------------------

def _openai_stream(prompt: str):
    """生成 token chunk 的迭代器，瞬时连接错误自动重试（仅在没拿到第一个 chunk 时）。"""
    if not settings.openai_api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY")

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        got_any = False
        try:
            for chunk in _openai_stream_once(prompt):
                got_any = True
                yield chunk
            return
        except Exception as e:
            last_exc = e
            if got_any:
                # 已经吐过 token 了，半途断开不重试（避免重复内容）
                break
            if not _is_transient(e) or attempt == _MAX_RETRIES - 1:
                break
            wait = _BACKOFF_BASE * (2 ** attempt)
            logger.warning("AI 流式调用失败 (#{}/{}, {} 秒后重试): {}", attempt + 1, _MAX_RETRIES, wait, e)
            time.sleep(wait)
    raise RuntimeError(_user_friendly_error(last_exc) if last_exc else "AI 服务调用失败")


def _openai_stream_once(prompt: str):
    import httpx

    base = (settings.openai_base_url or "https://api.openai.com").rstrip("/")
    url = f"{base}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = {
        "model": settings.openai_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }

    with httpx.stream("POST", url, headers=headers, json=payload, timeout=httpx.Timeout(120.0, connect=10.0)) as r:
        if r.status_code != 200:
            body = r.read().decode("utf-8", errors="replace")[:300]
            if r.status_code in (401, 403):
                raise RuntimeError("AI 服务凭证无效，请联系管理员检查配置")
            if r.status_code == 429:
                raise RuntimeError("AI 服务请求过于频繁，请稍后再试")
            raise RuntimeError(f"上游 {r.status_code}")
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            try:
                delta = obj["choices"][0]["delta"]
                text = delta.get("content")
            except (KeyError, IndexError, TypeError):
                continue
            if text:
                yield text


def _dashscope_stream(prompt: str):
    if not settings.dashscope_api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY")
    import dashscope
    dashscope.api_key = settings.dashscope_api_key
    responses = dashscope.Generation.call(
        model=settings.qwen_model,
        prompt=prompt,
        result_format="message",
        stream=True,
        incremental_output=True,
    )
    for resp in responses:
        if resp.status_code != 200:
            raise RuntimeError(f"千问流式调用失败: {resp.message}")
        text = resp.output.choices[0].message.content
        if text:
            yield text


def stream_call(prompt: str):
    """返回 yields str 的迭代器；上层用 SSE 写出去即可。"""
    backend = (settings.ai_backend or "openai").lower()
    if backend == "dashscope":
        yield from _dashscope_stream(prompt)
    else:
        yield from _openai_stream(prompt)


def stream_analyze_stock(snapshot: dict):
    """流式生成投资分析。yields 每个 token chunk（字符串）。"""
    template = _load_prompt("stock_analysis.md")
    for k, v in snapshot.items():
        template = template.replace("{" + k + "}", "" if v is None else str(v))
    yield from stream_call(template)


# ---------------------- 业务函数 ----------------------

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    """容错地从模型输出里抠出 JSON。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return json.loads(m.group(0))
    raise RuntimeError(f"模型返回非 JSON: {text[:200]}")


def parse_nl_query(user_query: str) -> ScreenRequest:
    prompt = _load_prompt("nl_to_filter.md").replace("{user_query}", user_query)
    text = _call(prompt, json_mode=True)
    data = _extract_json(text)
    return ScreenRequest(**data)


def analyze_stock(snapshot: dict) -> str:
    template = _load_prompt("stock_analysis.md")
    for k, v in snapshot.items():
        template = template.replace("{" + k + "}", "" if v is None else str(v))
    text = _call(template, json_mode=False)
    return text.strip()
