from reduce_annotations_json import boxes_from_quadpoints, extract_text_in_boxes, normalize_text


def test_normalize_text():
    assert normalize_text(None) == ""
    assert normalize_text("  alpha   beta\n") == "alpha beta"


def test_boxes_from_quadpoints():
    quadpoints = [10, 20, 30, 20, 10, 10, 30, 10]
    boxes = boxes_from_quadpoints(quadpoints)
    assert boxes == [(10.0, 30.0, 10.0, 20.0)]


def test_extract_text_in_boxes():
    words = [
        {"text": "hello", "x0": 10.0, "x_center": 15.0, "y_center_pdf": 50.0},
        {"text": "world", "x0": 25.0, "x_center": 30.0, "y_center_pdf": 50.0},
        {"text": "outside", "x0": 200.0, "x_center": 210.0, "y_center_pdf": 50.0},
    ]
    boxes = [(8.0, 40.0, 48.0, 52.0)]
    assert extract_text_in_boxes(words, boxes) == "hello world"

