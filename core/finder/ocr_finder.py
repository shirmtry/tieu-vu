"""OCR fallback finder — returns bbox only; OCR text is never stored.

Uses RapidOCR over an in-memory screen grab (``mss``). No screenshots are
written to disk and no OCR text is logged.
"""

from __future__ import annotations

import hashlib
import logging

log = logging.getLogger(__name__)


class OcrFinder:
    def __init__(self, min_conf: float = 0.6) -> None:
        self.min_conf = float(min_conf)
        self._engine = None
        self._tried = False

    @property
    def available(self) -> bool:
        if self._engine is not None:
            return True
        if self._tried:
            return False
        self._tried = True
        try:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
            return True
        except Exception as exc:
            log.warning("OCR unavailable: %s", exc)
            return False

    def _capture(self):
        try:
            import mss
            import numpy as np

            with mss.mss() as sct:
                return np.array(sct.grab(sct.monitors[1]))[:, :, :3]
        except Exception:
            return None

    def find_by_text(self, text: str, min_score: float = 70.0) -> list:
        if not text.strip() or not self.available:
            return []
        img = self._capture()
        if img is None:
            return []
        from core.text_utils import fold

        from .uia_finder import FoundElement, ratio

        query = fold(text)
        try:
            results, _ = self._engine(img)
        except Exception as exc:
            log.warning("OCR error: %s", exc)
            return []
        if not results:
            return []
        out = []
        for box, ocr_text, conf in results:
            if float(conf) < self.min_conf:
                continue
            if ratio(query, fold(ocr_text)) < min_score:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            bbox = (
                int(min(xs)),
                int(min(ys)),
                int(max(xs) - min(xs)),
                int(max(ys) - min(ys)),
            )
            if bbox[2] <= 0 or bbox[3] <= 0:
                continue
            digest = hashlib.sha1(str(bbox).encode()).hexdigest()[:12]
            out.append(
                FoundElement(
                    id=f"ocr:text:{digest}",
                    name="",
                    role="text",
                    bbox=bbox,
                    source="ocr",
                )
            )
        out.sort(key=lambda e: e.bbox[2] * e.bbox[3])
        return out[:3]
