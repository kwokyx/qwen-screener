# Commit 规范

本仓库所有 commit 遵循 [Conventional Commits](https://www.conventionalcommits.org/) 风格。
目的：让 `git log --oneline` 一眼能看出每次改动的性质 + 影响范围；写论文 / 答辩 PPT 时也好截。

## 格式

```
<type>(<scope>): <subject>

[可选 body：解释"为什么"，不是"什么"]

[可选 footer：BREAKING CHANGE / Closes #issue]
```

- 全部小写（type / scope）
- subject ≤ 50 字，中英文均可，**用现在时祈使句**："add" 不是 "added"
- subject 末尾**不加句号**
- body 与 subject 之间空一行
- 一个 commit 只做一件事；不要把"加功能 + 修 bug + 删旧代码"塞一起

## type（必填，七选一）

| type | 何时用 |
|---|---|
| `feat` | 新功能（用户能感知的） |
| `fix` | bug 修复 |
| `refactor` | 重构（不改外部行为） |
| `perf` | 性能优化 |
| `docs` | 只改文档 / 注释 |
| `style` | 格式 / 缩进 / 命名（不改逻辑） |
| `test` | 加测试 / 改测试 |
| `chore` | 构建脚本、依赖升级、配置文件等杂项 |
| `ci` | 持续集成相关 |

## scope（可选，但推荐写）

按模块或功能区划分。本项目常用：

**后端**
- `backend` 通用后端
- `auth` JWT / 登录 / 注册
- `screener` 筛选引擎、`/screener` 路由
- `qwen` 大模型集成、`/qwen` 路由
- `stock` 行情 / 个股 / 自选 路由
- `db` 模型 / 迁移
- `sync` 数据同步脚本

**前端**
- `frontend` 通用前端
- `dashboard` `chat` `results` `detail` `portfolio` `strategy` 各页面
- `topbar` `palette` `notif` 公共组件
- `watchlist` 自选 + 预警 store
- `theme` 配色 / 全局样式

**跨模块**
- `deps` 依赖
- `release` 打 tag / 改版本号

## subject 写作要点

✅ 推荐
- `feat(watchlist): 添加价格预警规则编辑器`
- `fix(chat): 错误状态恢复后保留上次的 query`
- `refactor(qwen): 抽出 _call() 让 dashscope/openai 公用入口`
- `chore(deps): 升级 vue 到 3.5.13`

❌ 避免
- `update files` ← 信息量为零
- `fix bug` ← 哪个 bug？
- `修改了一些东西。` ← 句末加了句号；说"一些"=没说
- `feat: Add new feature for stock alert with notification panel and websocket polling and demo mode and recovery from network failure` ← 太长，应该拆 commit

## body（可选）

写"为什么这么做"，不是"做了什么"——做了什么从 diff 里能看出来。

```
fix(alertEngine): demo 模式下首次失败后才切换

之前一旦后端 503 就立刻 demoMode=true，但开发时端口刚启
来不及响应。改成两次失败再 fallback，避免 false positive。
```

## 分支命名（建议）

- 主线：`main`
- 功能：`feat/<scope>-<short-desc>`，如 `feat/watchlist-alerts`
- 修复：`fix/<scope>-<short-desc>`
- 实验：`exp/<topic>`

## 工具

- 想自动化校验：装 [commitlint](https://commitlint.js.org/) + husky
- VS Code 插件：Conventional Commits、Git Graph

---

> 如果不确定，宁可拆细：5 个小而清晰的 commit > 1 个大杂烩。
