from __future__ import annotations

import re
from collections.abc import Iterable

IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
IMAGE_LINE_PATTERN = re.compile(r"^\s*" + IMAGE_PATTERN.pattern + r"\s*$")

# Caption line shape in marker-converted markdown. The label word is configurable
# so new languages can extend coverage without changing the detector itself.
DEFAULT_CAPTION_LABELS = (
    "figure",
    "fig",
    "fig.",
    "picture",
    "pic",
    "pic.",
    "photo",
    "photograph",
    "foto",
    "table",
    "tbl",
    "tbl.",
    "tabel",
    "gambar",
    "diagram",
    "diagrama",
    "chart",
    "graph",
    "plate",
    "pl",
    "pl.",
    "scheme",
    "schema",
)
CAPTION_FORWARD_SCAN_LINES = 3
EMPHASIS_PATTERN = re.compile(r"\*+")
EXCESS_WHITESPACE_PATTERN = re.compile(r"\s+")
SPACE_BEFORE_PUNCTUATION_PATTERN = re.compile(r"\s+([:.,;\-\u2013])")
SPACE_AFTER_PUNCTUATION_PATTERN = re.compile(r"([:.,;\-\u2013])(\S)")


def normalize_caption_labels(labels: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_label in labels:
        label = " ".join(str(raw_label).strip().lower().split())
        if not label or label in seen:
            continue
        seen.add(label)
        normalized.append(label)
    return tuple(normalized)


def parse_caption_labels_text(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for raw_line in (text or "").splitlines():
        for candidate in raw_line.split(","):
            labels.append(candidate)
    return normalize_caption_labels(labels)


def build_caption_pattern(extra_labels: Iterable[str] = ()) -> re.Pattern[str]:
    labels = normalize_caption_labels((*DEFAULT_CAPTION_LABELS, *extra_labels))
    label_pattern = "|".join(sorted((re.escape(label) for label in labels), key=len, reverse=True))
    return re.compile(
        r"^\s*\*\*\s*"
        r"(?P<label>(?:" + label_pattern + r")(?:\s*[\d][\d.A-Za-z]*)?)"
        r"\s*[-\u2013:.,]?\s*\*\*"
        r"\s*[:.\-\u2013,]?\s*"
        r"(?P<body>.+?)\s*$",
        re.IGNORECASE,
    )


def caption_line_to_text(line: str) -> str:
    cleaned = EMPHASIS_PATTERN.sub("", (line or "").strip())
    cleaned = EXCESS_WHITESPACE_PATTERN.sub(" ", cleaned)
    cleaned = SPACE_BEFORE_PUNCTUATION_PATTERN.sub(r"\1", cleaned)
    cleaned = SPACE_AFTER_PUNCTUATION_PATTERN.sub(r"\1 \2", cleaned)
    return cleaned.strip()


def extract_image_captions(markdown_text: str, extra_labels: Iterable[str] = ()) -> dict[str, str]:
    if not markdown_text:
        return {}

    caption_pattern = build_caption_pattern(extra_labels)
    lines = markdown_text.splitlines()
    captions: dict[str, str] = {}
    seen: set[str] = set()
    index = 0

    while index < len(lines):
        if not IMAGE_LINE_PATTERN.match(lines[index]):
            index += 1
            continue

        block: list[str] = []
        while index < len(lines):
            line_match = IMAGE_LINE_PATTERN.match(lines[index])
            if line_match:
                path = (line_match.group(2) or "").strip()
                if path:
                    filename = path.rsplit("/", 1)[-1]
                    if filename and filename not in seen:
                        seen.add(filename)
                        block.append(filename)
                index += 1
                continue
            if lines[index].strip() == "":
                index += 1
                continue
            break

        caption = _find_caption_after_block(lines, index, caption_pattern)
        if not caption:
            continue
        caption_text = caption_line_to_text(caption)
        if not caption_text:
            continue
        for filename in block:
            captions[filename] = caption_text

    return captions


def _find_caption_after_block(
    lines: list[str],
    start_index: int,
    caption_pattern: re.Pattern[str],
) -> str:
    scanned = 0
    index = start_index
    while index < len(lines) and scanned < CAPTION_FORWARD_SCAN_LINES:
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        scanned += 1
        if caption_pattern.match(line):
            return line
        return ""
    return ""
