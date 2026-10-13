from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "sqlite:///./data/db.sqlite3"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    data_dir: str = "./data"
    frontend_origin: str = "http://localhost:3000"
    google_client_secret_path: str = "./data/secrets/google_client.json"
    google_token_path: str = "./data/secrets/google_token.json"
    oauth_redirect_uri: str = "http://localhost:8000/api/oauth/google/callback"
    notebook_total_timeout_seconds: int = 900
    notebook_penalty_power: float = 1.5

    # LLM review of project reports
    anthropic_api_key: str | None = None
    llm_review_model: str = "claude-sonnet-4-6"

    # LLM grader for peer-review rounds (scores each team's materials once)
    llm_peer_review_model: str = "claude-opus-5-5"
    llm_peer_review_effort: str = "high"

    # When set, every /api route except health, OAuth callback, and the
    # student review routes (/api/r/<token>) requires this token, sent as the
    # X-Instructor-Token header or the cg_instructor cookie. Leave unset for a
    # localhost-only deployment.
    instructor_token: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
