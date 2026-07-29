from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_path: Path = Path("data/observatory.db")
    gitlab_token: str = ""
    gitlab_token_internal: str = ""
    github_token: str = ""
    api_key: str = ""
    credential_key: str = ""
    # Jira Cloud credentials. Read from .env (loaded by honcho for `make dev`).
    # Accept both the OBSERVATORY_-prefixed names and the bare JIRA_* names the
    # Atlassian tooling conventionally uses; a validation_alias overrides the
    # class-wide OBSERVATORY_ env_prefix for these fields only.
    jira_url: str = Field(
        "", validation_alias=AliasChoices("OBSERVATORY_JIRA_URL", "JIRA_URL")
    )
    jira_email: str = Field(
        "", validation_alias=AliasChoices("OBSERVATORY_JIRA_EMAIL", "JIRA_EMAIL")
    )
    jira_token: str = Field(
        "",
        validation_alias=AliasChoices(
            "OBSERVATORY_JIRA_API_TOKEN", "JIRA_API_TOKEN"
        ),
    )
    collector_interval_minutes: int = 1440
    static_dir: Path = Path("src/frontend/dist")
    ssl_verify: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    anthropic_api_key: str = ""
    anthropic_vertex_project_id: str = ""
    cloud_ml_region: str = "global"
    chat_model: str = "claude-sonnet-4-20250514"
    # /checkouts is a browse root ONLY because the .git/secrets denylist in
    # chat/tools.py (_is_denied_path, layered on _validate_path) prevents the
    # chat agent from reading .git/config tokens or secret files there. Never
    # add /checkouts here without that denylist. See ADR-0028.
    chat_browse_roots: str = "/app/.context,/app/artifacts,/checkouts"
    checkout_root: Path = Path("/checkouts")
    repo_sync_interval_minutes: int = 60
    repo_sync_depth: int = 1
    repo_sync_on_startup: bool = True

    model_config = {"env_prefix": "OBSERVATORY_"}


settings = Settings()
