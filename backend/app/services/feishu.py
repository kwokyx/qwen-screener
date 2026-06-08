"""飞书通知模块：webhook 或企业自建应用推送选股结果。

- webhook 模式：直接 POST 到飞书群机器人 URL。
- 企业应用模式：先获取 tenant_access_token，再调消息 API。
- 两种都不配置时静默跳过。
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime

import httpx

from app.config import settings
from loguru import logger


class FeishuNotifier:
    _app_token: str | None = None
    _app_token_expires_at: float = 0
    _app_token_lock = threading.Lock()

    def push_strategy_result(self, strategy_name: str, items: list[dict]) -> None:
        if not items:
            return

        is_alert = strategy_name.startswith("价格预警")
        if is_alert:
            self._push_alert_card(strategy_name, items)
        elif settings.feishu_webhook_url:
            self._push_via_webhook(strategy_name, items)
        elif settings.feishu_app_id and settings.feishu_app_secret:
            self._push_via_app(strategy_name, items)

    def _push_alert_card(self, strategy_name: str, items: list[dict]) -> None:
        s = items[0]
        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": strategy_name},
                    "template": "red" if "📉" in strategy_name else "green",
                },
                "elements": [
                    {"tag": "div", "text": {"tag": "lark_md", "content": f"**{s.get('name', '')}**（{s.get('code', '')}）"}},
                    {"tag": "hr"},
                    {"tag": "div", "text": {"tag": "lark_md", "content": s.get("desc", s.get("tag", "预警触发"))}},
                ],
            },
        }
        if settings.feishu_webhook_url:
            self._post_card(settings.feishu_webhook_url, card)
        elif settings.feishu_app_id and settings.feishu_app_secret:
            token = self._get_app_token()
            if not token:
                return
            if settings.feishu_chat_id:
                rid, rt = settings.feishu_chat_id, "chat_id"
            elif settings.feishu_open_id:
                rid, rt = settings.feishu_open_id, "open_id"
            elif settings.feishu_email:
                rid, rt = settings.feishu_email, "email"
            else:
                return
            self._post_app_card(card, rid, rt, token, strategy_name)

    def _push_via_webhook(self, strategy_name: str, items: list[dict]) -> None:
        payload = self._build_card(strategy_name, items)
        self._post_card(settings.feishu_webhook_url, payload)

    def _push_via_app(self, strategy_name: str, items: list[dict]) -> None:
        token = self._get_app_token()
        if not token:
            logger.error(f"飞书推送跳过 [app] {strategy_name}: 无法获取 token")
            return

        payload = self._build_card(strategy_name, items)
        if settings.feishu_chat_id:
            receive_id, id_type = settings.feishu_chat_id, "chat_id"
        elif settings.feishu_open_id:
            receive_id, id_type = settings.feishu_open_id, "open_id"
        elif settings.feishu_email:
            receive_id, id_type = settings.feishu_email, "email"
        else:
            logger.error(f"飞书推送跳过 [app] {strategy_name}: 未配置 feishu_chat_id、feishu_open_id 或 feishu_email")
            return

        self._post_app_card(payload, receive_id, id_type, token, strategy_name)

    def _post_card(self, url: str, payload: dict) -> None:
        try:
            resp = httpx.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
            body = resp.json()
            if resp.status_code == 200 and body.get("code") == 0:
                logger.info(f"飞书推送成功: {body.get('code')}")
            else:
                logger.error(f"飞书推送失败: {resp.text}")
        except Exception as exc:
            logger.error(f"飞书推送异常: {exc}")

    def _post_app_card(self, payload: dict, receive_id: str = "", id_type: str = "", token: str = "", name: str = "") -> None:
        try:
            resp = httpx.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=" + id_type,
                json={
                    "receive_id": receive_id,
                    "msg_type": "interactive",
                    "content": json.dumps(payload["card"]),
                },
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=10,
            )
            body = resp.json()
            if body.get("code") == 0:
                logger.info(f"飞书推送成功 [app] {name}: 1 只")
            else:
                logger.error(f"飞书推送失败 [app] {name}: {body}")
        except Exception as exc:
            logger.error(f"飞书推送异常 [app] {name}: {exc}")

    @classmethod
    def _get_app_token(cls) -> str | None:
        now = time.monotonic()
        if cls._app_token and now < cls._app_token_expires_at - 120:
            return cls._app_token

        with cls._app_token_lock:
            if cls._app_token and now < cls._app_token_expires_at - 120:
                return cls._app_token
            try:
                resp = httpx.post(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    json={
                        "app_id": settings.feishu_app_id,
                        "app_secret": settings.feishu_app_secret,
                    },
                    timeout=10,
                )
                body = resp.json()
                if body.get("code") != 0:
                    logger.error(f"飞书 token 获取失败: {body}")
                    return None
                cls._app_token = body["tenant_access_token"]
                cls._app_token_expires_at = now + body.get("expire", 7200)
                return cls._app_token
            except Exception as exc:
                logger.error(f"飞书 token 获取异常: {exc}")
                return None

    @staticmethod
    def _build_card(strategy_name: str, items: list[dict]) -> dict:
        today = date.today().strftime("%Y-%m-%d")
        lines = []
        for i, s in enumerate(items, 1):
            code = s.get("code", "")
            name = s.get("name") or code
            close = s.get("close")
            change = s.get("change_pct")
            change_str = f" {change:+.2f}%" if change is not None else ""
            close_str = f" {close:.2f}" if close is not None else " -"
            lines.append(f"{i}. **{name}**（{code}）{close_str}{change_str}")

        stock_text = "\n".join(lines) if lines else "（暂无命中）"

        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"🔥 {strategy_name} 选股播报",
                    },
                    "template": "blue",
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": (
                                f"**日期：** {today}\n"
                                f"**策略：** {strategy_name}\n"
                                f"**选股数量：** {len(items)}"
                            ),
                        },
                    },
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**选股列表：**\n{stock_text}",
                        },
                    },
                ],
            },
        }


notifier = FeishuNotifier()
