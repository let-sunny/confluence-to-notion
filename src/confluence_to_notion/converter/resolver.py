"""Resolver — processes unresolved items using pluggable strategies.

The resolver deduplicates items, checks the resolution store first,
then tries each strategy in order until one succeeds. Newly resolved
entries are saved to the store automatically.
"""

import logging
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from confluence_to_notion.converter.resolution import ResolutionStore
from confluence_to_notion.converter.schemas import ResolutionEntry, UnresolvedItem

logger = logging.getLogger(__name__)


@runtime_checkable
class ResolveStrategy(Protocol):
    """Protocol for resolution strategies (AI, API, user input, etc.)."""

    async def try_resolve(self, item: UnresolvedItem) -> ResolutionEntry | None: ...


class ResolveReport(BaseModel):
    """Result of a resolve pass."""

    resolved_count: int = Field(default=0)
    from_store: int = Field(default=0)
    newly_resolved: int = Field(default=0)
    still_unresolved: list[UnresolvedItem] = Field(default_factory=list)


class Resolver:
    """Resolves unresolved items using store lookup + pluggable strategies.

    Usage:
        store = ResolutionStore(Path("output/resolution.json"))
        resolver = Resolver(store, strategies=[ai_strategy, user_strategy])
        report = await resolver.resolve(result.unresolved)
    """

    def __init__(
        self,
        store: ResolutionStore,
        strategies: list[ResolveStrategy] | None = None,
    ) -> None:
        self._store = store
        self._strategies = strategies or []

    async def resolve(self, items: list[UnresolvedItem]) -> ResolveReport:
        """Process unresolved items: deduplicate, check store, try strategies."""
        report = ResolveReport()
        seen: set[str] = set()

        for item in items:
            key = f"{item.kind}:{item.identifier}"
            if key in seen:
                continue
            seen.add(key)

            # 1. Check store
            existing = self._store.lookup(key)
            if existing is not None:
                report.resolved_count += 1
                report.from_store += 1
                logger.debug("Store hit: %s", key)
                continue

            # 2. Try strategies in order
            entry = await self._try_strategies(item)
            if entry is not None:
                self._store.add(
                    key=key,
                    resolved_by=entry.resolved_by,
                    value=entry.value,
                    confidence=entry.confidence,
                )
                report.resolved_count += 1
                report.newly_resolved += 1
                logger.info("Resolved: %s via %s", key, entry.resolved_by)
            else:
                report.still_unresolved.append(item)
                logger.info("Unresolved: %s", key)

        # Persist newly resolved entries
        if report.newly_resolved > 0:
            self._store.save()

        return report

    async def _try_strategies(self, item: UnresolvedItem) -> ResolutionEntry | None:
        for strategy in self._strategies:
            entry = await strategy.try_resolve(item)
            if entry is not None:
                return entry
        return None
