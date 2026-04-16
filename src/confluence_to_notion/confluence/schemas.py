"""Pydantic models for Confluence API data."""

from datetime import datetime

from pydantic import BaseModel


class ConfluencePageSummary(BaseModel):
    """Lightweight page reference returned by list endpoints."""

    id: str
    title: str


class PageTreeNode(BaseModel):
    """Recursive node representing a page in the Confluence hierarchy."""

    id: str
    title: str
    children: list["PageTreeNode"] = []


PageTreeNode.model_rebuild()


class ConfluencePage(BaseModel):
    """Full Confluence page with XHTML storage body."""

    id: str
    title: str
    space_key: str
    storage_body: str
    version: int
    created_at: datetime
