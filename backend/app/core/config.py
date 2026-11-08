from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://flags:flags@localhost:5432/flags"
    jwt_secret: str = "change-me"


settings = Settings()
