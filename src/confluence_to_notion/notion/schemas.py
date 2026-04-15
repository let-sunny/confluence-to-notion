"""Pydantic models for Notion API data."""

from pydantic import BaseModel


class NotionPageResult(BaseModel):
    """Result of creating a Notion page."""

    page_id: str
