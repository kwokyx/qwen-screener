from contextlib import asynccontextmanager
import threading
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api import auth, chat, health, market, notification, qwen, screener, stock, strategy
from app.config import settings
from app.database import Base, engine
from app import models  # noqa: F401  触发 ORM 注册
from app.services import migrations, scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("初始化数据库表...")
    Base.metadata.create_all(bind=engine)
    migrations.apply_sqlite_migrations(engine)
    scheduler.start()
    if "pytest_qwen" not in settings.database_url:
        threading.Thread(target=market.warm_market_cache, name="market-cache-warmup", daemon=True).start()
    yield
    scheduler.stop()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)


@app.middleware("http")
async def log_slow_api_requests(request: Request, call_next):
    t0 = perf_counter()
    response = await call_next(request)
    duration_ms = int((perf_counter() - t0) * 1000)
    path = request.url.path
    if path.startswith(settings.api_prefix) and (
        duration_ms >= 500
        or path.endswith("/health/data")
        or path.endswith("/quote")
        or path.endswith("/kline")
        or path == f"{settings.api_prefix}/screener"
    ):
        logger.info(
            "[REQ] {} {} status={} duration_ms={}",
            request.method,
            path,
            response.status_code,
            duration_ms,
        )
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"app": settings.app_name, "docs": "/docs"}


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(stock.router, prefix=settings.api_prefix)
app.include_router(screener.router, prefix=settings.api_prefix)
app.include_router(qwen.router, prefix=settings.api_prefix)
app.include_router(strategy.router, prefix=settings.api_prefix)
app.include_router(market.router, prefix=settings.api_prefix)
app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(notification.router, prefix=settings.api_prefix)
app.include_router(health.router, prefix=settings.api_prefix)
