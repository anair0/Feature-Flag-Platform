from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me!!"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Runtime connection: a NON-superuser role, so Postgres row-level security applies.
    database_url: str = "postgresql+psycopg://flags_app:flags_app@localhost:5432/flags"
    # Migrations run as the table owner.
    migration_database_url: str = (
        "postgresql+psycopg://flags_owner:flags_owner@localhost:5432/flags"
    )

    environment: str = "development"
    jwt_secret: str = DEV_JWT_SECRET
    jwt_ttl_seconds: int = 60 * 60 * 12

    cors_origins: list[str] = ["*"]
    stream_heartbeat_seconds: float = 15.0

    # Token-bucket rate limits: (requests per second, burst)
    rate_limit_enabled: bool = True
    auth_rate: float = 0.5
    auth_burst: int = 10
    evaluate_rate: float = 50.0
    evaluate_burst: int = 200


settings = Settings()
