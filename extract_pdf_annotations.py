#!/usr/bin/env python3
"""
Extract PDF annotations and map each annotation to the subsection it belongs to.

Usage:
  python3 extract_pdf_annotations.py --pdf HASA_v2_CH.pdf --out annotations.json
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pdfplumber
from pypdf import PdfReader


LINE_TOP_TOLERANCE = 1.2
SEGMENT_GAP_THRESHOLD = 25.0

PATTERN_ROMAN_HEADING = re.compile(r"^[IVXLCDM]+\.\s+[A-Z0-9][A-Z0-9\-\s]*$")
PATTERN_ALPHA_HEADING = re.compile(r"^[A-H]\.(?!\s*[A-Z]\.)\s*[A-Za-z]")
PATTERN_NUMERIC_HEADING = re.compile(r"^\d+(?:\.\d+)+\s+[A-Za-z]")
PATTERN_KEYWORD_HEADING = re.compile(
    r"^(Abstract|Introduction|Related Work|Experimental Setup|Results|Discussion|Conclusion|References)\b",
    re.IGNORECASE,
)


def normalize_text(text: Any) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def parse_pdf_date(raw: Any) -> Optional[str]:
    text = normalize_text(raw)
    if not text:
        return None
    if text.startswith("D:"):
        text = text[2:]
    match = re.match(r"^(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", text)
    if not match:
        return normalize_text(raw)

    year = int(match.group(1))
    month = int(match.group(2) or 1)
    day = int(match.group(3) or 1)
    hour = int(match.group(4) or 0)
    minute = int(match.group(5) or 0)
    second = int(match.group(6) or 0)

    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc).isoformat()
    except ValueError:
        return normalize_text(raw)


def is_heading_candidate(text: str) -> bool:
    title = normalize_text(text)
    if len(title) < 3 or len(title) > 120:
        return False
    if title.startswith("["):
        return False
    if title.count(",") > 2:
        return False
    if "http" in title.lower():
        return False
    if any(quote in title for quote in ('"', "“", "”")):
        return False

    return bool(
        PATTERN_ROMAN_HEADING.match(title)
        or PATTERN_ALPHA_HEADING.match(title)
        or PATTERN_NUMERIC_HEADING.match(title)
        or PATTERN_KEYWORD_HEADING.match(title)
    )


def heading_level(title: str) -> int:
    text = normalize_text(title)
    if PATTERN_ROMAN_HEADING.match(text):
        return 1
    if PATTERN_ALPHA_HEADING.match(text):
        return 2
    if PATTERN_NUMERIC_HEADING.match(text):
        return 3
    if PATTERN_KEYWORD_HEADING.match(text):
        return 1
    return 9


def cluster_words_into_lines(words: Iterable[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    lines: List[Dict[str, Any]] = []
    for word in sorted(words, key=lambda w: (float(w["top"]), float(w["x0"]))):
        word_top = float(word["top"])
        assigned = False
        for line in lines:
            if abs(word_top - line["top"]) <= LINE_TOP_TOLERANCE:
                line["words"].append(word)
                assigned = True
                break
        if not assigned:
            lines.append({"top": word_top, "words": [word]})
    return [line["words"] for line in lines]


def split_line_into_segments(words: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    sorted_words = sorted(words, key=lambda w: float(w["x0"]))
    segments: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    previous_x1: Optional[float] = None

    for word in sorted_words:
        x0 = float(word["x0"])
        if previous_x1 is not None and x0 - previous_x1 > SEGMENT_GAP_THRESHOLD:
            if current:
                segments.append(current)
            current = []
        current.append(word)
        previous_x1 = float(word["x1"])

    if current:
        segments.append(current)
    return segments


def detect_headings(pdf_path: Path) -> List[Dict[str, Any]]:
    headings: List[Dict[str, Any]] = []
    with pdfplumber.open(str(pdf_path)) as plumber_pdf:
        for page_index, page in enumerate(plumber_pdf.pages):
            words = page.extract_words(use_text_flow=True) or []
            if not words:
                continue

            for line_words in cluster_words_into_lines(words):
                for segment_words in split_line_into_segments(line_words):
                    title = normalize_text(" ".join(w["text"] for w in segment_words))
                    if not is_heading_candidate(title):
                        continue

                    top = sum(float(w["top"]) for w in segment_words) / len(segment_words)
                    x0 = float(segment_words[0]["x0"])
                    column = 0 if x0 < (float(page.width) / 2.0) else 1
                    headings.append(
                        {
                            "title": title,
                            "level": heading_level(title),
                            "page_index": page_index,
                            "page": page_index + 1,
                            "top_from_top": round(top, 3),
                            "x0": round(x0, 3),
                            "column_index": column,
                            "column": "left" if column == 0 else "right",
                        }
                    )

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for heading in sorted(
        headings,
        key=lambda h: (h["page_index"], h["column_index"], h["top_from_top"], h["x0"]),
    ):
        key = (heading["page_index"], heading["column_index"], round(heading["top_from_top"], 1), heading["title"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(heading)

    for index, heading in enumerate(deduped, start=1):
        heading["heading_index"] = index

    return deduped


def select_subsection(
    *,
    page_index: int,
    column_index: int,
    top_from_top: Optional[float],
    headings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not headings:
        return {
            "heading_index": None,
            "title": "Document Start",
            "level": 0,
            "page": 1,
            "page_index": 0,
            "column_index": 0,
            "column": "left",
            "top_from_top": 0.0,
        }

    if top_from_top is not None:
        same_page_same_column = [
            h
            for h in headings
            if h["page_index"] == page_index
            and h["column_index"] == column_index
            and h["top_from_top"] <= top_from_top + 1e-6
        ]
        if same_page_same_column:
            return max(same_page_same_column, key=lambda h: h["top_from_top"])

        same_page_any_column = [
            h for h in headings if h["page_index"] == page_index and h["top_from_top"] <= top_from_top + 1e-6
        ]
        if same_page_any_column:
            return max(same_page_any_column, key=lambda h: (h["column_index"] == column_index, h["top_from_top"]))

    previous_headings = [h for h in headings if h["page_index"] < page_index]
    if previous_headings:
        return max(previous_headings, key=lambda h: (h["page_index"], h["column_index"], h["top_from_top"]))

    first = headings[0]
    return {
        "heading_index": first.get("heading_index"),
        "title": "Document Start",
        "level": 0,
        "page": 1,
        "page_index": 0,
        "column_index": 0,
        "column": "left",
        "top_from_top": 0.0,
    }


def annotation_type_name(subtype: str) -> str:
    if subtype.startswith("/"):
        return subtype[1:]
    return subtype


def extract_annotations(
    pdf_path: Path,
    headings: List[Dict[str, Any]],
    include_popup: bool,
) -> List[Dict[str, Any]]:
    reader = PdfReader(str(pdf_path))
    annotations: List[Dict[str, Any]] = []

    for page_index, page in enumerate(reader.pages):
        annots = page.get("/Annots")
        if annots is None:
            continue
        annots = annots.get_object() if hasattr(annots, "get_object") else annots

        page_width = float(page.mediabox.right) - float(page.mediabox.left)
        page_height = float(page.mediabox.top) - float(page.mediabox.bottom)

        for annot_ref in annots:
            annot_obj = annot_ref.get_object()
            subtype_raw = str(annot_obj.get("/Subtype") or "")
            subtype = annotation_type_name(subtype_raw)

            if not include_popup and subtype_raw == "/Popup":
                continue

            rect = annot_obj.get("/Rect")
            rect_values: Optional[List[float]] = None
            x_center: Optional[float] = None
            y_center: Optional[float] = None
            top_from_top: Optional[float] = None
            column_index = 0

            if rect is not None:
                try:
                    rect_values = [float(value) for value in rect]
                    x0, y0, x1, y1 = rect_values
                    x_center = (x0 + x1) / 2.0
                    y_center = (y0 + y1) / 2.0
                    top_from_top = page_height - max(y0, y1)
                    column_index = 0 if x_center < (page_width / 2.0) else 1
                except Exception:
                    rect_values = None

            subsection = select_subsection(
                page_index=page_index,
                column_index=column_index,
                top_from_top=top_from_top,
                headings=headings,
            )

            annotation = {
                "page": page_index + 1,
                "annotation_type": subtype,
                "subtype_raw": subtype_raw,
                "author": normalize_text(annot_obj.get("/T")) or None,
                "subject": normalize_text(annot_obj.get("/Subj")) or None,
                "comment": normalize_text(annot_obj.get("/Contents")) or None,
                "id": normalize_text(annot_obj.get("/NM")) or None,
                "created_at": parse_pdf_date(annot_obj.get("/CreationDate")),
                "modified_at": parse_pdf_date(annot_obj.get("/M")),
                "rectangle": rect_values,
                "x_center": round(x_center, 3) if x_center is not None else None,
                "y_center": round(y_center, 3) if y_center is not None else None,
                "top_from_top": round(top_from_top, 3) if top_from_top is not None else None,
                "column_index": column_index,
                "column": "left" if column_index == 0 else "right",
                "subsection": {
                    "heading_index": subsection.get("heading_index"),
                    "title": subsection["title"],
                    "level": subsection.get("level"),
                    "page": subsection.get("page"),
                },
            }
            annotations.append(annotation)

    annotations.sort(
        key=lambda a: (
            a["page"],
            a["column_index"],
            a["top_from_top"] if a["top_from_top"] is not None else 1e9,
            a["x_center"] if a["x_center"] is not None else 1e9,
            a["id"] or "",
        )
    )
    for index, annotation in enumerate(annotations, start=1):
        annotation["annotation_index"] = index
    return annotations


def build_subsection_index(annotations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    ordered_keys: List[str] = []

    for annotation in annotations:
        subsection = annotation["subsection"]
        key = f"{subsection.get('heading_index')}::{subsection['title']}"
        if key not in buckets:
            buckets[key] = {
                "heading_index": subsection.get("heading_index"),
                "title": subsection["title"],
                "level": subsection.get("level"),
                "page": subsection.get("page"),
                "annotation_indexes": [],
                "annotation_count": 0,
            }
            ordered_keys.append(key)

        buckets[key]["annotation_indexes"].append(annotation["annotation_index"])
        buckets[key]["annotation_count"] += 1

    result = []
    for order, key in enumerate(ordered_keys, start=1):
        row = buckets[key]
        row["subsection_order"] = order
        result.append(row)
    return result


def resolve_default_pdf(cwd: Path) -> Path:
    pdf_files = sorted(cwd.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError("No PDF files were found in the current directory.")
    return pdf_files[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract annotations from a PDF and assign each annotation to a subsection."
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Source PDF path. Defaults to the first *.pdf file in the current directory.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path. Defaults to <pdf_stem>_annotations.json.",
    )
    parser.add_argument(
        "--include-popup",
        action="store_true",
        help="Include /Popup annotations. By default these are skipped because they are usually duplicates.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cwd = Path.cwd()
    pdf_path = args.pdf if args.pdf else resolve_default_pdf(cwd)
    pdf_path = pdf_path if pdf_path.is_absolute() else (cwd / pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    out_path = args.out
    if out_path is None:
        out_path = pdf_path.with_name(f"{pdf_path.stem}_annotations.json")
    out_path = out_path if out_path.is_absolute() else (cwd / out_path)

    headings = detect_headings(pdf_path)
    annotations = extract_annotations(pdf_path, headings=headings, include_popup=args.include_popup)
    subsection_index = build_subsection_index(annotations)

    payload = {
        "source_pdf": str(pdf_path),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "settings": {
            "include_popup": bool(args.include_popup),
            "line_top_tolerance": LINE_TOP_TOLERANCE,
            "segment_gap_threshold": SEGMENT_GAP_THRESHOLD,
        },
        "detected_headings": headings,
        "subsections": subsection_index,
        "annotations": annotations,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Source PDF: {pdf_path}")
    print(f"Detected headings: {len(headings)}")
    print(f"Extracted annotations: {len(annotations)}")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
