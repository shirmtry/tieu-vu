# =====================================================================
# tests/test_finder_uia.py — UIA finder (uiautomation fully mocked)
# =====================================================================
from __future__ import annotations

import sys
import types

from core.finder.uia_finder import UiaFinder


class _Rect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top = left, top
        self.right, self.bottom = right, bottom


class _Ctrl:
    def __init__(self, name, role="ButtonControl", bbox=(10, 20, 80, 30),
                 offscreen=False, children=()):
        self.Name = name
        self.ControlTypeName = role
        self.IsOffscreen = offscreen
        left, top, width, height = bbox
        self.BoundingRectangle = _Rect(left, top, left + width, top + height)
        self._children = list(children)

    def GetChildren(self):
        return self._children


def _install(monkeypatch, root, point=None):
    mod = types.ModuleType("uiautomation")
    mod.GetRootControl = lambda: root
    mod.ControlFromPoint = lambda x, y: point
    monkeypatch.setitem(sys.modules, "uiautomation", mod)


def test_find_by_name_fuzzy(monkeypatch):
    root = _Ctrl("Desktop", children=[_Ctrl("Đăng nhập"), _Ctrl("Hủy")])
    _install(monkeypatch, root)
    results = UiaFinder().find_by_name("dang nhap")
    assert [e.name for e in results] == ["Đăng nhập"]
    assert results[0].role == "button"
    assert results[0].bbox == (10, 20, 80, 30)
    assert results[0].source == "uia"
    assert results[0].id.startswith("uia:button:")


def test_min_score_filters(monkeypatch):
    root = _Ctrl("Desktop", children=[_Ctrl("Đăng xuất")])
    _install(monkeypatch, root)
    assert UiaFinder().find_by_name("Đăng nhập", min_score=99) == []


def test_offscreen_skipped(monkeypatch):
    root = _Ctrl("Desktop", children=[_Ctrl("Đăng nhập", offscreen=True)])
    _install(monkeypatch, root)
    assert UiaFinder().find_by_name("dang nhap") == []


def test_find_at_point(monkeypatch):
    point = _Ctrl("OK", role="ButtonControl", bbox=(100, 200, 40, 20))
    _install(monkeypatch, _Ctrl("Desktop"), point=point)
    element = UiaFinder().find_at_point(110, 210)
    assert element is not None
    assert element.name == "OK"
    assert element.bbox == (100, 200, 40, 20)


def test_unavailable_returns_empty():
    finder = UiaFinder()
    finder._tried = True  # gia lap import uiautomation that bai
    assert finder.available is False
    assert finder.find_by_name("login") == []
    assert finder.find_at_point(1, 1) is None
