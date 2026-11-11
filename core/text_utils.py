# =====================================================================
# core/text_utils.py
# Tien ich xu ly van ban tieng Viet dung chung cho NLU / voice / snippet:
# bo dau, gop am cuoi hay nghe nham, chuan hoa khoang trang.
# =====================================================================
from __future__ import annotations

import re
import unicodedata
from typing import List

_WORD_END_FOLDS = (("nh", "m"), ("ng", "n"), ("ch", "t"), ("c", "t"), ("p", "t"))


def normalize(text: str) -> str:
    """Lowercase, bo dau tieng Viet, bo dau cau, gop khoang trang.

    Vi du: "Tìm kiếm!" -> "tim kiem".
    """
    text = text.lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fold(text: str) -> str:
    """Gop phu am cuoi hay nghe nham (giong bac) de cham diem mo.

    "tính" -> "tim" (khop "tìm"), "vang" -> "van". Chi dung khi so khop;
    payload tra ve giu nguyen van ban goc.
    """
    out: List[str] = []
    for word in normalize(text).split():
        for src, dst in _WORD_END_FOLDS:
            if word.endswith(src):
                word = word[: -len(src)] + dst
                break
        out.append(word)
    return " ".join(out)


def strip_accents(text: str) -> str:
    """Bo dau nhung giu nguyen dau cau / hoa thuong."""
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if not unicodedata.combining(c))
