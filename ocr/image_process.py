"""OpenCV image preprocessing for handwritten English essays."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from logger_config import get_logger


log = get_logger("ocr.image_process")


class ImageProcessingError(RuntimeError):
    """Raised when an image cannot be read or processed."""


def load_image(path: str | Path) -> np.ndarray:
    """Read an image from disk as a BGR ndarray."""
    path = Path(path)
    # OpenCV's imread is not reliable with non-ASCII Windows paths.
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        raise ImageProcessingError(f"无法读取图片: {path}")
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ImageProcessingError(f"无法读取图片: {path}")
    return image


def to_grayscale(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image.copy()
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def estimate_skew_angle(gray: np.ndarray) -> float:
    """Estimate a small page skew angle in degrees.

    Angles are normalized to [-45, 45]. Very small values are ignored by the
    caller to avoid rotating almost-straight pages unnecessarily.
    """
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    binary = cv2.adaptiveThreshold(
        blur,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        11,
        8,
    )
    contours, _ = cv2.findContours(
        binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )
    angles: list[float] = []
    for contour in contours:
        if cv2.contourArea(contour) < 80:
            continue
        rect = cv2.minAreaRect(contour)
        angle = rect[2]
        if angle > 45:
            angle -= 90
        elif angle < -45:
            angle += 90
        if abs(angle) < 30:
            angles.append(angle)
    if not angles:
        return 0.0
    return float(np.median(angles))


def rotate_image(image: np.ndarray, angle_degrees: float) -> np.ndarray:
    """Rotate around the image center with an expanded canvas."""
    if abs(angle_degrees) < 0.25:
        return image
    h, w = image.shape[:2]
    center = (w / 2, h / 2)
    matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_w = int((h * sin) + (w * cos))
    new_h = int((h * cos) + (w * sin))
    matrix[0, 2] += (new_w / 2) - center[0]
    matrix[1, 2] += (new_h / 2) - center[1]
    return cv2.warpAffine(
        image,
        matrix,
        (new_w, new_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def denoise(gray: np.ndarray) -> np.ndarray:
    """Denoise while preserving thin handwriting strokes."""
    return cv2.fastNlMeansDenoising(gray, None, h=8, templateWindowSize=7, searchWindowSize=21)


def binarize(gray: np.ndarray, method: str = "adaptive") -> np.ndarray:
    """Convert a grayscale image to a white-on-black binary mask."""
    method = method.lower()
    if method == "otsu":
        _, binary = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
        return binary
    if method == "sauvola":
        # Sauvola is not in core OpenCV, so approximate with a large adaptive
        # window and a moderate constant for a paper photograph.
        return cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            35,
            12,
        )
    return cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        15,
        8,
    )


def enhance(gray: np.ndarray) -> np.ndarray:
    """Return a clean grayscale image suitable for TrOCR."""
    denoised = denoise(gray)
    return cv2.medianBlur(denoised, 3)


def detect_text_regions(
    binary: np.ndarray,
    min_area: int = 120,
) -> list[tuple[int, int, int, int]]:
    """Return bounding boxes for candidate text regions.

    Coordinates are ``(x, y, w, h)`` and sorted left-to-right, top-to-bottom.
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(
        closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    boxes: list[tuple[int, int, int, int]] = []
    for contour in contours:
        if cv2.contourArea(contour) < min_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if h < 8 or w < 8:
            continue
        boxes.append((x, y, w, h))
    boxes.sort(key=lambda box: (round(box[1] / 20), box[0]))
    return boxes


def segment_lines(
    binary: np.ndarray,
    min_height: int = 8,
) -> list[tuple[int, int, int, int]]:
    """Split a page into line bounding boxes."""
    horizontal = cv2.getStructuringElement(cv2.MORPH_RECT, (45, 1))
    merged = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, horizontal)
    contours, _ = cv2.findContours(
        merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    boxes: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h >= min_height and w >= 10:
            boxes.append((x, y, w, h))
    boxes.sort(key=lambda box: box[1])
    return boxes


def crop_regions(
    image: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
    padding: int = 4,
) -> list[np.ndarray]:
    crops: list[np.ndarray] = []
    h, w = image.shape[:2]
    for x, y, bw, bh in boxes:
        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(w, x + bw + padding)
        y2 = min(h, y + bh + padding)
        crops.append(image[y1:y2, x1:x2])
    return crops


def preprocess_for_ocr(
    image_path: str | Path,
    *,
    auto_rotate: bool = True,
    binarize_method: str = "adaptive",
) -> dict[str, Any]:
    """Run the complete image pipeline and return reusable artifacts.

    The returned dict contains the enhanced grayscale image, binary mask,
    detected text regions, and segmented line boxes. TrOCR normally uses the
    enhanced image; the binary artifacts support debugging and future layout
    analysis.
    """
    original = load_image(image_path)
    gray = to_grayscale(original)
    rotated_gray = gray
    if auto_rotate:
        angle = estimate_skew_angle(gray)
        if abs(angle) >= 0.35:
            log.info("Deskew image by %.2f degrees", angle)
            rotated_gray = rotate_image(gray, angle)
    clean_gray = enhance(rotated_gray)
    binary = binarize(clean_gray, method=binarize_method)
    text_boxes = detect_text_regions(binary)
    line_boxes = segment_lines(binary)
    return {
        "original": original,
        "gray": clean_gray,
        "binary": binary,
        "text_boxes": text_boxes,
        "line_boxes": line_boxes,
    }


def save_preview(image: np.ndarray, path: str | Path) -> Path:
    """Save a processed image for the confirmation UI."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
        suffix = ".png"
    ok, encoded = cv2.imencode(suffix, image)
    if not ok:
        raise ImageProcessingError(f"无法保存处理后的图片: {path}")
    path.write_bytes(encoded.tobytes())
    return path
