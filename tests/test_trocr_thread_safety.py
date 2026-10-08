from concurrent.futures import ThreadPoolExecutor
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtCore import QThreadPool
from PyQt6.QtTest import QTest

from ocr.trocr_engine import TrOCREngine
from tests.test_workflow_sessions import draft, make_window


class ControlledTrOCREngine(TrOCREngine):
    def __init__(self, gate: threading.Event | None = None) -> None:
        super().__init__({"model_name": "controlled"})
        self.gate = gate
        self.started = threading.Event()
        self.completed = threading.Event()
        self.load_calls = 0
        self.active_calls = 0
        self.max_active_calls = 0
        self.completed_calls = 0
        self.state_lock = threading.Lock()

    def _load_components(self) -> None:
        with self.state_lock:
            self.load_calls += 1
        time.sleep(0.03)
        self._processor = object()
        self._model = object()
        self._device = "cpu"

    def _recognize_image(self, image: np.ndarray) -> str:
        with self.state_lock:
            self.active_calls += 1
            self.max_active_calls = max(
                self.max_active_calls,
                self.active_calls,
            )
        self.started.set()
        try:
            if self.gate is not None:
                assert self.gate.wait(timeout=3)
            time.sleep(0.04)
            return "BODY TEXT" if int(image[0, 0]) == 1 else "REFERENCE TEXT"
        finally:
            with self.state_lock:
                self.active_calls -= 1
                self.completed_calls += 1
                if self.completed_calls >= 2:
                    self.completed.set()


def fake_preprocess(image_path) -> dict:
    marker = 1 if "body" in Path(image_path).stem else 2
    return {
        "gray": np.array([[marker]], dtype=np.uint8),
        "line_boxes": [],
    }


def wait_for(predicate, timeout_ms: int = 3000) -> None:
    elapsed = 0
    while not predicate() and elapsed < timeout_ms:
        QTest.qWait(12)
        elapsed += 12
    assert predicate()


def test_trocr_instance_serializes_load_preprocess_and_inference(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "ocr.trocr_engine.preprocess_for_ocr",
        fake_preprocess,
    )
    engine = ControlledTrOCREngine()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(engine.recognize, ["body.png", "reference.png"])
        )

    assert set(results) == {"BODY TEXT", "REFERENCE TEXT"}
    assert engine.load_calls == 1
    assert engine.max_active_calls == 1


def test_local_body_and_reference_workers_share_serial_engine(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "ocr.trocr_engine.preprocess_for_ocr",
        fake_preprocess,
    )
    window, db = make_window(tmp_path)
    window.config.set("ocr.mode", "local")
    engine = ControlledTrOCREngine()
    window.ocr_engine = engine
    window.thread_pool = QThreadPool()
    window.thread_pool.setMaxThreadCount(2)
    body_path = tmp_path / "body.png"
    reference_path = tmp_path / "reference.png"
    Image.new("RGB", (12, 12), "white").save(body_path)
    Image.new("RGB", (12, 12), "white").save(reference_path)
    essay_draft = draft("学生", "题目")
    essay_draft.update(
        input_mode="ocr",
        image_path=str(body_path),
        excellent_path=str(reference_path),
    )

    window._start_recognition(essay_draft)
    wait_for(
        lambda: "ocr" not in window._active_jobs
        and "reference" not in window._active_jobs
    )

    assert engine.load_calls == 1
    assert engine.max_active_calls == 1
    assert window.ocr_page.get_text() == "BODY TEXT"
    assert window._reference_text == "REFERENCE TEXT"
    essay = db.get_essay(window._current_essay_id)
    assert essay is not None
    assert essay["ocr_text"] == "BODY TEXT"
    window.close()


def test_queued_local_ocr_from_old_session_is_discarded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "ocr.trocr_engine.preprocess_for_ocr",
        fake_preprocess,
    )
    window, db = make_window(tmp_path)
    window.config.set("ocr.mode", "local")
    gate = threading.Event()
    engine = ControlledTrOCREngine(gate)
    window.ocr_engine = engine
    window.thread_pool = QThreadPool()
    window.thread_pool.setMaxThreadCount(2)
    body_path = tmp_path / "old-body.png"
    reference_path = tmp_path / "old-reference.png"
    Image.new("RGB", (12, 12), "white").save(body_path)
    Image.new("RGB", (12, 12), "white").save(reference_path)
    old_draft = draft("旧学生", "旧题目")
    old_draft.update(
        input_mode="ocr",
        image_path=str(body_path),
        excellent_path=str(reference_path),
    )

    window._start_recognition(old_draft)
    assert engine.started.wait(timeout=2)
    QTest.qWait(50)
    assert "串行识别" in window.ocr_page.hint_label.text()
    window._start_recognition(draft("新学生", "新题目"))
    gate.set()
    wait_for(engine.completed.is_set)
    QTest.qWait(100)

    assert engine.max_active_calls == 1
    assert window.ocr_page.get_text() == ""
    assert window._reference_text == ""
    assert db.count_essays() == 0
    window.close()
