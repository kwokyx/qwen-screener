from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    app_name: str = "QwenStockScreener"
    debug: bool = True
    api_prefix: str = "/api/v1"

    database_url: str = "sqlite:///./stock.db"
    redis_url: str | None = None

    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 1440
    algorithm: str = "HS256"

    # 数据源后端：baostock (默认) / akshare (legacy)
    data_provider: str = "baostock"

    # 大模型后端：openai (默认) / dashscope
    ai_backend: str = "openai"

    # OpenAI 兼容（支持自建/中转：base_url 可换）
    openai_api_key: str = ""
    openai_base_url: str = "https://api2.up.railway.app"
    openai_model: str = "gpt-5.4-mini"
    openai_reasoning: str = "high"
    openai_responses_enabled: bool = False
    agent_plan_timeout_seconds: float = 10.0
    agent_react_step_timeout_seconds: float = 18.0

    # 阿里云百炼 dashscope（备用）
    dashscope_api_key: str = ""
    qwen_model: str = "qwen-plus"

    cors_origins: str = "http://localhost:5173"

    # 飞书通知（webhook 或企业自建应用二选一，都不填则不推送）
    feishu_webhook_url: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_chat_id: str = ""
    feishu_open_id: str = ""
    feishu_email: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
