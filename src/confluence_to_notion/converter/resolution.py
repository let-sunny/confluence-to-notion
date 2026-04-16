"""Resolution store — persists resolved facts across conversion runs."""

import logging
from pathlib import Path
from typing import Any

from confluence_to_notion.converter.schemas import ResolutionData, ResolutionEntry

logger = logging.getLogger(__name__)


class ResolutionStore:
    """Load, query, and persist resolution entries.

    Usage:
        store = ResolutionStore(Path("output/resolution.json"))
        entry = store.lookup("jira_server:ASF JIRA")
        if entry is None:
            store.add("jira_server:ASF JIRA", resolved_by="user_input",
                       value={"url": "https://issues.apache.org/jira"})
            store.save()
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self.data = self._load()

    def _load(self) -> ResolutionData:
        if not self._path.exists():
            return ResolutionData()
        try:
            return ResolutionData.model_validate_json(self._path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            logger.warning("Failed to load %s, starting fresh", self._path)
            return ResolutionData()

    def lookup(self, key: str) -> ResolutionEntry | None:
        """Look up a resolution entry by key (e.g. 'macro:toc')."""
        return self.data.entries.get(key)

    def add(
        self,
        key: str,
        *,
        resolved_by: str,
        value: dict[str, Any],
        confidence: float | None = None,
    ) -> None:
        """Add or overwrite a resolution entry."""
        self.data.entries[key] = ResolutionEntry(
            resolved_by=resolved_by,
            value=value,
            confidence=confidence,
        )

    def keys(self) -> list[str]:
        """Return all resolution keys."""
        return list(self.data.entries.keys())

    def save(self) -> None:
        """Persist the store to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            self.data.model_dump_json(indent=2),
            encoding="utf-8",
        )
