"""Pydantic models for Confluence API data."""

from datetime import datetime

from pydantic import BaseModel


class ConfluencePageSummary(BaseModel):
    """Lightweight page reference returned by list endpoints."""

    id: str
    title: str


class ConfluencePage(BaseModel):
    """Full Confluence page with XHTML storage body."""

    id: str
    title: str
    space_key: str
    storage_body: str
    version: int
    created_at: datetime
