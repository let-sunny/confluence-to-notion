"""Unit tests for the Resolver — store lookup, dedup, strategy dispatch."""

from pathlib import Path

from confluence_to_notion.converter.resolution import ResolutionStore
from confluence_to_notion.converter.resolver import Resolver
from confluence_to_notion.converter.schemas import (
    ResolutionEntry,
    UnresolvedItem,
)


def _macro(name: str, page: str = "pg-1") -> UnresolvedItem:
    return UnresolvedItem(kind="macro", identifier=name, source_page_id=page)


def _page_link(title: str, page: str = "pg-1") -> UnresolvedItem:
    return UnresolvedItem(kind="page_link", identifier=title, source_page_id=page)


class FakeStrategy:
    """Strategy that resolves specific identifiers."""

    def __init__(self, known: dict[str, dict]) -> None:
        self._known = known
        self.call_count = 0

    async def try_resolve(self, item: UnresolvedItem) -> ResolutionEntry | None:
        self.call_count += 1
        value = self._known.get(item.identifier)
        if value is None:
            return None
        return ResolutionEntry(resolved_by="ai_inference", value=value, confidence=0.9)


class FailStrategy:
    """Strategy that never resolves anything."""

    async def try_resolve(self, item: UnresolvedItem) -> ResolutionEntry | None:
        return None


class TestResolverStoreLookup:
    """Items already in the store are reused without calling strategies."""

    async def test_store_hit_skips_strategy(self, tmp_path: Path) -> None:
        store = ResolutionStore(tmp_path / "res.json")
        store.add(
            key="macro:known-macro",
            resolved_by="user_input",
            value={"notion_block_type": "callout"},
        )
        strategy = FakeStrategy({})
        resolver = Resolver(store, strategies=[strategy])

        report = await resolver.resolve([_macro("known-macro")])

        assert report.resolved_count == 1
        assert report.from_store == 1
        assert report.newly_resolved == 0
        assert report.still_unresolved == []
        assert strategy.call_count == 0

    async def test_store_miss_calls_strategy(self, tmp_path: Path) -> None:
        store = ResolutionStore(tmp_path / "res.json")
        strategy = FakeStrategy({"new-macro": {"notion_block_type": "table"}})
        resolver = Resolver(store, strategies=[strategy])

        report = await resolver.resolve([_macro("new-macro")])

        assert report.resolved_count == 1
        assert report.from_store == 0
        assert report.newly_resolved == 1
        assert strategy.call_count == 1
        # Should be saved to store
        assert store.lookup("macro:new-macro") is not None


class TestDeduplication:
    """Same identifier appearing multiple times is resolved only once."""

    async def test_duplicate_items_resolved_once(self, tmp_path: Path) -> None:
        store = ResolutionStore(tmp_path / "res.json")
        strategy = FakeStrategy({"dup-macro": {"type": "callout"}})
        resolver = Resolver(store, strategies=[strategy])

        items = [_macro("dup-macro", "pg-1"), _macro("dup-macro", "pg-2")]
        report = await resolver.resolve(items)

        assert report.resolved_count == 1
        assert strategy.call_count == 1

    async def test_different_kinds_same_identifier_not_deduped(self, tmp_path: Path) -> None:
        """macro:foo and page_link:foo are different keys."""
        store = ResolutionStore(tmp_path / "res.json")
        strategy = FakeStrategy({"foo": {"value": "resolved"}})
        resolver = Resolver(store, strategies=[strategy])

        items = [_macro("foo"), _page_link("foo")]
        report = await resolver.resolve(items)

        assert report.resolved_count == 2
        assert strategy.call_count == 2


class TestStrategyChain:
    """Strategies are tried in order; first success wins."""

    async def test_first_strategy_wins(self, tmp_path: Path) -> None:
        store = ResolutionStore(tmp_path / "res.json")
        s1 = FakeStrategy({"x": {"from": "s1"}})
        s2 = FakeStrategy({"x": {"from": "s2"}})
        resolver = Resolver(store, strategies=[s1, s2])

        report = await resolver.resolve([_macro("x")])

        assert report.newly_resolved == 1
        entry = store.lookup("macro:x")
        assert entry is not None
        assert entry.value == {"from": "s1"}
        assert s1.call_count == 1
        assert s2.call_count == 0

    async def test_fallthrough_to_second(self, tmp_path: Path) -> None:
        store = ResolutionStore(tmp_path / "res.json")
        s1 = FailStrategy()
        s2 = FakeStrategy({"y": {"from": "s2"}})
        resolver = Resolver(store, strategies=[s1, s2])

        report = await resolver.resolve([_macro("y")])

        assert report.newly_resolved == 1
        assert store.lookup("macro:y") is not None

    async def test_all_fail_stays_unresolved(self, tmp_path: Path) -> None:
        store = ResolutionStore(tmp_path / "res.json")
        resolver = Resolver(store, strategies=[FailStrategy()])

        report = await resolver.resolve([_macro("mystery")])

        assert report.resolved_count == 0
        assert report.still_unresolved == [_macro("mystery")]


class TestResolveReport:
    """Report accurately counts resolved/unresolved/store/new."""

    async def test_mixed_report(self, tmp_path: Path) -> None:
        store = ResolutionStore(tmp_path / "res.json")
        store.add(key="macro:cached", resolved_by="user_input", value={"cached": True})

        strategy = FakeStrategy({"resolvable": {"new": True}})
        resolver = Resolver(store, strategies=[strategy])

        items = [_macro("cached"), _macro("resolvable"), _macro("impossible")]
        report = await resolver.resolve(items)

        assert report.resolved_count == 2
        assert report.from_store == 1
        assert report.newly_resolved == 1
        assert len(report.still_unresolved) == 1
        assert report.still_unresolved[0].identifier == "impossible"

    async def test_empty_input(self, tmp_path: Path) -> None:
        store = ResolutionStore(tmp_path / "res.json")
        resolver = Resolver(store, strategies=[])

        report = await resolver.resolve([])

        assert report.resolved_count == 0
        assert report.still_unresolved == []


class TestStorePersistence:
    """Newly resolved items are persisted via store.save()."""

    async def test_auto_save(self, tmp_path: Path) -> None:
        path = tmp_path / "res.json"
        store = ResolutionStore(path)
        strategy = FakeStrategy({"widget": {"type": "database"}})
        resolver = Resolver(store, strategies=[strategy])

        await resolver.resolve([_macro("widget")])

        # Reload from disk
        store2 = ResolutionStore(path)
        assert store2.lookup("macro:widget") is not None
