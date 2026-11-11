# =====================================================================
# core/autocomplete.py
# Goi y tu hoan thanh: n-gram cuc bo (khong can GPU/mang) + LLM tuy chon.
# HUD hien 3 goi y; Tab chap nhan goi y dau tien.
# =====================================================================
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[\wÀ-ỹ]+|[^\w\s]", re.UNICODE)


def tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


class NgramModel:
    """Mo hinh n-gram don gian: dem next-token theo 1..n token truoc."""

    def __init__(self, order: int = 2):
        self.order = max(1, int(order))
        self._counts: Dict[Tuple[str, ...], Counter] = defaultdict(Counter)
        self._vocab: Counter = Counter()

    def train(self, corpus: Iterable[str]):
        for line in corpus:
            tokens = ["<s>"] * self.order + tokenize(line) + ["</s>"]
            for i, tok in enumerate(tokens):
                if tok in ("<s>", "</s>"):
                    continue
                self._vocab[tok] += 1
                for k in range(1, self.order + 1):
                    if i - k < 0:
                        continue
                    ctx = tuple(tokens[i - k:i])
                    self._counts[ctx][tok] += 1

    def suggest(self, prefix: str, k: int = 3) -> List[str]:
        """Goi y token tiep theo; uu tien ngu canh dai, roi den vocabulary."""
        tokens = tokenize(prefix)
        last_word = ""
        m = re.search(r"([\wÀ-ỹ]*)$", prefix)
        if m:
            last_word = m.group(1).lower()

        # Dung toan bo token lam ngu canh; last_word chi dung de loc
        # prefix (uu tien tu hoan thanh tu dang go do).
        ctx_tokens = tokens

        scores: Counter = Counter()
        for size in range(min(self.order, len(ctx_tokens)), 0, -1):
            ctx = tuple(ctx_tokens[-size:])
            counts = self._counts.get(ctx)
            if not counts:
                continue
            weight = 10 ** (size - 1)
            for tok, cnt in counts.items():
                if tok in ("</s>",):
                    continue
                scores[tok] += cnt * weight
        for tok, cnt in self._vocab.items():
            if last_word and tok.startswith(last_word) and tok != last_word:
                scores[tok] += cnt * 0.1
        candidates = [tok for tok, _ in scores.most_common(k * 4)]
        if last_word:
            matched = [t for t in candidates if t.startswith(last_word)]
            candidates = matched or candidates
        return candidates[:k]


class AutocompleteEngine:
    """Boc NgramModel + LLM fallback (neu duoc bat)."""

    def __init__(self, config: dict, corpus: Optional[Iterable[str]] = None):
        cfg = config.get("autocomplete", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.k = int(cfg.get("max_suggestions", 3))
        self.model = NgramModel(order=int(cfg.get("ngram_order", 2)))
        base = [
            "tìm kiếm thời tiết hôm nay",
            "mở youtube và phát nhạc",
            "gửi email cho khách hàng",
            "tạo báo cáo doanh thu tháng này",
            "ủng hộ tiểu vũ",
            "cảm ơn bạn đã ủng hộ tiểu vũ",
            "lịch họp ngày mai lúc 9 giờ",
            "download model onnx runtime",
        ]
        self.model.train(list(corpus or []) + base)

    def suggest(self, text: str) -> List[str]:
        if not self.enabled or not text.strip():
            return []
        return self.model.suggest(text, self.k)
