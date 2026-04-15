"""Application configuration loaded from environment variables."""

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration for confluence-to-notion, loaded from .env file.

    Fields are optional so that each CLI command only requires what it needs:
    - `fetch` needs only confluence_base_url
    - `notion-ping` needs notion_api_token
    - Agent pipeline runs via `claude -p` (no API key needed)
    """

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Confluence (email + token optional for public wikis like cwiki.apache.org)
    confluence_base_url: str = "https://cwiki.apache.org/confluence"
    confluence_email: str | None = None
    confluence_api_token: str | None = None
    confluence_api_path: str = "/rest/api"

    # Notion (optional — only needed for notion-ping, migrate)
    notion_api_token: str | None = None
    notion_root_page_id: str | None = None

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
    def _validate_notion_token(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("ntn_", "secret_")):
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

    def require_notion(self) -> None:
        """Raise if Notion credentials are missing."""
        if not self.notion_api_token:
            msg = "NOTION_API_TOKEN is required. Set it in .env"
            raise ValueError(msg)
        if not self.notion_root_page_id:
            msg = "NOTION_ROOT_PAGE_ID is required. Set it in .env"
            raise ValueError(msg)
