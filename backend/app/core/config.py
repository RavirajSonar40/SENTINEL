from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://sentinel:sentinel_dev_2026@localhost:5432/sentinel"
    SECRET_KEY: str = "sentinel-dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ENVIRONMENT: str = "development"

    # LLM Settings (Phase 1)
    LLM_PROVIDER: str = "mock"
    LLM_BASE_URL: str = ""
    LLM_API_URL: str = ""  # Legacy alias for LLM_BASE_URL
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_TEMPERATURE: float = 0.3
    LLM_TIMEOUT_SECONDS: float = 60.0
    LLM_TIMEOUT: float = 60.0  # Legacy alias for LLM_TIMEOUT_SECONDS
    LLM_MAX_OUTPUT_TOKENS: int = 4000
    LLM_MAX_TOKENS: int = 4000  # Legacy alias for LLM_MAX_OUTPUT_TOKENS
    LLM_MAX_REQUEST_RETRIES: int = 2
    LLM_JSON_REPAIR_RETRIES: int = 1
    LLM_CACHE_ENABLED: bool = True
    LLM_CACHE_TTL_SECONDS: int = 300

    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""
    GITHUB_REDIRECT_URI: str = "http://localhost:8000/github/callback"

    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = ""
    REDIS_URL: str = ""
    QDRANT_URL: str = "http://localhost:6333"
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX: str = "sentinel"
    CRON_SECRET: str = ""
    GITHUB_TOKEN: str = ""

    LOG_LEVEL: str = "INFO"

    @property
    def resolved_llm_base_url(self) -> str:
        return self.LLM_BASE_URL or self.LLM_API_URL

    @property
    def resolved_llm_timeout(self) -> float:
        return self.LLM_TIMEOUT_SECONDS if self.LLM_TIMEOUT_SECONDS != 60.0 else self.LLM_TIMEOUT

    @property
    def resolved_llm_max_tokens(self) -> int:
        return self.LLM_MAX_OUTPUT_TOKENS if self.LLM_MAX_OUTPUT_TOKENS != 4000 else self.LLM_MAX_TOKENS

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
