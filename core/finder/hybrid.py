"""Hybrid finder: UIA first (accurate), OCR fallback (bbox only)."""

from __future__ import annotations

from .uia_finder import FoundElement


class HybridFinder:
    def __init__(self, config: dict) -> None:
        from .ocr_finder import OcrFinder
        from .uia_finder import UiaFinder

        cfg = config.get("voice_click", {})
        uia = cfg.get("uia", {})
        ocr = cfg.get("ocr_fallback", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.uia = UiaFinder(
            max_depth=int(uia.get("max_depth", 10)),
            max_nodes=int(uia.get("max_nodes", 5000)),
        )
        self.ocr = OcrFinder(float(ocr.get("min_conf", 0.6)))
        self._uia_score = float(uia.get("min_score", 70))
        self._ocr_score = float(ocr.get("min_score", 70))
        self._ocr_enabled = bool(ocr.get("enabled", True))

    def find(self, target: str) -> list[FoundElement]:
        if not self.enabled or not target.strip():
            return []
        results = self.uia.find_by_name(target, self._uia_score)
        if results or not self._ocr_enabled:
            return results
        return self.ocr.find_by_text(target, self._ocr_score)
