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
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import settings
from app.schemas.screener import ScreenRequest


PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


# ---------------------- OpenAI / Responses API 调用 ----------------------

def _openai_client():
    if not settings.openai_api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，请在 backend/.env 中填入")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai 未安装，请 pip install -r requirements.txt") from e
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)


def _openai_call(prompt: str, *, json_mode: bool = False) -> str:
    """调用模型并取出纯文本输出。优先使用 Responses API，失败回退 Chat Completions。"""
    client = _openai_client()
    model = settings.openai_model
    effort = settings.openai_reasoning or "high"

    # ---- 1. 尝试 Responses API ----
    try:
        kwargs: dict[str, Any] = {"model": model, "input": prompt}
        if effort:
            kwargs["reasoning"] = {"effort": effort}
        if json_mode:
            # 不同 SDK 版本字段名可能不同，失败也能兜到 chat.completions
            kwargs["text"] = {"format": {"type": "json_object"}}
        resp = client.responses.create(**kwargs)
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
        logger.warning("Responses API 返回空文本: {}", resp)
    except Exception as e:
        logger.warning("Responses API 失败，回退 chat.completions: {}", e)

    # ---- 2. 回退 Chat Completions ----
    cc_kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
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
    """生成 token chunk 的迭代器。

    用 httpx 直接解析 SSE：openai-python 的 Stream 对某些中转返回的 chunk
    （如 id 前缀为 'resp_' 的）会因 pydantic 校验而吃掉事件，这里绕过 SDK。
    """
    if not settings.openai_api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY")
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

    with httpx.stream("POST", url, headers=headers, json=payload, timeout=120.0) as r:
        if r.status_code != 200:
            body = r.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"上游 {r.status_code}: {body}")
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                logger.debug("跳过非 JSON SSE 帧: {}", data[:80])
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
