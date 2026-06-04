from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_path: Path = Path("data/observatory.db")
    gitlab_token: str = ""
    github_token: str = ""
    api_key: str = ""
    credential_key: str = ""
    collector_interval_minutes: int = 30
    static_dir: Path = Path("src/frontend/dist")
    ssl_verify: bool = True
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_prefix": "OBSERVATORY_"}


settings = Settings()
