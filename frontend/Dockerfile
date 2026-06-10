# ---- Build 阶段：用 Node 构建 dist/ ----
FROM node:20-alpine AS builder

WORKDIR /app

# 利用 layer cache：单独 copy package.json 装依赖
COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build


# ---- 运行阶段：nginx 静态服务 + /api 反代到 backend ----
FROM nginx:alpine AS runtime

# 移除默认配置
RUN rm /etc/nginx/conf.d/default.conf

ENV PORT=80 \
    BACKEND_PROXY_URL=http://backend:8000

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

# 健康检查：拉一下首页
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q --spider "http://127.0.0.1:${PORT:-80}/" || exit 1

CMD ["nginx", "-g", "daemon off;"]
