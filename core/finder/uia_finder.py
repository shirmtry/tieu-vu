"""UIA (Windows Accessibility) finder — primary element finder.

Lazy-imports ``uiautomation``; missing dependency degrades to an empty result,
never crashes. Element names are only used in-memory for fuzzy matching.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger(__name__)

Role = Literal["button", "link", "edit", "menu_item", "tab", "text", "other"]

_ROLE_MAP = {
    "ButtonControl": "button",
    "HyperlinkControl": "link",
    "EditControl": "edit",
    "MenuItemControl": "menu_item",
    "TabItemControl": "tab",
    "TextControl": "text",
}


@dataclass
class FoundElement:
    id: str
    name: str
    role: Role
    bbox: tuple[int, int, int, int]
    source: Literal["uia", "ocr"] = "uia"


def ratio(a: str, b: str) -> float:
    """Fuzzy token score 0..100; falls back to difflib when rapidfuzz missing."""
    try:
        from rapidfuzz import fuzz

        return float(fuzz.token_sort_ratio(a, b))
    except ImportError:  # pragma: no cover - exercised only without rapidfuzz
        import difflib

        return difflib.SequenceMatcher(None, a, b).ratio() * 100.0


def _rect_bbox(rect) -> tuple[int, int, int, int] | None:
    try:
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width <= 0 or height <= 0:
            return None
        return int(rect.left), int(rect.top), width, height
    except Exception:
        return None


def _element_id(role: str, name: str, bbox: tuple[int, int, int, int]) -> str:
    digest = hashlib.sha1(f"{name}:{bbox}".encode()).hexdigest()[:12]
    return f"uia:{role}:{digest}"


class UiaFinder:
    def __init__(self, max_depth: int = 10, max_nodes: int = 5000) -> None:
        self.max_depth = int(max_depth)
        self.max_nodes = int(max_nodes)
        self._uia = None
        self._tried = False

    @property
    def available(self) -> bool:
        if self._uia is not None:
            return True
        if self._tried:
            return False
        self._tried = True
        try:
            import uiautomation

            self._uia = uiautomation
            return True
        except Exception as exc:
            log.warning("UIA unavailable: %s", exc)
            return False

    @staticmethod
    def _role_of(ctrl) -> Role:
        try:
            return _ROLE_MAP.get(ctrl.ControlTypeName, "other")  # type: ignore[arg-type]
        except Exception:
            return "other"

    def _to_element(self, ctrl) -> FoundElement | None:
        try:
            name = ctrl.Name or ""
            bbox = _rect_bbox(ctrl.BoundingRectangle)
            if bbox is None:
                return None
            role = self._role_of(ctrl)
            return FoundElement(
                id=_element_id(role, name, bbox),
                name=name,
                role=role,
                bbox=bbox,
                source="uia",
            )
        except Exception:
            return None

    def find_by_name(self, name: str, min_score: float = 70.0) -> list[FoundElement]:
        if not name.strip() or not self.available:
            return []
        from core.text_utils import fold

        query = fold(name)
        results: list[FoundElement] = []
        try:
            root = self._uia.GetRootControl()
            stack, seen = [(root, 0)], 0
            while stack and seen < self.max_nodes and len(results) < 5:
                node, depth = stack.pop()
                if depth > self.max_depth:
                    continue
                try:
                    children = node.GetChildren()
                except Exception:
                    continue
                for ctrl in children:
                    seen += 1
                    if seen >= self.max_nodes or len(results) >= 5:
                        break
                    stack.append((ctrl, depth + 1))
                    try:
                        ctrl_name = (ctrl.Name or "").strip()
                        if ctrl.IsOffscreen or not ctrl_name:
                            continue
                        if ratio(query, fold(ctrl_name)) < min_score:
                            continue
                        element = self._to_element(ctrl)
                        if element is not None:
                            results.append(element)
                    except Exception:
                        continue
        except Exception as exc:
            log.warning("UIA walk error: %s", exc)
        results.sort(key=lambda e: e.bbox[2] * e.bbox[3])
        return results[:5]

    def find_at_point(self, x: int, y: int) -> FoundElement | None:
        if not self.available:
            return None
        try:
            ctrl = self._uia.ControlFromPoint(int(x), int(y))
            return self._to_element(ctrl) if ctrl is not None else None
        except Exception:
            return None
