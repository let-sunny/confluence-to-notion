"""Unit tests for the LLM-as-judge runner.

The runner calls the Anthropic Messages API once per (page, converted-content) pair
and caches the parsed JSON response on disk so a second run with unchanged input
incurs no API cost. Tests use a fake Anthropic-compatible client injected via
dependency injection — no real network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from confluence_to_notion.agents.schemas import LLMJudgeResult
from confluence_to_notion.eval.llm_judge import run_llm_judge, score_page


def _ok_response_json() -> str:
    return json.dumps(
        {
            "scores": {
                "information_preservation": 4,
                "notion_idiom": 5,
                "structure": 3,
                "readability": 4,
            },
            "overall_comment": "정보 보존 양호, 구조 일부 단순화됨",
        }
    )


@dataclass
class _FakeMessages:
    response_text: str
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.response_text)]
        )


@dataclass
class FakeAnthropic:
    """Minimal stand-in for ``anthropic.Anthropic``."""

    response_text: str = field(default_factory=_ok_response_json)
    messages: _FakeMessages = field(init=False)

    def __post_init__(self) -> None:
        self.messages = _FakeMessages(response_text=self.response_text)

    @property
    def call_count(self) -> int:
        return len(self.messages.calls)


# --- score_page ---


class TestScorePage:
    def test_first_call_invokes_api_and_returns_parsed_result(
        self, tmp_path: Path
    ) -> None:
        client = FakeAnthropic()
        cache_dir = tmp_path / "cache"

        result = score_page(
            page_id="27835336",
            xhtml="<p>hello</p>",
            converted_json='{"blocks": []}',
            client=client,
            cache_dir=cache_dir,
            model="claude-sonnet-4-6",
        )

        assert client.call_count == 1
        assert isinstance(result, LLMJudgeResult)
        assert result.page_id == "27835336"
        assert result.cache_hit is False
        assert result.model == "claude-sonnet-4-6"
        assert result.scores["information_preservation"] == 4
        assert result.scores["notion_idiom"] == 5
        assert "정보 보존" in result.overall_comment

    def test_second_call_with_same_input_hits_cache(self, tmp_path: Path) -> None:
        client = FakeAnthropic()
        cache_dir = tmp_path / "cache"

        first = score_page(
            page_id="p1",
            xhtml="<p>x</p>",
            converted_json='{"blocks": []}',
            client=client,
            cache_dir=cache_dir,
            model="claude-sonnet-4-6",
        )
        second = score_page(
            page_id="p1",
            xhtml="<p>x</p>",
            converted_json='{"blocks": []}',
            client=client,
            cache_dir=cache_dir,
            model="claude-sonnet-4-6",
        )

        assert client.call_count == 1
        assert first.cache_hit is False
        assert second.cache_hit is True
        assert second.scores == first.scores
        assert second.overall_comment == first.overall_comment

    def test_cache_key_changes_with_converted_content(self, tmp_path: Path) -> None:
        client = FakeAnthropic()
        cache_dir = tmp_path / "cache"

        score_page(
            page_id="p1",
            xhtml="<p>x</p>",
            converted_json='{"blocks": []}',
            client=client,
            cache_dir=cache_dir,
            model="claude-sonnet-4-6",
        )
        score_page(
            page_id="p1",
            xhtml="<p>x</p>",
            converted_json='{"blocks": [{"type": "paragraph"}]}',
            client=client,
            cache_dir=cache_dir,
            model="claude-sonnet-4-6",
        )
        assert client.call_count == 2

    def test_cache_key_invariant_to_converted_whitespace(
        self, tmp_path: Path
    ) -> None:
        """Re-formatting converted JSON should not invalidate the cache."""
        client = FakeAnthropic()
        cache_dir = tmp_path / "cache"

        score_page(
            page_id="p1",
            xhtml="<p>x</p>",
            converted_json='{"a":1,"b":2}',
            client=client,
            cache_dir=cache_dir,
            model="claude-sonnet-4-6",
        )
        score_page(
            page_id="p1",
            xhtml="<p>x</p>",
            converted_json='{\n  "b": 2,\n  "a": 1\n}',
            client=client,
            cache_dir=cache_dir,
            model="claude-sonnet-4-6",
        )
        assert client.call_count == 1

    def test_cache_files_persisted_under_configured_dir(self, tmp_path: Path) -> None:
        client = FakeAnthropic()
        cache_dir = tmp_path / "nested" / "cache"

        score_page(
            page_id="p1",
            xhtml="<p>x</p>",
            converted_json='{"blocks": []}',
            client=client,
            cache_dir=cache_dir,
            model="claude-sonnet-4-6",
        )

        assert cache_dir.is_dir()
        cached = list(cache_dir.glob("*.json"))
        assert len(cached) == 1


# --- run_llm_judge ---


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestRunLlmJudge:
    def test_iterates_over_paired_pages_only(self, tmp_path: Path) -> None:
        converted_dir = tmp_path / "converted"
        samples_dir = tmp_path / "samples"
        cache_dir = tmp_path / "cache"

        # Three converted pages, but only two have a samples-side xhtml.
        _write(converted_dir / "p1.json", '{"blocks": []}')
        _write(converted_dir / "p2.json", '{"blocks": []}')
        _write(converted_dir / "orphan.json", '{"blocks": []}')
        _write(samples_dir / "p1.xhtml", "<p>p1</p>")
        _write(samples_dir / "p2.xhtml", "<p>p2</p>")
        # samples-side orphan has no converted twin
        _write(samples_dir / "samples-orphan.xhtml", "<p>solo</p>")

        client = FakeAnthropic()
        results = run_llm_judge(
            output_dir=converted_dir,
            samples_dir=samples_dir,
            cache_dir=cache_dir,
            client=client,
            model="claude-sonnet-4-6",
        )

        page_ids = sorted(r.page_id for r in results)
        assert page_ids == ["p1", "p2"]
        assert client.call_count == 2

    def test_cache_persists_across_invocations(self, tmp_path: Path) -> None:
        converted_dir = tmp_path / "converted"
        samples_dir = tmp_path / "samples"
        cache_dir = tmp_path / "cache"

        _write(converted_dir / "p1.json", '{"blocks": []}')
        _write(samples_dir / "p1.xhtml", "<p>p1</p>")

        client = FakeAnthropic()
        first = run_llm_judge(
            output_dir=converted_dir,
            samples_dir=samples_dir,
            cache_dir=cache_dir,
            client=client,
            model="claude-sonnet-4-6",
        )
        second = run_llm_judge(
            output_dir=converted_dir,
            samples_dir=samples_dir,
            cache_dir=cache_dir,
            client=client,
            model="claude-sonnet-4-6",
        )

        assert client.call_count == 1
        assert first[0].cache_hit is False
        assert second[0].cache_hit is True

    def test_returns_empty_when_no_paired_pages(self, tmp_path: Path) -> None:
        converted_dir = tmp_path / "converted"
        samples_dir = tmp_path / "samples"
        cache_dir = tmp_path / "cache"

        _write(converted_dir / "p1.json", '{"blocks": []}')
        # no samples files
        samples_dir.mkdir()

        client = FakeAnthropic()
        results = run_llm_judge(
            output_dir=converted_dir,
            samples_dir=samples_dir,
            cache_dir=cache_dir,
            client=client,
            model="claude-sonnet-4-6",
        )

        assert results == []
        assert client.call_count == 0

    def test_invalid_json_response_raises(self, tmp_path: Path) -> None:
        converted_dir = tmp_path / "converted"
        samples_dir = tmp_path / "samples"
        cache_dir = tmp_path / "cache"

        _write(converted_dir / "p1.json", '{"blocks": []}')
        _write(samples_dir / "p1.xhtml", "<p>p1</p>")

        client = FakeAnthropic(response_text="not valid json")
        with pytest.raises(ValueError, match="judge response"):
            run_llm_judge(
                output_dir=converted_dir,
                samples_dir=samples_dir,
                cache_dir=cache_dir,
                client=client,
                model="claude-sonnet-4-6",
            )
