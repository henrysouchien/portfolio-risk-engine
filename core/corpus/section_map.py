"""Vendored from AI-excel-addin/mcp_servers/langextract_mcp/text_utils.py on 2026-04-22. Re-vendor if upstream evolves."""

from __future__ import annotations

from dataclasses import dataclass
import re


SectionMap = dict[str, tuple[str, int, int]]

_TRANSCRIPT_SECTION_MAP = {
    'PREPARED REMARKS': 'Prepared Remarks',
    'Q&A SESSION': 'Q&A Session',
}

_EDGAR_CORPUS_HEADER_TO_ID = {
    '10-K': {
        'Item 1. Business': 'item_1',
        'Item 1A. Risk Factors': 'item_1a',
        'Item 1B. Unresolved Staff Comments': 'item_1b',
        'Item 2. Properties': 'item_2',
        'Item 3. Legal Proceedings': 'item_3',
        "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations": 'item_7',
        'Item 7A. Quantitative and Qualitative Disclosures About Market Risk': 'item_7a',
        'Item 8. Financial Statements': 'item_8',
        'Item 8. Notes to Financial Statements': 'item_8_notes',
    },
    '10-Q': {
        'Part I, Item 1. Financial Statements': 'part1_item1',
        'Part I, Item 1. Notes to Financial Statements': 'part1_item1_notes',
        "Part I, Item 2. Management's Discussion and Analysis of Financial Condition and Results of Operations": 'part1_item2',
        'Part I, Item 3. Quantitative and Qualitative Disclosures About Market Risk': 'part1_item3',
        'Part I, Item 4. Controls and Procedures': 'part1_item4',
        'Part II, Item 1. Legal Proceedings': 'part2_item1',
        'Part II, Item 1A. Risk Factors': 'part2_item1a',
    },
    '8-K': {
        'Earnings Press Release': 'earnings_release',
    },
}


@dataclass(frozen=True)
class SectionRow:
    section: str
    content: str
    char_start: int
    char_end: int
    speaker_name: str | None
    speaker_role: str | None


def _parse_filing_sections_raw(text: str) -> SectionMap:
    """Split a filing markdown blob into sections while preserving file offsets."""
    matches = list(re.finditer(r"^## SECTION: (?P<header>.+)$", text, flags=re.MULTILINE))
    if not matches:
        raise ValueError("No `## SECTION:` headers were found in the filing text.")

    sections: SectionMap = {}
    for index, match in enumerate(matches):
        start_offset = match.start()
        end_offset = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group("header").strip()] = (
            text[start_offset:end_offset],
            start_offset,
            end_offset,
        )
    return sections


def _parse_transcript_sections_raw(text: str) -> list[SectionRow]:
    # Vendored from AI-excel-addin/api/research/document_service.py on 2026-04-22.
    header_pattern = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
    speaker_pattern = re.compile(r"^SPEAKER:\s*(.+?)(?:\s+\((.+?)\))?$")

    headers = list(header_pattern.finditer(text))
    current_section: str | None = None
    segments: list[SectionRow] = []

    for index, header in enumerate(headers):
        level = len(header.group(1))
        title = header.group(2).strip()

        if level == 2:
            current_section = _TRANSCRIPT_SECTION_MAP.get(title.upper())
            continue

        if level != 3 or current_section is None:
            continue

        speaker_match = speaker_pattern.match(title)
        if speaker_match is None:
            continue

        text_start = header.end()
        if text_start < len(text) and text[text_start] == "\n":
            text_start += 1

        next_header_start = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        text_end = next_header_start
        while text_end > text_start and text[text_end - 1] == "\n":
            text_end -= 1
        while text_start < text_end and text[text_start] == "\n":
            text_start += 1

        segment_text = text[text_start:text_end]
        if not segment_text.strip():
            continue

        role = str(speaker_match.group(2) or "").strip() or None
        segments.append(
            SectionRow(
                section=current_section,
                content=segment_text,
                char_start=text_start,
                char_end=text_end,
                speaker_name=speaker_match.group(1).strip(),
                speaker_role=role,
            )
        )

    return segments


def parse_sections(text: str, source: str) -> list[SectionRow]:
    """Dispatch parser based on source value from frontmatter."""
    if source == 'edgar':
        raw = _parse_filing_sections_raw(text)
        return [
            SectionRow(
                section=header,
                content=content,
                char_start=start,
                char_end=end,
                speaker_name=None,
                speaker_role=None,
            )
            for header, (content, start, end) in raw.items()
        ]
    if source == 'fmp_transcripts':
        return _parse_transcript_sections_raw(text)
    raise ValueError(f"Unknown source: {source!r}")


def corpus_header_to_edgar_id(header: str, form_type: str) -> str | None:
    """Map a corpus filing header back to Edgar_updater's canonical section id."""
    base_form_type = form_type[:-2] if form_type.endswith('/A') else form_type
    return _EDGAR_CORPUS_HEADER_TO_ID.get(base_form_type, {}).get(header)
