from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


# ─── Core ──────────────────────────────────────────────────────────────

class Run(BaseModel):
    text: str
    font_name: str | None
    font_size_pt: float | None
    bold: bool | None
    italic: bool | None


class Paragraph(BaseModel):
    index: int
    text: str
    style_name: str | None
    runs: list[Run]
    alignment: str | None
    indent_left_cm: float | None
    indent_first_line_cm: float | None
    line_spacing: float | None
    is_in_table: bool


class Section(BaseModel):
    title: str
    level: int
    paragraph_index: int
    detection_method: Literal["style", "heuristic"]


# ─── Citation / Reference ──────────────────────────────────────────────

class Citation(BaseModel):
    raw_text: str
    authors: list[str]
    year: str
    year_suffix: str | None
    has_et_al: bool
    citation_type: Literal["parenthetical", "narrative"]
    paragraph_index: int


class Reference(BaseModel):
    index: int
    raw_text: str
    first_author_surname: str | None
    year: str | None
    year_suffix: str | None
    parse_confidence: float
    paragraph_index: int
    doi: str | None = None
    urls: list[str] = []
    author_count: int | None = None


# ─── Figures / Tables ──────────────────────────────────────────────────

class Figure(BaseModel):
    index: int
    figure_number: int | None
    caption_text: str | None
    paragraph_index: int
    caption_position: str | None = None


class Table(BaseModel):
    index: int
    table_number: int | None
    caption_text: str | None
    paragraph_index: int
    caption_position: str | None = None
    has_vertical_borders: bool | None = None


# ─── Document container ────────────────────────────────────────────────

class DocumentMetadata(BaseModel):
    paper_size: str | None
    paper_width_cm: float
    paper_height_cm: float
    margin_top_cm: float
    margin_bottom_cm: float
    margin_left_cm: float
    margin_right_cm: float
    default_line_spacing: float | None
    has_page_numbers: bool | None = None


class ParsedDocument(BaseModel):
    metadata: DocumentMetadata
    paragraphs: list[Paragraph]
    sections: list[Section]
    citations: list[Citation]
    references: list[Reference]
    figures: list[Figure]
    tables: list[Table]


# ─── API response ─────────────────────────────────────────────────────

class Locator(BaseModel):
    kind: Literal["document", "paragraph"]
    paragraph_index: int | None = None
    char_start: int | None = None
    char_end: int | None = None


class CheckDetail(BaseModel):
    location: str
    locator: Locator | None = None
    message: str
    expected: Any | None = None
    actual: Any | None = None
    excerpt: str | None = None


class CheckResult(BaseModel):
    rule_id: str
    category: str
    name: str
    status: Literal["pass", "fail"]
    severity: Literal["error", "warning", "info"]
    details: list[CheckDetail]


class ReportSummary(BaseModel):
    total_checks: int
    passed: int
    errors: int
    warnings: int
    info: int


class CheckReport(BaseModel):
    file_name: str
    timestamp: datetime
    summary: ReportSummary
    results: list[CheckResult]
