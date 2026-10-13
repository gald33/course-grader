from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "sqlite:///./data/db.sqlite3"
    # No connection pooling in the app (use with Supabase's transaction
    # pooler from serverless hosts, where the pooler does the pooling).
    database_null_pool: bool = False
    # Background job worker (python -m app.tasks.worker)
    worker_poll_seconds: float = 2.0
    job_stale_minutes: int = 60
    data_dir: str = "./data"
    # Where new artifact files go: "local" (DATA_DIR) or "supabase" (Storage).
    storage_backend: str = "local"
    supabase_project_url: str | None = None
    supabase_secret_key: str | None = None
    supabase_storage_bucket: str = "course-grader"
    # Public address of the frontend; account emails link back to it.
    public_app_url: str = "http://localhost:3000"
    # Signs student login cookies. Defaults to a key derived from
    # SUPABASE_SECRET_KEY, so it's stable across serverless instances.
    session_secret: str | None = None
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


def sqlalchemy_database_url(url: str) -> str:
    """Route plain Postgres URLs (as Supabase gives them) to the psycopg 3 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url
