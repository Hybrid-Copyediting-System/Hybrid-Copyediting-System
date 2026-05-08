"""ET&S (Educational Technology & Society) APA 7th hardcoded profile."""

# ─── Layout ────────────────────────────────────────────────────────────
PAPER_SIZE = "A4"
PAPER_WIDTH_CM = 21.0
PAPER_HEIGHT_CM = 29.7

MARGIN_TOP_CM = 2.5
MARGIN_BOTTOM_CM = 2.5
MARGIN_LEFT_CM = 2.5
MARGIN_RIGHT_CM = 2.5
MARGIN_TOLERANCE_CM = 0.05

LINE_SPACING = 1.0
LINE_SPACING_TOLERANCE = 0.05

# Body paragraph first-line indent (APA 7 §2.24: 0.5 inch ≈ 1.27 cm).
# ET&S follows this convention.
BODY_FIRST_LINE_INDENT_CM = 1.27
BODY_INDENT_TOLERANCE_CM = 0.15

# ET&S body alignment. The journal template uses justify; APA 7 default is
# "left" but ET&S reflows to justified at typesetting time, so the manuscript
# is checked against either. Keep both acceptable to avoid false positives.
BODY_ALLOWED_ALIGNMENTS = {"justify", "left", "JUSTIFY", "LEFT", None}

# ─── Fonts ─────────────────────────────────────────────────────────────
FONT_TITLE = ("Times New Roman", 14.0, True, False)
FONT_BODY = ("Times New Roman", 10.0, False, False)
FONT_ABSTRACT = ("Times New Roman", 10.0, False, True)
FONT_HEADING_1 = ("Times New Roman", 12.0, True, False)
FONT_HEADING_2 = ("Times New Roman", 10.0, True, False)
FONT_HEADING_3 = ("Times New Roman", 10.0, True, True)
FONT_REFERENCE = ("Times New Roman", 9.0, False, False)

# ─── Structure ─────────────────────────────────────────────────────────
ABSTRACT_MAX_WORDS = 250
KEYWORDS_MAX_COUNT = 5
REQUIRED_SECTIONS = ["Abstract", "Introduction", "References"]

# Paper title length cap (APA 7 §2.4 recommends ≤ 12 words). Treated as a
# soft warning — many legitimate titles run a little longer.
TITLE_MAX_WORDS = 12

# ─── Citation / Reference ──────────────────────────────────────────────
ET_AL_THRESHOLD = 3
REFERENCE_LIST_TITLES = ["References", "Reference List", "參考文獻", "參考書目"]
REFERENCE_HANGING_INDENT_CM = 1.27
REFERENCE_INDENT_TOLERANCE_CM = 0.15

# APA 7 §9.8 author list rules:
#   ≤ AUTHOR_LIST_FULL_THRESHOLD authors → list every author
#   ≥ AUTHOR_LIST_ELLIPSIS_THRESHOLD authors → first 19 + "..." + final author
AUTHOR_LIST_FULL_THRESHOLD = 20
AUTHOR_LIST_ELLIPSIS_THRESHOLD = 21
AUTHOR_LIST_ELLIPSIS_KEEP = 19

# ─── Quotation ─────────────────────────────────────────────────────────
# APA 7 §8.27 / §8.25: ≥ 40 words → block quote (indented, no quotation marks).
BLOCK_QUOTE_WORD_THRESHOLD = 40

# ─── Figures / Tables ──────────────────────────────────────────────────
CAPTION_POSITION_FIGURE = "above"
CAPTION_POSITION_TABLE = "above"
