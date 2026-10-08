from pathlib import Path

import cv2
import numpy as np

from ocr.image_process import preprocess_for_ocr


def _write_text_image(path: Path) -> None:
    image = np.full((300, 900, 3), 255, dtype=np.uint8)
    cv2.putText(
        image,
        "I went to the park with my classmates",
        (25, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (0, 0, 0),
        3,
        cv2.LINE_AA,
    )
    cv2.putText(
        image,
        "We had a wonderful time together",
        (25, 200),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (0, 0, 0),
        3,
        cv2.LINE_AA,
    )
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    path.write_bytes(encoded.tobytes())


def test_preprocess_detects_lines(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    _write_text_image(image_path)
    result = preprocess_for_ocr(image_path)
    assert result["gray"].ndim == 2
    assert len(result["line_boxes"]) >= 2
    assert len(result["text_boxes"]) >= 2
