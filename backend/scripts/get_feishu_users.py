"""飞书用户列表查询脚本 — 帮你找到自己的 open_id。

用法:
    FEISHU_APP_ID=cli_xxx FEISHU_APP_SECRET=xxx python scripts/get_feishu_users.py
"""

import os
import httpx

APP_ID = os.environ.get("FEISHU_APP_ID", "")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")

if not APP_ID or not APP_SECRET:
    print("请设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET 环境变量")
    exit(1)

# 1. 获取 tenant_access_token
resp = httpx.post(
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    json={"app_id": APP_ID, "app_secret": APP_SECRET},
    timeout=10,
)
body = resp.json()
if body.get("code") != 0:
    print(f"获取 token 失败: {body}")
    exit(1)
token = body["tenant_access_token"]
print(f"token 获取成功")

# 2. 列出用户
resp = httpx.get(
    "https://open.feishu.cn/open-apis/contact/v3/users",
    headers={"Authorization": f"Bearer {token}"},
    params={"page_size": 50},
    timeout=10,
)
body = resp.json()
if body.get("code") != 0:
    print(f"获取用户列表失败: {body}")
    exit(1)

users = body.get("data", {}).get("items", [])
if not users:
    print("未找到用户，请确认应用权限已配置 contact:user:readonly")
    exit(1)

print(f"\n找到 {len(users)} 个用户：\n")
for u in users:
    name = u.get("name", "?")
    open_id = u.get("open_id", "")
    email = u.get("email", "")
    print(f"  {name}  open_id={open_id}  email={email}")
