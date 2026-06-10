# Railway 部署指南

本文档用于把当前项目部署到 Railway。项目按现有边界拆成三个服务：

| 服务 | Root Directory | 说明 |
|---|---|---|
| `backend` | `/backend` | FastAPI API、定时同步、SQLite 数据卷、AI Agent |
| `frontend` | `/frontend` | Vue 构建产物 + nginx，同源反代 `/api/*` 到后端 |
| `redis` | Railway Redis | 可选缓存；没有 Redis 时业务仍可运行，但建议生产启用 |

## 一、部署前检查

本地先确认不要把真实密钥和数据库文件提交到 Git：

```bash
git status --short --branch
git diff --check
rg -n "sk-|OPENAI_API_KEY=|DASHSCOPE_API_KEY=|FEISHU_.*=" \
  backend/app backend/tests backend/scripts frontend/src frontend/scripts \
  docker-compose.yml README.md docs backend/.env.example || true
```

`.env`、`*.db`、`*.sqlite*` 已在 `.gitignore` 中忽略，真实密钥只在 Railway Variables 页面填写。

## 二、创建 Railway 服务

推荐从 GitHub 仓库创建服务。

1. 新建 Railway Project。
2. 添加 Redis 服务，命名建议为 `redis`。
3. 添加 GitHub Repo 服务作为后端：
   - Service Name：`backend`
   - Root Directory：`/backend`
   - Config File：`/backend/railway.toml`
4. 添加同一个 GitHub Repo 服务作为前端：
   - Service Name：`frontend`
   - Root Directory：`/frontend`
   - Config File：`/frontend/railway.toml`
5. 给 `frontend` 生成 Public Domain。`backend` 可以生成 Public Domain 方便调试，也可以只通过内网给前端访问。

Railway 的 monorepo 服务需要单独设置 Root Directory；本仓库的 `railway.toml` 放在子目录下，所以 Config File 也要填绝对路径。

## 三、后端变量

在 `backend` 服务的 Variables 中配置：

```bash
PORT=8000
DEBUG=False
DATABASE_URL=sqlite:////app/data/stock.db
REDIS_URL=${{redis.REDIS_URL}}
SECRET_KEY=<生成一段至少32位的随机字符串>
ACCESS_TOKEN_EXPIRE_MINUTES=1440

AI_BACKEND=<保持与你本地一致>
OPENAI_API_KEY=<在Railway里填写真实Key>
OPENAI_BASE_URL=<保持与你本地一致>
OPENAI_MODEL=<保持与你本地一致>
OPENAI_RESPONSES_ENABLED=false
AGENT_PLAN_TIMEOUT_SECONDS=10
AGENT_REACT_STEP_TIMEOUT_SECONDS=18

CORS_ORIGINS=https://${{frontend.RAILWAY_PUBLIC_DOMAIN}}

FEISHU_WEBHOOK_URL=
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_CHAT_ID=
FEISHU_OPEN_ID=
FEISHU_EMAIL=
```

如果不使用 Redis，可把 `REDIS_URL` 留空。飞书变量不填时不会推送。

## 四、后端数据卷

后端使用 SQLite 时必须挂载 Railway Volume，否则重部署后数据库会丢失。

在 `backend` 服务添加 Volume：

```text
Mount Path: /app/data
```

后端变量中的 `DATABASE_URL=sqlite:////app/data/stock.db` 必须和这个路径一致。

## 五、前端变量

在 `frontend` 服务的 Variables 中配置：

```bash
BACKEND_PROXY_URL=http://backend.railway.internal:8000
```

如果后端服务名不是 `backend`，把域名改为实际服务名，例如：

```bash
BACKEND_PROXY_URL=http://<service-name>.railway.internal:8000
```

如果 Railway 私网在当前区域连接超时，也可以给 `backend` 生成一个 Railway Public Domain，并把这里改成后端公网 HTTPS 域名：

```bash
BACKEND_PROXY_URL=https://<backend-domain>
```

前端 nginx 会在容器启动时读取 Railway 注入的 `PORT`，并把 `/api/*` 反代到 `BACKEND_PROXY_URL`。浏览器始终访问前端域名，不直接跨域请求后端。

## 六、首次初始化数据

首次部署成功后，后端数据库是空的。进入 Railway 后端服务的 Shell/SSH，执行一次：

```bash
python -m scripts.sync_data full
```

如果只想先让页面快速有基础数据，可以分步执行：

```bash
python -m scripts.sync_data basic
python -m scripts.sync_data daily 10
python -m scripts.sync_data financial all
python -m scripts.sync_data dividend
```

初始化完成后，后端的 APScheduler 会继续按东八区定时同步：

| 时间 | 任务 |
|---|---|
| 周一-周五 15:05 | 行情快刷 |
| 周一-周五 15:30 | 全市场日 K |
| 周一-周五 16:00 | 价值面补充 |
| 周一-周五 18:00 | 策略扫描和飞书推送 |
| 周六 02:00 | 财务摘要 |
| 周六 03:00 | 分红数据 |
| 周日 02:00 | 股票列表 |
| 周日 03:00 | K 线回填 |
| 每 6 小时 | SQLite 备份 |

## 七、上线验证

部署后用前端域名验证：

```bash
curl -s https://<frontend-domain>/api/v1/health/data
curl -s https://<frontend-domain>/api/v1/health/ai
curl -s 'https://<frontend-domain>/api/v1/market/overview?sector_limit=100&movers_limit=10'
curl -s https://<frontend-domain>/api/v1/market/indices
```

浏览器检查：

| 页面 | 验证点 |
|---|---|
| `/login` | 验证码、注册、登录 |
| `/dashboard` | 大盘、板块、数据新鲜度 |
| `/chat` | AI 选股、普通对话、SSE 流式返回 |
| `/results` | 条件筛选、批量加入自选 |
| `/strategy` | 条件选股、策略选股 |
| `/portfolio` | 自选、排序、批量编辑、预警启停 |
| `/detail/600036.SH` | 本地详情、K 线、千问解读 |

如果 `/health/data` 显示 `fresh=false`，优先看 `sync_warnings` 和 `recommended_jobs`。不要手动把 `fresh` 改成 true，应重新运行对应同步任务。

## 八、常见问题

| 现象 | 处理 |
|---|---|
| Railway 提示 Application failed to respond | 确认服务监听 `0.0.0.0:$PORT`；本项目 Dockerfile 已处理 |
| 前端能打开但 API 404/502 | 检查 `BACKEND_PROXY_URL` 是否为 `http://backend.railway.internal:8000` |
| 数据重部署后丢失 | 检查 backend Volume 是否挂载到 `/app/data` |
| AI 暂不可用 | 检查 AI Key、base URL、模型名和上游网络；系统会安全降级，不会伪造筛选结果 |
| Redis 连接失败 | 检查 `REDIS_URL` 引用变量；也可临时留空禁用缓存 |
| Dashboard 首屏仍慢 | Redis 只减少后端计算，不能消除 Railway 公网/TLS/区域延迟；优先确认 `/market/overview` 已部署并被前端调用 |
| 数据为空 | 在 backend Shell/SSH 执行 `python -m scripts.sync_data full` |
