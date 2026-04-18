"""LLM-as-judge runner that scores Confluence → Notion conversions.

Each (page_id, converted-content) pair is sent to the Anthropic Messages API
once and scored across four dimensions:

- ``information_preservation`` — 원문 정보가 빠짐없이 전달되었는가
- ``notion_idiom`` — Notion 관용 표현(callout, toggle, code 등)을 적절히 활용했는가
- ``structure`` — 헤딩/목록/표 구조가 적절히 보존되었는가
- ``readability`` — 결과 페이지의 가독성

Results are signal-only per ADR-004 — they never flip ``EvalReport.overall_pass``.

Calls are cached on disk under ``cache_dir`` keyed by
``sha256(page_id + canonical(converted_json))`` so a re-run with unchanged
converter output makes no API call.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol, cast

from rich.console import Console

from confluence_to_notion.agents.schemas import LLMJudgeResult
from confluence_to_notion.config import Settings

_console = Console()

DEFAULT_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = (
    "당신은 Confluence → Notion 변환 결과를 평가하는 한국어 reviewer 입니다. "
    "원본 XHTML 과 변환된 Notion 블록 JSON 을 보고 4가지 차원을 1~5 정수로 채점하세요. "
    "출력은 반드시 다음 JSON 스키마만 포함해야 합니다 (마크다운 코드펜스/주석 금지):\n"
    '{"scores": {"information_preservation": int, "notion_idiom": int,'
    ' "structure": int, "readability": int}, "overall_comment": "string"}\n'
    "차원 정의:\n"
    "- information_preservation: 원문의 정보(텍스트, 매크로 의미)가 빠짐없이 전달되었는가\n"
    "- notion_idiom: callout/toggle/code 등 Notion 관용 표현을 적절히 활용했는가\n"
    "- structure: 헤딩/목록/표 등 문서 구조가 적절히 보존되었는가\n"
    "- readability: 결과 페이지의 가독성"
)


class _MessagesClient(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _AnthropicClient(Protocol):
    """Structural type matching the slice of ``anthropic.Anthropic`` we use."""

    @property
    def messages(self) -> _MessagesClient: ...


def _canonical_json(raw: str) -> str:
    """Return ``raw`` re-serialized with sorted keys and no whitespace.

    Falls back to ``raw`` unchanged if it isn't valid JSON, so the cache still
    keys deterministically on the original bytes.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _cache_key(page_id: str, converted_json: str) -> str:
    payload = f"{page_id}|{_canonical_json(converted_json)}".encode()
    return hashlib.sha256(payload).hexdigest()


def _extract_text(response: Any) -> str:
    blocks = getattr(response, "content", None)
    if not blocks:
        raise ValueError("judge response has no content blocks")
    for block in blocks:
        text = getattr(block, "text", None)
        if text:
            return str(text)
    raise ValueError("judge response has no text block")


def _build_user_prompt(page_id: str, xhtml: str, converted_json: str) -> str:
    return (
        f"page_id: {page_id}\n\n"
        "=== 원본 Confluence XHTML ===\n"
        f"{xhtml}\n\n"
        "=== 변환된 Notion 블록 JSON ===\n"
        f"{converted_json}\n\n"
        "위 두 콘텐츠를 비교해 4가지 차원을 채점하고 JSON 으로 응답하세요."
    )


def _parse_response(text: str) -> tuple[dict[str, int], str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"judge response is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"judge response must be a JSON object, got {type(data).__name__}")
    scores = data.get("scores")
    comment = data.get("overall_comment", "")
    if not isinstance(scores, dict):
        raise ValueError("judge response missing 'scores' object")
    return {str(k): int(v) for k, v in scores.items()}, str(comment)


def score_page(
    page_id: str,
    xhtml: str,
    converted_json: str,
    *,
    client: _AnthropicClient,
    cache_dir: Path,
    model: str = DEFAULT_MODEL,
) -> LLMJudgeResult:
    """Score a single page, hitting the Anthropic API only on cache miss."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{_cache_key(page_id, converted_json)}.json"

    if cache_file.exists():
        cached = LLMJudgeResult.model_validate_json(cache_file.read_text(encoding="utf-8"))
        _console.log(f"[dim]llm-judge cache hit: {page_id}[/dim]")
        return cached.model_copy(update={"cache_hit": True})

    _console.log(f"[cyan]llm-judge cache miss: {page_id} → calling {model}[/cyan]")
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(page_id, xhtml, converted_json)}],
    )
    scores, comment = _parse_response(_extract_text(response))

    result = LLMJudgeResult(
        page_id=page_id,
        scores=scores,
        overall_comment=comment,
        model=model,
        cache_hit=False,
    )
    cache_file.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result


def _resolve_pairs(output_dir: Path, samples_dir: Path) -> list[tuple[str, Path, Path]]:
    """Return (page_id, xhtml_path, converted_path) triples that exist on both sides."""
    converted = {p.stem: p for p in output_dir.glob("*.json")} if output_dir.is_dir() else {}
    xhtml = {p.stem: p for p in samples_dir.glob("*.xhtml")} if samples_dir.is_dir() else {}
    paired_ids = sorted(converted.keys() & xhtml.keys())
    return [(pid, xhtml[pid], converted[pid]) for pid in paired_ids]


def _default_client() -> _AnthropicClient:
    from anthropic import Anthropic

    settings = Settings()
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set; required for --llm-judge. Set it in .env"
        )
    return cast(_AnthropicClient, Anthropic(api_key=settings.anthropic_api_key))


def run_llm_judge(
    output_dir: Path,
    samples_dir: Path,
    cache_dir: Path,
    *,
    client: _AnthropicClient | None = None,
    model: str = DEFAULT_MODEL,
) -> list[LLMJudgeResult]:
    """Score every page that has both a converted JSON and a sample XHTML.

    Pages missing from either side are skipped silently (the eval pipeline
    handles missing-pair reporting separately).
    """
    pairs = _resolve_pairs(output_dir, samples_dir)
    if not pairs:
        _console.log("[yellow]llm-judge: no paired pages found, skipping[/yellow]")
        return []

    judge_client = client if client is not None else _default_client()

    results: list[LLMJudgeResult] = []
    for page_id, xhtml_path, converted_path in pairs:
        results.append(
            score_page(
                page_id=page_id,
                xhtml=xhtml_path.read_text(encoding="utf-8"),
                converted_json=converted_path.read_text(encoding="utf-8"),
                client=judge_client,
                cache_dir=cache_dir,
                model=model,
            )
        )
    return results
