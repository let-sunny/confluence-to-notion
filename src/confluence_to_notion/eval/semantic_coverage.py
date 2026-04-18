"""Semantic coverage metric: what fraction of macro/element kinds seen in
samples is documented by at least one discovery pattern.

The enumeration is intentionally coarse — we collapse heading levels and list
kinds together so a pattern that mentions `<h2>` counts as covering all
headings.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from confluence_to_notion.agents.schemas import DiscoveryOutput, SemanticCoverage

_AC_NS = "http://www.atlassian.com/schema/confluence/4/ac/"
_RI_NS = "http://www.atlassian.com/schema/confluence/4/ri/"

_XHTML_WRAPPER = (
    '<root xmlns:ac="{ac}" xmlns:ri="{ri}">{body}</root>'
)

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_LIST_TAGS = {"ul", "ol"}
_CODE_TAGS = {"code", "pre"}


def _wrap(xhtml: str) -> str:
    return _XHTML_WRAPPER.format(ac=_AC_NS, ri=_RI_NS, body=xhtml)


def _strip_ns(tag: str) -> tuple[str | None, str]:
    """Split a Clark-notation tag into (namespace, local_name)."""
    if tag.startswith("{"):
        end = tag.index("}")
        return tag[1:end], tag[end + 1 :]
    return None, tag


def _collect_keys(xhtml: str) -> set[str]:
    """Walk XHTML and return the set of normalized element keys it contains.

    Malformed fragments are skipped with an empty set so one bad page does not
    kill the whole metric.
    """
    try:
        root = ET.fromstring(_wrap(xhtml))
    except ET.ParseError:
        return set()

    keys: set[str] = set()
    for elem in root.iter():
        ns, local = _strip_ns(elem.tag)
        if ns == _AC_NS:
            if local == "structured-macro":
                name = elem.get(f"{{{_AC_NS}}}name")
                if name:
                    keys.add(f"macro:{name}")
            elif local == "link":
                keys.add("element:ac-link")
            elif local == "image":
                keys.add("element:ac-image")
        elif ns is None:
            if local in _HEADING_TAGS:
                keys.add("element:heading")
            elif local in _LIST_TAGS:
                keys.add("element:list")
            elif local in _CODE_TAGS:
                keys.add("element:code")
            elif local == "table":
                keys.add("element:table")
            elif local == "a":
                keys.add("element:link")
    return keys


def _pattern_keys(patterns: DiscoveryOutput) -> set[str]:
    """Union of normalized element keys found across every pattern's snippets."""
    covered: set[str] = set()
    for pattern in patterns.patterns:
        for snippet in pattern.example_snippets:
            covered |= _collect_keys(snippet)
    return covered


def analyze_coverage(samples_dir: Path, patterns: DiscoveryOutput) -> SemanticCoverage:
    """Enumerate element kinds in samples_dir and report the fraction covered by patterns.

    Args:
        samples_dir: Directory containing `*.xhtml` Confluence storage-body files.
        patterns: DiscoveryOutput whose `example_snippets` are scanned for the
            same normalized keys.

    Returns:
        SemanticCoverage with sample_elements, covered_elements, and ratio.

    Raises:
        ValueError: if samples_dir contains no `.xhtml` files.
    """
    sample_files = sorted(samples_dir.glob("*.xhtml"))
    if not sample_files:
        raise ValueError(f"no .xhtml files found in {samples_dir}")

    sample_keys: set[str] = set()
    for path in sample_files:
        sample_keys |= _collect_keys(path.read_text(encoding="utf-8"))

    pattern_keys = _pattern_keys(patterns)
    covered = sample_keys & pattern_keys

    ratio = len(covered) / len(sample_keys) if sample_keys else 1.0

    return SemanticCoverage(
        pages_analyzed=len(sample_files),
        sample_elements=sorted(sample_keys),
        covered_elements=sorted(covered),
        coverage_ratio=ratio,
    )
