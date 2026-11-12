# =====================================================================
# tests/test_gesture_click.py — giu 2 ban tay xoe 5s -> ActionEvent gaze_click
# =====================================================================
from __future__ import annotations

import numpy as np

from core.state_machine import StateMachine
from core.vision_engine import HandLandmarks, VisionFrame

WRIST = (0.5, 0.80)
MCP = {"index": (0.44, 0.60), "middle": (0.50, 0.58),
       "ring": (0.56, 0.60), "pinky": (0.61, 0.63)}
IDX = {"thumb": [1, 2, 3, 4], "index": [5, 6, 7, 8],
       "middle": [9, 10, 11, 12], "ring": [13, 14, 15, 16],
       "pinky": [17, 18, 19, 20]}


def make_open_palm(dx: float = 0.0) -> HandLandmarks:
    pts = np.zeros((21, 3), dtype=np.float32)
    pts[0] = (WRIST[0] + dx, WRIST[1], 0)
    for f in ("index", "middle", "ring", "pinky"):
        mx, my = MCP[f]
        i_mcp, i_pip, i_dip, i_tip = IDX[f]
        pts[i_mcp] = (mx + dx, my, 0)
        pts[i_pip] = (mx + dx, my - 0.08, 0)
        pts[i_dip] = (mx + dx, my - 0.13, 0)
        pts[i_tip] = (mx + dx, my - 0.18, 0)
    for i, p in zip(IDX["thumb"], [(0.42, 0.72), (0.38, 0.70),
                                   (0.32, 0.70), (0.26, 0.70)], strict=False):
        pts[i] = (p[0] + dx, p[1], 0)
    return HandLandmarks(points=pts, handedness="Right", score=0.99)


def frame(hands, ts: float) -> VisionFrame:
    return VisionFrame(timestamp=ts, hands=hands)


def cfg_for(base_config: dict) -> dict:
    c = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base_config.items()}
    c["state_machine"] = dict(base_config["state_machine"], stability_frames=2)
    c["gesture"] = dict(base_config["gesture"])
    c["gesture"]["gaze"] = dict(base_config["gesture"]["gaze"], enabled=False)
    return c


def names(events) -> list[str]:
    return [e.name for e in events]


def test_hold_both_open_hands_five_seconds_emits_gaze_click(base_config):
    sm = StateMachine(cfg_for(base_config))
    h1, h2 = make_open_palm(), make_open_palm(0.3)

    out = [sm.update(frame([h1, h2], i * 0.01)) for i in range(4)]
    assert "gaze_click" not in [n for ev in out for n in names(ev)]

    fired = sm.update(frame([h1, h2], 5.1))
    assert names(fired) == ["gaze_click"]

    # Giu tiep khong duoc lap lai trong cung mot lan giu.
    again = sm.update(frame([h1, h2], 6.0))
    assert "gaze_click" not in names(again)


def test_lowering_hands_before_five_seconds_cancels_click(base_config):
    sm = StateMachine(cfg_for(base_config))
    h1, h2 = make_open_palm(), make_open_palm(0.3)

    out = [sm.update(frame([h1, h2], i * 0.01)) for i in range(3)]
    out.append(sm.update(frame([], 4.0)))
    assert "gaze_click" not in [n for ev in out for n in names(ev)]

    # Gio lai -> bo dem phai tinh tu dau, khong duoc ke thua lan giu cu.
    out = [sm.update(frame([h1, h2], 4.1 + i * 0.01)) for i in range(3)]
    assert "gaze_click" not in [n for ev in out for n in names(ev)]

    assert "gaze_click" not in names(sm.update(frame([h1, h2], 8.0)))
    assert names(sm.update(frame([h1, h2], 9.5))) == ["gaze_click"]
