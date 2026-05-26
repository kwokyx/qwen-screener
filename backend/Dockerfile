# 多阶段构建：编译期 + 运行期分离，减小最终镜像
# 编译期需要 gcc 等编译 wheel；运行期只要 slim
FROM python:3.10-slim AS builder

# 关闭字节码 + 不缓存 pip
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ===== 关键改动：换阿里云源 =====
# Debian 12 (bookworm) 换源方式
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list 2>/dev/null; \
    true

# 系统依赖：pandas/numpy 偶尔需要 gcc 编译；slim 没自带
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 先 copy requirements 单独装，能利用 docker layer cache
COPY requirements.txt .

# ===== 关键改动：pip 换清华源（比阿里源快） =====
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --user --no-warn-script-location -r requirements.txt


# ---- 运行阶段 ----
FROM python:3.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/root/.local/bin:$PATH

WORKDIR /app

# 从 builder 拷贝已装好的 site-packages
COPY --from=builder /root/.local /root/.local

# 拷贝代码 + 测试（tests 体积小，留在镜像里方便 `docker exec ... pytest`）
COPY app ./app
COPY tests ./tests
COPY scripts ./scripts

# 暴露 FastAPI 默认端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/market/ticker', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]