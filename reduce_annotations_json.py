#!/usr/bin/env python3
"""
Reduce extracted annotations JSON to only:
  - comment
  - subsection_title
  - page
  - highlighted_text

Usage:
  python3 reduce_annotations_json.py --input HASA_v2_CH_annotations_all.json --output minimal_annotations.json --pdf HASA_v2_CH.pdf
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pdfplumber
from pypdf import PdfReader


MARKUP_TYPES = {"Highlight", "StrikeOut", "Underline", "Squiggly"}
GEOMETRY_TOLERANCE = 0.75

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Keep only comment, subsection title, page, and highlighted text from an annotations JSON file."
    )
    parser.add_argument("--input", type=Path, required=True, help="Path to full annotations JSON file.")
    parser.add_argument("--output", type=Path, required=True, help="Path to output reduced JSON file.")
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="PDF source path. If omitted, uses 'source_pdf' from the input JSON.",
    )
    parser.add_argument(
        "--drop-empty-comments",
        action="store_true",
        help="Skip rows where comment is empty/null.",
    )
    return parser.parse_args()


def get_annotations(payload: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("annotations"), list):
        return payload["annotations"]
    if isinstance(payload, list):
        return payload
    raise ValueError("Input JSON must be either a list or an object containing an 'annotations' list.")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def pop_match(mapping: Dict[Tuple[Any, ...], List[Optional[str]]], key: Tuple[Any, ...]) -> Tuple[bool, Optional[str]]:
    rows = mapping.get(key)
    if not rows:
        return False, None
    return True, rows.pop(0)


def resolve_pdf_path(args: argparse.Namespace, payload: Any, input_path: Path) -> Path:
    if args.pdf is not None:
        pdf_path = args.pdf
    elif isinstance(payload, dict) and payload.get("source_pdf"):
        pdf_path = Path(str(payload["source_pdf"]))
    else:
        raise ValueError("Could not resolve source PDF path. Pass --pdf or include 'source_pdf' in input JSON.")

    if not pdf_path.is_absolute():
        pdf_path = (input_path.parent / pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    return pdf_path


def build_page_words(pdf_path: Path) -> Dict[int, List[Dict[str, float | str]]]:
    page_words: Dict[int, List[Dict[str, float | str]]] = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_index, page in enumerate(pdf.pages):
            words = page.extract_words(use_text_flow=True) or []
            page_height = float(page.height)
            rows: List[Dict[str, float | str]] = []
            for word in words:
                text = normalize_text(word.get("text"))
                if not text:
                    continue
                x0 = float(word["x0"])
                x1 = float(word["x1"])
                top = float(word["top"])
                bottom = float(word["bottom"])
                y_center_top = (top + bottom) / 2.0
                y_center_pdf = page_height - y_center_top
                rows.append(
                    {
                        "text": text,
                        "x0": x0,
                        "x_center": (x0 + x1) / 2.0,
                        "y_center_pdf": y_center_pdf,
                    }
                )
            page_words[page_index] = rows
    return page_words


def boxes_from_quadpoints(quadpoints: Optional[List[float]]) -> List[Tuple[float, float, float, float]]:
    if not quadpoints:
        return []
    boxes: List[Tuple[float, float, float, float]] = []
    values = [float(v) for v in quadpoints]
    for i in range(0, len(values) - 7, 8):
        quad = values[i : i + 8]
        xs = quad[0::2]
        ys = quad[1::2]
        boxes.append((min(xs), max(xs), min(ys), max(ys)))
    return boxes


def box_from_rect(rect: Optional[List[float]]) -> List[Tuple[float, float, float, float]]:
    if not rect or len(rect) != 4:
        return []
    x0, y0, x1, y1 = [float(v) for v in rect]
    return [(min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1))]


def extract_text_in_boxes(
    page_words: List[Dict[str, float | str]], boxes: List[Tuple[float, float, float, float]]
) -> Optional[str]:
    if not boxes:
        return None

    chunks: List[str] = []
    for xmin, xmax, ymin, ymax in boxes:
        selected = []
        for word in page_words:
            x_center = float(word["x_center"])
            y_center = float(word["y_center_pdf"])
            if (
                xmin - GEOMETRY_TOLERANCE <= x_center <= xmax + GEOMETRY_TOLERANCE
                and ymin - GEOMETRY_TOLERANCE <= y_center <= ymax + GEOMETRY_TOLERANCE
            ):
                selected.append(word)

        selected.sort(key=lambda w: (-float(w["y_center_pdf"]), float(w["x0"])))
        chunk = normalize_text(" ".join(str(w["text"]) for w in selected))
        if chunk and (not chunks or chunk != chunks[-1]):
            chunks.append(chunk)

    merged = normalize_text(" ".join(chunks))
    return merged or None


def build_raw_annotations_with_highlight_text(pdf_path: Path) -> List[Dict[str, Any]]:
    page_words = build_page_words(pdf_path)
    reader = PdfReader(str(pdf_path))

    raw_annotations: List[Dict[str, Any]] = []
    for page_index, page in enumerate(reader.pages):
        annots = page.get("/Annots")
        if not annots:
            continue
        annots = annots.get_object() if hasattr(annots, "get_object") else annots
        page_width = float(page.mediabox.right) - float(page.mediabox.left)
        page_height = float(page.mediabox.top) - float(page.mediabox.bottom)

        for annot_ref in annots:
            annot_obj = annot_ref.get_object()
            subtype_raw = str(annot_obj.get("/Subtype") or "")
            subtype = subtype_raw[1:] if subtype_raw.startswith("/") else subtype_raw
            nm = normalize_text(annot_obj.get("/NM")) or None

            rect_obj = annot_obj.get("/Rect")
            rect: Optional[List[float]] = None
            top_from_top: Optional[float] = None
            x_center: Optional[float] = None
            column_index = 0
            if rect_obj is not None:
                rect = [float(v) for v in rect_obj]
                x_center = (rect[0] + rect[2]) / 2.0
                top_from_top = page_height - max(rect[1], rect[3])
                column_index = 0 if x_center < (page_width / 2.0) else 1

            quadpoints_obj = annot_obj.get("/QuadPoints")
            quadpoints = [float(v) for v in quadpoints_obj] if quadpoints_obj is not None else None

            parent_ref = annot_obj.get("/Parent")
            parent_objid = getattr(parent_ref, "idnum", None) if parent_ref is not None else None
            objid = getattr(annot_ref, "idnum", None)

            raw_annotations.append(
                {
                    "page": page_index + 1,
                    "page_index": page_index,
                    "subtype": subtype,
                    "id": nm,
                    "top_from_top": round(top_from_top, 3) if top_from_top is not None else None,
                    "x_center": round(x_center, 3) if x_center is not None else None,
                    "column_index": column_index,
                    "rect": rect,
                    "quadpoints": quadpoints,
                    "objid": objid,
                    "parent_objid": parent_objid,
                }
            )

    raw_annotations.sort(
        key=lambda a: (
            a["page"],
            a["column_index"],
            a["top_from_top"] if a["top_from_top"] is not None else 1e9,
            a["x_center"] if a["x_center"] is not None else 1e9,
            a["id"] or "",
        )
    )

    objid_to_index: Dict[int, int] = {}
    for index, row in enumerate(raw_annotations):
        if row["objid"] is not None:
            objid_to_index[int(row["objid"])] = index

    memo: Dict[int, Optional[str]] = {}

    def compute_highlighted_text(index: int, seen: Optional[set[int]] = None) -> Optional[str]:
        if index in memo:
            return memo[index]
        if seen is None:
            seen = set()
        if index in seen:
            return None
        seen.add(index)

        row = raw_annotations[index]
        subtype = row["subtype"]
        text: Optional[str] = None

        if subtype in MARKUP_TYPES:
            boxes = boxes_from_quadpoints(row.get("quadpoints")) or box_from_rect(row.get("rect"))
            text = extract_text_in_boxes(page_words.get(row["page_index"], []), boxes)
        elif subtype == "Popup":
            parent_objid = row.get("parent_objid")
            if parent_objid is not None and int(parent_objid) in objid_to_index:
                text = compute_highlighted_text(objid_to_index[int(parent_objid)], seen)

        memo[index] = text
        return text

    for i in range(len(raw_annotations)):
        raw_annotations[i]["highlighted_text"] = compute_highlighted_text(i)

    return raw_annotations


def main() -> None:
    args = parse_args()
    input_path = args.input.resolve()
    output_path = args.output.resolve()

    data = json.loads(input_path.read_text(encoding="utf-8"))
    annotations = list(get_annotations(data))
    pdf_path = resolve_pdf_path(args, data, input_path)
    raw_annotations = build_raw_annotations_with_highlight_text(pdf_path)

    by_full_key: Dict[Tuple[Any, ...], List[Optional[str]]] = defaultdict(list)
    by_id_key: Dict[Tuple[Any, ...], List[Optional[str]]] = defaultdict(list)
    by_position_key: Dict[Tuple[Any, ...], List[Optional[str]]] = defaultdict(list)
    for raw in raw_annotations:
        full_key = (
            raw["page"],
            raw["subtype"],
            raw["top_from_top"],
            raw["x_center"],
            raw["id"] or "",
        )
        by_full_key[full_key].append(raw.get("highlighted_text"))

        id_key = (raw["page"], raw["subtype"], raw["id"] or "")
        by_id_key[id_key].append(raw.get("highlighted_text"))

        position_key = (raw["page"], raw["subtype"], raw["top_from_top"], raw["x_center"])
        by_position_key[position_key].append(raw.get("highlighted_text"))

    reduced: List[Dict[str, Any]] = []
    matched_count = 0
    for ann in annotations:
        comment = ann.get("comment")
        if args.drop_empty_comments and (comment is None or str(comment).strip() == ""):
            continue

        subsection = ann.get("subsection") or {}
        subsection_title = subsection.get("title")
        if subsection_title is None:
            subsection_title = ann.get("subsection_title")

        subtype = ann.get("annotation_type")
        if not subtype and ann.get("subtype_raw"):
            subtype_raw = str(ann.get("subtype_raw"))
            subtype = subtype_raw[1:] if subtype_raw.startswith("/") else subtype_raw
        subtype = normalize_text(subtype)

        page = ann.get("page")
        top_from_top = to_float(ann.get("top_from_top"))
        x_center = to_float(ann.get("x_center"))
        ann_id = normalize_text(ann.get("id")) or ""

        full_key = (
            page,
            subtype,
            round(top_from_top, 3) if top_from_top is not None else None,
            round(x_center, 3) if x_center is not None else None,
            ann_id,
        )
        found, highlighted_text = pop_match(by_full_key, full_key)
        if not found:
            found, highlighted_text = pop_match(by_id_key, (page, subtype, ann_id))
        if not found:
            found, highlighted_text = pop_match(
                by_position_key,
                (
                    page,
                    subtype,
                    round(top_from_top, 3) if top_from_top is not None else None,
                    round(x_center, 3) if x_center is not None else None,
                ),
            )
        if found:
            matched_count += 1

        reduced.append(
            {
                "comment": comment,
                "subsection_title": subsection_title,
                "page": page,
                "highlighted_text": highlighted_text,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(reduced, ensure_ascii=False, indent=2), encoding="utf-8")
    with_highlighted_text = sum(1 for row in reduced if normalize_text(row.get("highlighted_text")))

    print(f"Source PDF: {pdf_path}")
    print(f"Input annotations: {len(annotations)}")
    print(f"Output rows: {len(reduced)}")
    print(f"Matched to PDF annotations: {matched_count}")
    print(f"Rows with highlighted_text: {with_highlighted_text}")
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
