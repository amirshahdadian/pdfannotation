from extract_pdf_annotations import (
    heading_level,
    is_heading_candidate,
    normalize_text,
    parse_pdf_date,
    select_subsection,
)


def test_normalize_text():
    assert normalize_text(None) == ""
    assert normalize_text("  hello   world \n") == "hello world"


def test_parse_pdf_date():
    value = parse_pdf_date("D:20260319153045")
    assert value is not None
    assert value.startswith("2026-03-19T15:30:45")


def test_is_heading_candidate():
    assert is_heading_candidate("I. INTRODUCTION")
    assert is_heading_candidate("A. Method Overview")
    assert is_heading_candidate("References")
    assert not is_heading_candidate("this is a normal sentence in paragraph text")


def test_heading_level():
    assert heading_level("I. INTRODUCTION") == 1
    assert heading_level("A. Method Overview") == 2
    assert heading_level("1.2 Dataset") == 3


def test_select_subsection_prefers_same_page_and_column():
    headings = [
        {
            "heading_index": 1,
            "title": "I. INTRODUCTION",
            "level": 1,
            "page": 1,
            "page_index": 0,
            "column_index": 0,
            "column": "left",
            "top_from_top": 100.0,
        },
        {
            "heading_index": 2,
            "title": "A. Prior Work",
            "level": 2,
            "page": 1,
            "page_index": 0,
            "column_index": 1,
            "column": "right",
            "top_from_top": 140.0,
        },
    ]
    selected = select_subsection(page_index=0, column_index=0, top_from_top=220.0, headings=headings)
    assert selected["title"] == "I. INTRODUCTION"


def test_select_subsection_falls_back_to_previous_page():
    headings = [
        {
            "heading_index": 1,
            "title": "I. INTRODUCTION",
            "level": 1,
            "page": 1,
            "page_index": 0,
            "column_index": 0,
            "column": "left",
            "top_from_top": 100.0,
        }
    ]
    selected = select_subsection(page_index=2, column_index=1, top_from_top=50.0, headings=headings)
    assert selected["title"] == "I. INTRODUCTION"

