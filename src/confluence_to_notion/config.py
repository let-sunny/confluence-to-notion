"""Application configuration loaded from environment variables."""

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration for confluence-to-notion, loaded from .env file."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Confluence (email + token are optional for public wikis like cwiki.apache.org)
    confluence_base_url: str
    confluence_email: str | None = None
    confluence_api_token: str | None = None
    confluence_api_path: str = "/rest/api"

    # Notion
    notion_api_token: str
    notion_root_page_id: str

    # Anthropic
    anthropic_api_key: str
    anthropic_model: str = "claude-sonnet-4-5-20250929"

    @field_validator("confluence_base_url")
    @classmethod
    def _validate_confluence_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            msg = "confluence_base_url must start with http:// or https://"
            raise ValueError(msg)
        return v

    @field_validator("confluence_api_path")
    @classmethod
    def _validate_api_path(cls, v: str) -> str:
        if not v.startswith("/"):
            msg = "confluence_api_path must start with /"
            raise ValueError(msg)
        return v

    @field_validator("notion_api_token")
    @classmethod
    def _validate_notion_token(cls, v: str) -> str:
        if not v.startswith(("ntn_", "secret_")):
            msg = "notion_api_token must start with 'ntn_' or 'secret_'"
            raise ValueError(msg)
        return v

    @property
    def confluence_rest_url(self) -> str:
        """Full base URL for Confluence REST API calls."""
        return f"{self.confluence_base_url.rstrip('/')}{self.confluence_api_path}"

    @property
    def confluence_auth_available(self) -> bool:
        """Whether Confluence credentials are configured."""
        return bool(self.confluence_email and self.confluence_api_token)
