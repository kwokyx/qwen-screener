#!/usr/bin/env bash
# 一键启动后端 + 前端的开发服务。Ctrl-C 同时停掉两个。
# 用法：./dev.sh

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

# 清理旧进程
pkill -f "uvicorn app.main" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
sleep 1

# 启动后端
cd "$ROOT/backend"
if [ ! -d .venv ]; then
  echo "❌ backend/.venv 不存在，请先 python -m venv .venv && pip install -r requirements.txt"
  exit 1
fi
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000 --log-level warning &
BACKEND_PID=$!

# 启动前端
cd "$ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

# Ctrl-C 同时杀掉两个
cleanup() {
  kill $BACKEND_PID 2>/dev/null || true
  kill $FRONTEND_PID 2>/dev/null || true
  pkill -f "uvicorn app.main" 2>/dev/null || true
  pkill -f "vite" 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

echo ""
echo "════════════════════════════════════════"
echo "  前端  →  http://localhost:5173/"
echo "  后端  →  http://127.0.0.1:8000/docs"
echo "  按 Ctrl-C 停止"
echo "════════════════════════════════════════"
echo ""

wait
