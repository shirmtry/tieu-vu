# =====================================================================
# core/nlu.py
# Hieu lenh tu nhien: rule-based tu config.yaml, fallback LLM nho
# (Qwen2.5-0.5B GGUF qua llama-cpp-python) neu bat va san sang.
# Rule-based luon chay truoc de do tre < 1ms cho lenh pho bien.
# =====================================================================
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .text_utils import fold, normalize

log = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz

    def _sim(a: str, b: str) -> float:
        return float(fuzz.ratio(a, b))
except ImportError:  # pragma: no cover
    import difflib

    def _sim(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio() * 100.0


@dataclass
class Intent:
    name: str                      # ten ActionEvent, vd "donate_window"
    payload: dict = field(default_factory=dict)
    confidence: float = 0.0
    source: str = "rule"           # "rule" | "llm"
    # Cau phan hoi TTS (neu co) -> NLU sinh them Intent("speak").
    response: str = ""


# Rule mac dinh khi config khong khai bao. "slot": "rest" -> phan con lai
# cua cau duoc dua vao payload[slot_key].
DEFAULT_RULES = [
    {"name": "donate_window", "patterns": [
        "mở donate", "mo donate", "ủng hộ tiểu vũ", "ung ho tieu vu",
        "ủng hộ", "donate", "quyên góp"], "confidence": 0.98},
    {"name": "wake_toggle", "patterns": [
        "bật tiểu vũ", "tắt tiểu vũ", "dừng tiểu vũ"], "confidence": 0.95},
    {"name": "open_url", "patterns": ["mở youtube", "open youtube"],
     "payload": {"url": "https://www.youtube.com"},
     "response": "Đã mở YouTube.", "confidence": 0.9},
    {"name": "open_url", "patterns": ["mở google", "open google"],
     "payload": {"url": "https://www.google.com"},
     "response": "Đã mở Google.", "confidence": 0.9},
    {"name": "open_url", "patterns": ["mở github", "open github"],
     "payload": {"url": "https://github.com"},
     "response": "Đã mở GitHub.", "confidence": 0.9},
    {"name": "search", "patterns": ["tìm kiếm", "tìm giúp", "tra cứu", "search"],
     "slot": "rest", "slot_key": "query", "confidence": 0.85},
    {"name": "type_text", "patterns": ["gõ", "nhập", "viết", "type"],
     "slot": "rest", "slot_key": "text", "confidence": 0.85},
    {"name": "click", "patterns": ["bấm chuột", "click", "nhấp"],
     "confidence": 0.9},
    {"name": "scroll", "patterns": ["cuộn lên", "cuộn xuống", "scroll up",
                                    "scroll down"], "confidence": 0.9},
]


class RuleEngine:
    """So khop mo (fuzzy) tren cau da bo dau / gop am."""

    def __init__(self, rules: Optional[List[dict]] = None, threshold: float = 80.0):
        self.rules = rules or DEFAULT_RULES
        self.threshold = float(threshold)
        self._compiled = []
        for rule in self.rules:
            pats = [fold(p) for p in rule.get("patterns", [])]
            self._compiled.append((rule, pats))

    def parse(self, text: str) -> Optional[Intent]:
        norm = fold(text)
        if not norm:
            return None
        best: Optional[Intent] = None
        best_score = 0.0
        for rule, patterns in self._compiled:
            for pat in patterns:
                score = 100.0 if norm == pat else 0.0
                if norm.startswith(pat + " "):
                    score = max(score, 95.0)
                score = max(score, _sim(pat, norm))
                if score < self.threshold or score <= best_score:
                    continue
                payload = dict(rule.get("payload", {}))
                if rule.get("slot") == "rest":
                    normalized_words = normalize(text).split()
                    pat_words = pat.split()
                    rest = " ".join(normalized_words[len(pat_words):]).strip()
                    payload[rule.get("slot_key", "text")] = rest
                    if not rest:
                        continue
                best = Intent(
                    name=str(rule["name"]),
                    payload=payload,
                    confidence=score / 100.0,
                    source="rule",
                    response=str(rule.get("response", "")),
                )
                best_score = score
        return best


class LLMFallback:
    """Qwen2.5-0.5B GGUF qua llama-cpp-python (tuy chon, lazy load)."""

    def __init__(self, model_path: str, n_ctx: int = 512):
        self.model_path = model_path
        self.n_ctx = int(n_ctx)
        self._llm = None
        self._tried = False

    @property
    def available(self) -> bool:
        if self._llm is not None:
            return True
        if self._tried:
            return False
        self._tried = True
        try:
            from llama_cpp import Llama

            self._llm = Llama(model_path=self.model_path, n_ctx=self.n_ctx,
                              verbose=False)
            log.info("NLU LLM fallback san sang: %s", self.model_path)
            return True
        except Exception as exc:
            log.info("LLM fallback khong kha dung (%s).", exc)
            return False

    def parse(self, text: str) -> Optional[Intent]:
        if not self.available or self._llm is None:
            return None
        prompt = (
            "Ban la bo phan tich lenh cho tro ly may tinh Tiểu Vũ.\n"
            "Tra ve DUY NHAT mot JSON: {\"action\": <ten>, \"payload\": {...}}.\n"
            "Cac action hop le: donate_window, search, type_text, open_url, "
            "click, scroll.\n"
            f"Cau lenh: {text}\nJSON:"
        )
        try:
            out = self._llm(prompt, max_tokens=96, temperature=0.0)
            raw = out["choices"][0]["text"].strip()
            match = re.search(r"\{.*\}", raw, re.S)
            if not match:
                return None
            data = json.loads(match.group(0))
            action = str(data.get("action", "")).strip()
            if not action:
                return None
            return Intent(action, dict(data.get("payload") or {}), 0.6, "llm")
        except Exception as exc:
            log.debug("LLM parse loi: %s", exc)
            return None


class NLU:
    """Pipeline: rule-based -> LLM fallback (neu bat)."""

    def __init__(self, config: dict):
        cfg = config.get("nlu", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.rules = RuleEngine(cfg.get("rules") or DEFAULT_RULES,
                                float(cfg.get("fuzzy_threshold", 80)))
        self.llm: Optional[LLMFallback] = None
        if cfg.get("llm_fallback", False):
            self.llm = LLMFallback(str(cfg.get("llm_model",
                                               "models/qwen2.5-0.5b-instruct-q4_k_m.gguf")))
        # CoderNLU (Ollama) chen giua rule-based va LLM nho.
        self.coder = None
        if (cfg.get("coder", {}) or {}).get("enabled", False):
            try:
                from .nlu_coder import CoderNLU

                self.coder = CoderNLU(config)
            except Exception as exc:
                log.warning("Khong khoi tao duoc CoderNLU (%s).", exc)

    def parse(self, text: str) -> List[Intent]:
        if not self.enabled:
            return []
        intent = self.rules.parse(text)
        if intent is not None:
            if intent.response:
                # Thuc thi hanh dong truoc, sau do TTS tra loi.
                return [intent, Intent("speak", {"text": intent.response},
                                       intent.confidence, "rule")]
            return [intent]
        if self.coder is not None:
            event = self.coder.parse(text)
            if event is not None:
                return [Intent(event.name, dict(event.payload), 0.9, "coder")]
        if self.llm is not None:
            intent = self.llm.parse(text)
            if intent is not None:
                return [intent]
        return []
