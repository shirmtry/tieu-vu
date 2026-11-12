# =====================================================================
# tests/test_integration_voice_click.py — NLU -> finder -> click, privacy
# =====================================================================
from __future__ import annotations

import copy

from core.finder.actions import click_found, telemetry_fields
from core.finder.uia_finder import FoundElement
from core.nlu import NLU


def _nlu(base_config):
    cfg = copy.deepcopy(base_config)
    cfg["nlu"]["coder"]["enabled"] = False
    return NLU(cfg)


class _Mouse:
    def __init__(self):
        self.moves = []
        self.clicks = 0

    def move_screen(self, x, y):
        self.moves.append((x, y))

    def left_click(self):
        self.clicks += 1


def test_nlu_click_intent(base_config):
    intents = _nlu(base_config).parse("bấm nút Đăng nhập")
    assert intents and intents[0].name == "click_target"
    assert intents[0].payload["target"] == "dang nhap"
    assert set(intents[0].payload) == {"target"}


def test_nlu_to_click():
    element = FoundElement("uia:button:abc", "Đăng nhập", "button",
                           (100, 50, 40, 20), "uia")
    mouse = _Mouse()
    click_found(element, mouse)
    assert mouse.moves == [(120, 60)]
    assert mouse.clicks == 1


def test_telemetry_has_no_element_name_or_ocr_text():
    uia_el = FoundElement("uia:button:abc", "Đăng nhập", "button",
                          (0, 0, 10, 10), "uia")
    ocr_el = FoundElement("ocr:text:def", "", "text", (0, 0, 10, 10), "ocr")
    for el in (uia_el, ocr_el):
        fields = telemetry_fields(el, 4.2)
        assert set(fields) == {"element_id", "role", "duration_ms"}
        assert "Đăng nhập" not in str(fields)
        assert "name" not in fields and "text" not in fields
