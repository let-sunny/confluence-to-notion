"""Unit tests for the semantic coverage analyzer."""

from pathlib import Path

import pytest

from confluence_to_notion.agents.schemas import (
    DiscoveryOutput,
    DiscoveryPattern,
    SemanticCoverage,
)
from confluence_to_notion.eval.semantic_coverage import analyze_coverage


def _write_sample(path: Path, body: str) -> None:
    """Write a Confluence XHTML snippet as a .xhtml sample file."""
    path.write_text(body, encoding="utf-8")


def _make_pattern(
    pattern_id: str,
    *,
    pattern_type: str | None = None,
    snippets: list[str] | None = None,
) -> DiscoveryPattern:
    return DiscoveryPattern(
        pattern_id=pattern_id,
        pattern_type=pattern_type or pattern_id.split(":")[0],
        description=f"Pattern {pattern_id}",
        example_snippets=snippets or [f"<ex>{pattern_id}</ex>"],
        source_pages=["p1"],
        frequency=1,
    )


def _make_patterns(*patterns: DiscoveryPattern, pages: int = 1) -> DiscoveryOutput:
    return DiscoveryOutput(
        sample_dir="samples/",
        pages_analyzed=pages,
        patterns=list(patterns),
    )


# --- Element enumeration rules (normalized keys) ---


class TestSampleEnumeration:
    """Pin down the normalization rules for sample_elements keys."""

    def test_structured_macro_becomes_macro_prefix(self, tmp_path: Path) -> None:
        _write_sample(
            tmp_path / "p1.xhtml",
            '<ac:structured-macro ac:name="info"><ac:rich-text-body><p>x</p>'
            "</ac:rich-text-body></ac:structured-macro>",
        )
        cov = analyze_coverage(tmp_path, _make_patterns())
        assert "macro:info" in cov.sample_elements

    def test_table_becomes_element_table(self, tmp_path: Path) -> None:
        _write_sample(
            tmp_path / "p1.xhtml",
            "<table><tbody><tr><td>a</td></tr></tbody></table>",
        )
        cov = analyze_coverage(tmp_path, _make_patterns())
        assert "element:table" in cov.sample_elements

    def test_all_headings_collapse_to_element_heading(self, tmp_path: Path) -> None:
        _write_sample(
            tmp_path / "p1.xhtml",
            "<h1>A</h1><h2>B</h2><h3>C</h3><h4>D</h4><h5>E</h5><h6>F</h6>",
        )
        cov = analyze_coverage(tmp_path, _make_patterns())
        assert "element:heading" in cov.sample_elements
        assert not any(
            k.startswith("element:h") and k != "element:heading" for k in cov.sample_elements
        )

    def test_lists_collapse_to_element_list(self, tmp_path: Path) -> None:
        _write_sample(
            tmp_path / "p1.xhtml",
            "<ul><li>a</li></ul><ol><li>b</li></ol>",
        )
        cov = analyze_coverage(tmp_path, _make_patterns())
        assert "element:list" in cov.sample_elements
        assert "element:ul" not in cov.sample_elements
        assert "element:ol" not in cov.sample_elements

    def test_anchor_becomes_element_link(self, tmp_path: Path) -> None:
        _write_sample(
            tmp_path / "p1.xhtml",
            '<p><a href="https://example.com">x</a></p>',
        )
        cov = analyze_coverage(tmp_path, _make_patterns())
        assert "element:link" in cov.sample_elements

    def test_code_and_pre_collapse_to_element_code(self, tmp_path: Path) -> None:
        _write_sample(
            tmp_path / "p1.xhtml",
            "<p><code>a</code></p><pre>b</pre>",
        )
        cov = analyze_coverage(tmp_path, _make_patterns())
        assert "element:code" in cov.sample_elements

    def test_ac_link_and_ac_image_captured(self, tmp_path: Path) -> None:
        _write_sample(
            tmp_path / "p1.xhtml",
            '<p><ac:link><ri:page ri:content-title="Foo"/></ac:link></p>'
            '<ac:image><ri:attachment ri:filename="a.png"/></ac:image>',
        )
        cov = analyze_coverage(tmp_path, _make_patterns())
        assert "element:ac-link" in cov.sample_elements
        assert "element:ac-image" in cov.sample_elements


# --- Coverage calculation ---


class TestAnalyzeCoverage:
    def test_pages_analyzed_counts_xhtml_files(self, tmp_path: Path) -> None:
        _write_sample(tmp_path / "p1.xhtml", "<p>one</p>")
        _write_sample(tmp_path / "p2.xhtml", "<p>two</p>")
        _write_sample(tmp_path / "p3.xhtml", "<p>three</p>")
        _write_sample(tmp_path / "notes.txt", "ignored")
        cov = analyze_coverage(tmp_path, _make_patterns())
        assert cov.pages_analyzed == 3

    def test_covered_intersection_with_patterns(self, tmp_path: Path) -> None:
        _write_sample(
            tmp_path / "p1.xhtml",
            '<ac:structured-macro ac:name="info"><ac:rich-text-body><p>x</p>'
            "</ac:rich-text-body></ac:structured-macro>"
            '<ac:structured-macro ac:name="code"><ac:plain-text-body>'
            "<![CDATA[x]]></ac:plain-text-body></ac:structured-macro>"
            "<table><tbody><tr><td>a</td></tr></tbody></table>",
        )
        patterns = _make_patterns(
            _make_pattern(
                "macro:info",
                snippets=[
                    '<ac:structured-macro ac:name="info"><ac:rich-text-body>'
                    "<p>x</p></ac:rich-text-body></ac:structured-macro>"
                ],
            ),
        )
        cov = analyze_coverage(tmp_path, patterns)
        assert set(cov.sample_elements) == {"macro:info", "macro:code", "element:table"}
        assert set(cov.covered_elements) == {"macro:info"}
        assert cov.coverage_ratio == pytest.approx(1 / 3)

    def test_full_coverage(self, tmp_path: Path) -> None:
        _write_sample(
            tmp_path / "p1.xhtml",
            '<ac:structured-macro ac:name="toc"/>',
        )
        patterns = _make_patterns(
            _make_pattern(
                "macro:toc",
                snippets=['<ac:structured-macro ac:name="toc"/>'],
            ),
        )
        cov = analyze_coverage(tmp_path, patterns)
        assert cov.coverage_ratio == 1.0
        assert set(cov.covered_elements) == {"macro:toc"}

    def test_pattern_with_no_matching_sample_keys_not_covered(self, tmp_path: Path) -> None:
        _write_sample(tmp_path / "p1.xhtml", '<ac:structured-macro ac:name="info"/>')
        patterns = _make_patterns(
            _make_pattern(
                "macro:code",
                snippets=['<ac:structured-macro ac:name="code"/>'],
            ),
        )
        cov = analyze_coverage(tmp_path, patterns)
        assert cov.sample_elements == ["macro:info"]
        assert cov.covered_elements == []
        assert cov.coverage_ratio == 0.0

    def test_empty_sample_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match=r"no \.xhtml"):
            analyze_coverage(tmp_path, _make_patterns())

    def test_empty_patterns_with_samples(self, tmp_path: Path) -> None:
        _write_sample(tmp_path / "p1.xhtml", '<ac:structured-macro ac:name="info"/>')
        cov = analyze_coverage(tmp_path, _make_patterns())
        assert cov.sample_elements == ["macro:info"]
        assert cov.covered_elements == []
        assert cov.coverage_ratio == 0.0

    def test_extra_pattern_keys_ignored(self, tmp_path: Path) -> None:
        """A pattern's snippets may reference keys not in samples; those are dropped."""
        _write_sample(tmp_path / "p1.xhtml", '<ac:structured-macro ac:name="info"/>')
        patterns = _make_patterns(
            _make_pattern(
                "macro:info",
                snippets=[
                    '<ac:structured-macro ac:name="info"/>'
                    '<ac:structured-macro ac:name="code"/>'
                ],
            ),
        )
        cov = analyze_coverage(tmp_path, patterns)
        assert set(cov.covered_elements) == {"macro:info"}
        assert set(cov.sample_elements) == {"macro:info"}
        assert cov.coverage_ratio == 1.0

    def test_output_is_semantic_coverage_instance(self, tmp_path: Path) -> None:
        _write_sample(tmp_path / "p1.xhtml", '<ac:structured-macro ac:name="info"/>')
        cov = analyze_coverage(tmp_path, _make_patterns())
        assert isinstance(cov, SemanticCoverage)

    def test_sample_and_covered_are_sorted(self, tmp_path: Path) -> None:
        _write_sample(
            tmp_path / "p1.xhtml",
            '<ac:structured-macro ac:name="toc"/>'
            '<ac:structured-macro ac:name="info"/>'
            "<table/>",
        )
        patterns = _make_patterns(
            _make_pattern(
                "macro:toc",
                snippets=['<ac:structured-macro ac:name="toc"/>'],
            ),
            _make_pattern(
                "macro:info",
                snippets=['<ac:structured-macro ac:name="info"/>'],
            ),
        )
        cov = analyze_coverage(tmp_path, patterns)
        assert cov.sample_elements == sorted(cov.sample_elements)
        assert cov.covered_elements == sorted(cov.covered_elements)
