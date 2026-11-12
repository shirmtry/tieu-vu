# =====================================================================
# tests/test_state_logic.py — state machine + mode exclusivity
# =====================================================================
from __future__ import annotations

import time

import numpy as np
import pytest

from core.state_machine import Mode, State, StateMachine
from core.vision_engine import HandLandmarks, VisionFrame

WRIST = (0.5, 0.80)
MCP = {"index": (0.44, 0.60), "middle": (0.50, 0.58),
       "ring": (0.56, 0.60), "pinky": (0.61, 0.63)}
IDX = {"thumb": [1, 2, 3, 4], "index": [5, 6, 7, 8],
       "middle": [9, 10, 11, 12], "ring": [13, 14, 15, 16],
       "pinky": [17, 18, 19, 20]}


def make_hand(extended=("index",), thumb=False, pinch=None):
    pts = np.zeros((21, 3), dtype=np.float32)
    pts[0] = (*WRIST, 0)
    for f in ("index", "middle", "ring", "pinky"):
        mx, my = MCP[f]
        i_mcp, i_pip, i_dip, i_tip = IDX[f]
        pts[i_mcp] = (mx, my, 0)
        if f in extended:
            pts[i_pip] = (mx, my - 0.08, 0)
            pts[i_dip] = (mx, my - 0.13, 0)
            pts[i_tip] = (mx, my - 0.18, 0)
        else:
            pts[i_pip] = (mx, my - 0.05, 0)
            pts[i_dip] = (mx, my + 0.00, 0)
            pts[i_tip] = (mx + 0.01, my + 0.06, 0)
    if thumb:
        for i, p in zip(IDX["thumb"], [(0.42, 0.72), (0.38, 0.70),
                                       (0.32, 0.70), (0.26, 0.70)], strict=False):
            pts[i] = (*p, 0)
    else:
        for i, p in zip(IDX["thumb"], [(0.44, 0.72), (0.46, 0.68),
                                       (0.48, 0.66), (0.50, 0.64)], strict=False):
            pts[i] = (*p, 0)
    if pinch == "index":
        pts[4] = (0.42, 0.55, 0)
        pts[8] = (0.425, 0.555, 0)
    elif pinch == "middle":
        pts[4] = (0.48, 0.55, 0)
        pts[12] = (0.485, 0.555, 0)
    return HandLandmarks(points=pts, handedness="Right", score=0.99)


def frame(hands, ts=None):
    return VisionFrame(timestamp=ts if ts is not None else time.time(), hands=hands)


def names(events):
    return [e.name for e in events]


@pytest.fixture()
def cfg(base_config):
    c = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base_config.items()}
    c["state_machine"] = dict(base_config["state_machine"], stability_frames=2)
    c["gesture"] = dict(base_config["gesture"])
    c["gesture"]["gaze"] = dict(base_config["gesture"]["gaze"], enabled=False)
    return c


def run(sm, frames):
    return [sm.update(f) for f in frames]


def test_classification(cfg):
    sm = StateMachine(cfg)
    assert sm._classify_hand(make_hand(extended=("index",))).is_pointing
    assert sm._classify_hand(make_hand(extended=())).is_fist
    assert sm._classify_hand(make_hand(
        extended=("index", "middle", "ring", "pinky"), thumb=True)).is_open_palm
    assert sm._classify_hand(make_hand(
        extended=("index", "middle", "ring", "pinky"), thumb=False)).is_four_fingers
    assert sm._classify_hand(make_hand(extended=("index", "middle"))).is_v_sign
    assert sm._classify_hand(make_hand(extended=("index",), thumb=True)).is_l_sign
    assert sm._classify_hand(make_hand(pinch="index")).pinch_index
    assert sm._classify_hand(make_hand(pinch="middle")).pinch_middle


def test_alt_tab_single_fire(cfg):
    sm = StateMachine(cfg)
    h = make_hand(extended=("index", "middle", "ring", "pinky"), thumb=False)
    out = run(sm, [frame([h])] * 6)
    assert sum(names(ev).count("alt_tab") for ev in out) == 1
    assert sm.state == State.WINDOW_MGMT


def test_fist_close_tab(cfg):
    sm = StateMachine(cfg)
    out = run(sm, [frame([make_hand(extended=())])] * 6)
    assert sum(names(ev).count("close_tab") for ev in out) == 1


def test_l_play_pause(cfg):
    sm = StateMachine(cfg)
    h = make_hand(extended=("index",), thumb=True)
    out = run(sm, [frame([h])] * 6)
    assert sum(names(ev).count("play_pause") for ev in out) == 1
    assert sm.state == State.MEDIA


def test_mouse_move_and_click(cfg):
    sm = StateMachine(cfg)
    point = make_hand(extended=("index",))
    pinch = make_hand(pinch="index")
    out = run(sm, [frame([point])] * 3 + [frame([pinch])] * 2 + [frame([point])] * 3)
    alln = [n for ev in out for n in names(ev)]
    assert alln.count("mouse_move") >= 3
    assert "left_click" in alln
    assert "drag_start" not in alln


def test_drag_long_pinch(cfg):
    c = dict(cfg)
    c["state_machine"] = dict(cfg["state_machine"], drag_hold_sec=0.05)
    sm = StateMachine(c)
    point = make_hand(extended=("index",))
    pinch = make_hand(pinch="index")
    t0 = time.time()
    out = [sm.update(frame([point], t0))]
    out += [sm.update(frame([pinch], t0 + 0.2 + i * 0.02)) for i in range(8)]
    out.append(sm.update(frame([point], t0 + 0.5)))
    alln = [n for ev in out for n in names(ev)]
    assert "drag_start" in alln
    assert "drag_end" in alln


def test_two_hand_volume_excludes_mouse(cfg):
    sm = StateMachine(cfg)
    h1 = make_hand(extended=("index",))
    h2 = make_hand(extended=("index",))
    h2.points[:, 0] += 0.3
    out = run(sm, [frame([h1, h2])] * 5)
    alln = [n for ev in out for n in names(ev)]
    assert "volume" in alln
    assert "mouse_move" not in alln
    assert sm.state == State.VOLUME


def test_two_hand_copy_and_open_hold(cfg):
    sm = StateMachine(cfg)
    p1 = make_hand(pinch="index")
    p2 = make_hand(pinch="index")
    p2.points[:, 0] += 0.05
    alln = [n for ev in run(sm, [frame([p1, p2])] * 5) for n in names(ev)]
    assert "copy_plain" in alln

    sm = StateMachine(cfg)
    o1 = make_hand(extended=("index", "middle", "ring", "pinky"), thumb=True)
    o2 = make_hand(extended=("index", "middle", "ring", "pinky"), thumb=True)
    o2.points[:, 0] += 0.3
    alln = [n for ev in run(sm, [frame([o1, o2])] * 5) for n in names(ev)]
    # Xoe 2 tay khong con mo app; chi click sau khi giu du 5s (xem
    # tests/test_gesture_click.py).
    assert "open_app" not in alln
    assert "gaze_click" not in alln


def test_idle_when_no_hands(cfg):
    sm = StateMachine(cfg)
    run(sm, [frame([])] * 4)
    assert sm.state == State.IDLE


def test_mode_blocks_gestures(cfg):
    sm = StateMachine(cfg)
    sm.set_mode(Mode.FOCUS)
    out = sm.update(frame([make_hand(extended=("index", "middle", "ring", "pinky"))]))
    assert out == []
    assert Mode.FOCUS.accepts_gaze is False
    assert Mode.FOCUS.accepts_voice is False
    sm.set_mode(Mode.GAZE)
    assert sm.mode.accepts_gestures
    assert sm.mode.accepts_gaze
    assert not sm.mode.accepts_voice


def test_toggle_mode(cfg):
    sm = StateMachine(cfg)
    assert sm.mode is Mode.IDLE
    assert sm.toggle_mode(Mode.GAZE) is Mode.GAZE
    assert sm.toggle_mode(Mode.GAZE) is Mode.IDLE
