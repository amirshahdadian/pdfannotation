# PDF Annotation Extractor

Small Python toolkit to:

1. extract annotations from a PDF,
2. map each annotation to the most likely subsection based on page text layout,
3. reduce the output JSON to a minimal schema for downstream processing.

## Features

- Supports common annotation types (`Highlight`, `StrikeOut`, `Text`, and optional `Popup`).
- Maps each annotation to a subsection title in reading order.
- Extracts highlighted text from annotation geometry (`QuadPoints`/`Rect`).
- Produces both rich and minimal JSON outputs.

## Requirements

- Python 3.10+
- Dependencies in [`requirements.txt`](./requirements.txt)

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For development:

```bash
pip install -r requirements-dev.txt
```

## Usage

### 1) Extract rich annotations JSON

```bash
python3 extract_pdf_annotations.py \
  --pdf /absolute/path/to/input.pdf \
  --out /absolute/path/to/output_annotations.json
```

Include popup annotations (usually duplicates of markup comments):

```bash
python3 extract_pdf_annotations.py \
  --pdf /absolute/path/to/input.pdf \
  --out /absolute/path/to/output_annotations_all.json \
  --include-popup
```

### 2) Reduce to minimal JSON

Minimal output fields:

- `comment`
- `subsection_title`
- `page`
- `highlighted_text`

```bash
python3 reduce_annotations_json.py \
  --input /absolute/path/to/output_annotations_all.json \
  --output /absolute/path/to/output_annotations_minimal.json \
  --pdf /absolute/path/to/input.pdf
```

Drop rows with empty/null comments:

```bash
python3 reduce_annotations_json.py \
  --input /absolute/path/to/output_annotations_all.json \
  --output /absolute/path/to/output_annotations_minimal.json \
  --pdf /absolute/path/to/input.pdf \
  --drop-empty-comments
```

## Output Notes

- `highlighted_text` is populated for markup annotations (`Highlight`, `StrikeOut`, etc.) and for `Popup` when it can be traced to its parent markup.
- Some annotations may still have `highlighted_text: null` when geometry is missing/ambiguous.

## Repository Hygiene

- `.gitignore` excludes local PDFs and generated JSON by default.
- If you need to share sample data, add explicitly redacted files and commit with `git add -f`.

## Development

Run tests:

```bash
pytest
```

Run lint:

```bash
ruff check .
```

## License

MIT. See [`LICENSE`](./LICENSE).

