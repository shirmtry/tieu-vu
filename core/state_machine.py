# =====================================================================
# core/state_machine.py
# "Bo nao" cua he thong. Nhan VisionFrame, phan loai cu chi, chong nhieu
# (stability), chong double-trigger (cooldown), va giai quyet XUNG DOT CU
# CHI bang trong tai uu tien (priority arbitration).
#
# Triet ly chong xung dot:
#   - Moi frame chi MOT "kenh" thang cuoc: TWO_HAND_SYSTEM > FACE_SCROLL >
#     ONE_HAND_MOUSE. Hai tay dang lam viec he thong thi mat va chuot khong
#     duoc kich hoat dong thoi.
#   - Cu chi离散 (discrete) chi phat mot lan tai "rising edge" sau khi da
#     on dinh du N frame, roi nghi theo cooldown.
#   - Cu chi lien tuc (mouse_move, volume) duoc throttle bang cooldown ngan.
# =====================================================================
from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from .vision_engine import (
    INDEX_PIP,
    INDEX_TIP,
    LEFT_EYE_BOTTOM,
    LEFT_EYE_TOP,
    LEFT_IRIS,
    MIDDLE_PIP,
    MIDDLE_TIP,
    PINKY_MCP,
    PINKY_PIP,
    PINKY_TIP,
    RIGHT_EYE_BOTTOM,
    RIGHT_EYE_TOP,
    RIGHT_IRIS,
    RING_PIP,
    RING_TIP,
    THUMB_IP,
    THUMB_TIP,
    WRIST,
    HandLandmarks,
    VisionFrame,
    dist2d,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Trang thai cua he thong
# ---------------------------------------------------------------------
class State(Enum):
    IDLE = "IDLE"
    MOUSE = "MOUSE"
    VOLUME = "VOLUME"
    WINDOW_MGMT = "WINDOW_MGMT"
    TEXT_EDIT = "TEXT_EDIT"
    MEDIA = "MEDIA"


# ---------------------------------------------------------------------
# Che do dieu khien: chi MOT che do nhan input tai mot thoi diem.
#   IDLE  - chi hotkey (khong chan gesture, tuong thich nguoc)
#   GAZE  - gaze + gesture chuot
#   VOICE - micro (gesture bi khoa)
#   VK    - ban phim ao (gesture/micro bi khoa)
#   FOCUS - khoa toan bo input AI (chi hotkey)
#   CODE  - micro -> CoderNLU (gesture bi khoa, mode duoc giu khi noi)
#   VOICE_CLICK - micro -> tim & bam element (gesture khoa, gaze highlight)
# ---------------------------------------------------------------------
class Mode(Enum):
    IDLE = "IDLE"
    GAZE = "GAZE"
    VOICE = "VOICE"
    VK = "VK"
    FOCUS = "FOCUS"
    CODE = "code"
    VOICE_CLICK = "VOICE_CLICK"

    @property
    def accepts_gestures(self) -> bool:
        return self in (Mode.IDLE, Mode.GAZE)

    @property
    def accepts_gaze(self) -> bool:
        return self in (Mode.GAZE, Mode.VOICE_CLICK)

    @property
    def accepts_voice(self) -> bool:
        return self in (Mode.VOICE, Mode.CODE, Mode.VOICE_CLICK)


def wake_transition(mode: Mode) -> Optional[Mode]:
    """Mode dich khi wake word kich hoat; None = khong doi mode.

    VK/FOCUS khoa micro (wake bi tu choi), VOICE/CODE/VOICE_CLICK da san sang
    nhan lenh nen giu nguyen. Cac mode khac tam chuyen sang VOICE.
    """
    if mode in (Mode.VK, Mode.FOCUS):
        return None
    if mode in (Mode.VOICE, Mode.CODE, Mode.VOICE_CLICK):
        return None
    return Mode.VOICE


def done_transition(mode: Mode, prev_mode: Mode) -> Optional[Mode]:
    """Mode khoi phuc sau khi nghe xong lenh; None = giu nguyen.

    CODE duoc giu lai (khong tu thoat) cho den khi user toggle hotkey.
    """
    if mode is not Mode.VOICE:
        return None
    return prev_mode if prev_mode not in (Mode.VOICE, Mode.VK) else Mode.GAZE



# ---------------------------------------------------------------------
# Su kien hanh dong gui den Action Dispatcher (main.py)
# ---------------------------------------------------------------------
@dataclass
class ActionEvent:
    name: str                          # ten hanh dong, vd "left_click"
    payload: dict = field(default_factory=dict)
    source: str = "gesture"            # "gesture" | "voice" | "web"
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------
# Ket qua phan loai cu chi cua mot ban tay
# ---------------------------------------------------------------------
@dataclass
class HandGesture:
    hand: HandLandmarks
    extended: Dict[str, bool] = field(default_factory=dict)
    num_extended: int = 0              # khong tinh ngon cai
    pinch_index: bool = False
    pinch_middle: bool = False
    pinch_index_ratio: float = 1.0
    is_fist: bool = False
    is_open_palm: bool = False
    is_pointing: bool = False
    is_v_sign: bool = False
    is_l_sign: bool = False
    is_four_fingers: bool = False
    is_three_fingers: bool = False     # tro + giua + ap ut -> xu ly AI clipboard


# =====================================================================
# Cac bo tro: Stability (chong nhieu) va Cooldown (chong lap)
# =====================================================================
class StabilityTracker:
    """Dem so frame lien tiep mot cu chi xuat hien.

    Mot cu chi chi duoc coi la 'on dinh' khi xuat hien >= required frame
    lien tiep, giup loai bo nhieu / nhan dien nham trong vai frame.
    """

    def __init__(self, required_frames: int):
        self.required = max(1, int(required_frames))
        self._counts: Dict[str, int] = {}

    def update(self, key: str, active: bool):
        self._counts[key] = self._counts.get(key, 0) + 1 if active else 0

    def is_stable(self, key: str) -> bool:
        return self._counts.get(key, 0) >= self.required

    def count(self, key: str) -> int:
        return self._counts.get(key, 0)

    def reset(self, key: str):
        self._counts[key] = 0


class CooldownGate:
    """Dam bao moi hanh dong cach nhau it nhat cooldown giay."""

    def __init__(self, default_sec: float, overrides: Dict[str, float]):
        self.default = float(default_sec)
        self.overrides = {k: float(v) for k, v in (overrides or {}).items()}
        self._last: Dict[str, float] = {}

    def allow(self, action: str, now: float) -> bool:
        cd = self.overrides.get(action, self.default)
        if now - self._last.get(action, -1e9) >= cd:
            self._last[action] = now
            return True
        return False


class SwipeDetector:
    """Phat hien vuot tay trai/phai dua tren van toc co tay.

    Giua mot cua so thoi gian, neu do dich chuyen ngang du lon va du nhanh
    thi ket luan la swipe. Dung cho Undo/Redo (1 tay) va chuyen desktop (2 tay).
    """

    def __init__(self, min_disp: float, max_dur: float, min_vel: float):
        self.min_disp = float(min_disp)
        self.max_dur = float(max_dur)
        self.min_vel = float(min_vel)
        self._hist: Deque[Tuple[float, float]] = deque()
        self._last_fire = 0.0

    def update(self, now: float, x: float) -> Optional[str]:
        self._hist.append((now, x))
        # Loai bo cac diem qua cu.
        while self._hist and now - self._hist[0][0] > self.max_dur:
            self._hist.popleft()
        if len(self._hist) < 3:
            return None
        t0, x0 = self._hist[0]
        dt = now - t0
        if dt <= 1e-3:
            return None
        dx = x - x0
        vel = abs(dx) / dt
        if abs(dx) >= self.min_disp and vel >= self.min_vel:
            # Chong lap: moi swipe cach nhau it nhat max_dur.
            if now - self._last_fire >= self.max_dur:
                self._last_fire = now
                self._hist.clear()
                return "right" if dx > 0 else "left"
        return None

    def reset(self):
        self._hist.clear()


# =====================================================================
# Bo may trang thai
# =====================================================================
class StateMachine:
    def __init__(self, config: dict):
        self.cfg = config
        sm = config.get("state_machine", {})
        g = config.get("gesture", {})

        self.state = State[sm.get("initial_state", "IDLE")]
        self.mode = Mode[sm.get("initial_mode", "IDLE")]
        self.stability = StabilityTracker(sm.get("stability_frames", 4))
        self.cooldown = CooldownGate(
            sm.get("default_cooldown_sec", 0.5),
            sm.get("cooldowns", {}),
        )
        self.drag_hold_sec = float(sm.get("drag_hold_sec", 1.0))
        # Giu 2 ban tay xoe (5 ngon) du lau -> click tai diem mat dang nhin.
        self.two_hand_click_hold = float(sm.get("two_hand_click_hold_sec", 5.0))
        self.priority = sm.get("priority",
                               ["TWO_HAND_SYSTEM", "FACE_SCROLL", "ONE_HAND_MOUSE"])

        # Nguong cu chi.
        self.pinch_th = float(g.get("pinch_threshold", 0.35))
        self.pinch_mid_th = float(g.get("pinch_middle_threshold", 0.40))
        self.pinch_min_reach = float(g.get("pinch_min_reach", 0.9))
        self.finger_ratio = float(g.get("finger_extend_ratio", 1.15))
        self.alt_tab_count = int(g.get("alt_tab_finger_count", 4))
        # Cu chi 3 ngon tay (tro+giua+ap ut) -> xu ly clipboard bang AI.
        self.ai_gesture_enabled = bool(g.get("ai_gesture", {}).get("enabled", True))
        gaze = g.get("gaze", {})
        self.gaze_enabled = bool(gaze.get("enabled", True))
        self.gaze_up = float(gaze.get("up_threshold", 0.30))
        self.gaze_down = float(gaze.get("down_threshold", 0.70))
        self.gaze_hold = float(gaze.get("hold_sec", 1.0))
        self.v_scroll_sens = float(g.get("v_scroll_sensitivity", 3.0))
        vol = g.get("volume", {})
        self.vol_min = float(vol.get("min_dist", 0.10))
        self.vol_max = float(vol.get("max_dist", 0.80))
        sw = g.get("swipe", {})
        self.swipe_cfg = (sw.get("min_displacement", 0.20),
                          sw.get("max_duration_sec", 0.6),
                          sw.get("min_velocity", 0.6))

        # Trang thai noi bo.
        self._stable_prev: set = set()          # cac cu chi da on dinh frame truoc
        self._pinch_active = False
        self._pinch_start = 0.0
        self._dragging = False
        self._mouse_active = False       # co dang o kenh chuot frame nay khong
        self._gaze_dir: Optional[str] = None
        self._gaze_start = 0.0
        self._v_scroll_last_y: Optional[float] = None
        self._swipe_one = SwipeDetector(*self.swipe_cfg)
        self._swipe_two = SwipeDetector(*self.swipe_cfg)
        self._two_open_since: Optional[float] = None
        self._two_open_fired = False
        self.last_action: str = ""              # phuc vu HUD

    # ------------------------------------------------------------------
    # Phan loai cu chi mot ban tay
    # ------------------------------------------------------------------
    def _classify_hand(self, hand: HandLandmarks) -> HandGesture:
        p = hand.points
        palm = hand.palm_size

        def extended(tip: int, pip: int) -> bool:
            # Ngon tay duoi khi dau ngon xa co tay hon khop PIP.
            return dist2d(p[tip], p[WRIST]) > dist2d(p[pip], p[WRIST]) * self.finger_ratio

        ext = {
            "index": extended(INDEX_TIP, INDEX_PIP),
            "middle": extended(MIDDLE_TIP, MIDDLE_PIP),
            "ring": extended(RING_TIP, RING_PIP),
            "pinky": extended(PINKY_TIP, PINKY_PIP),
            # Ngon cai: dau ngon xa MCP ngon ut hon khop IP (dang giang ra).
            "thumb": dist2d(p[THUMB_TIP], p[PINKY_MCP]) >
                     dist2d(p[THUMB_IP], p[PINKY_MCP]) * self.finger_ratio,
        }
        num = sum(ext[f] for f in ("index", "middle", "ring", "pinky"))

        d_index = dist2d(p[THUMB_TIP], p[INDEX_TIP]) / palm
        d_middle = dist2d(p[THUMB_TIP], p[MIDDLE_TIP]) / palm
        # "Reach": diem chum phai nam xa co tay (ngon tay vuon ra ngoai).
        # Cac ngon gap trong long ban tay (fist/pointing) co tip gan nhau va
        # gan co tay -> reach thap -> khong phai pinch that. Day la key
        # chong nhan dien nham click/right-click khi tay dang nam/gap.
        reach_i = dist2d((p[THUMB_TIP] + p[INDEX_TIP]) / 2.0, p[WRIST]) / palm
        reach_m = dist2d((p[THUMB_TIP] + p[MIDDLE_TIP]) / 2.0, p[WRIST]) / palm
        pinch_index = d_index < self.pinch_th and reach_i > self.pinch_min_reach
        pinch_middle = d_middle < self.pinch_mid_th and reach_m > self.pinch_min_reach

        folded_all = not any(ext[f] for f in ("index", "middle", "ring", "pinky"))
        # Fist that su khong chua pinch (pinch uu tien hon fist).
        is_fist = folded_all and not pinch_index and not pinch_middle
        is_open_palm = num >= 4 and ext["thumb"]
        is_four = (num >= self.alt_tab_count and not ext["thumb"])
        is_v = (ext["index"] and ext["middle"] and
                not ext["ring"] and not ext["pinky"])
        is_pointing = ext["index"] and not ext["middle"] and not ext["ring"] and not ext["pinky"]
        # 3 ngon: tro + giua + ap ut duoi, ut + cai gap (khac V/4 ngon/open).
        is_three = (ext["index"] and ext["middle"] and ext["ring"]
                    and not ext["pinky"] and not ext["thumb"])

        # Chu L: cai + tro duoi, 3 ngon con lai gap, khong pinch, goc ~90 do.
        is_l = False
        if ext["thumb"] and ext["index"] and not ext["middle"] and \
                not ext["ring"] and not ext["pinky"] and not pinch_index:
            v_thumb = p[THUMB_TIP] - p[WRIST]
            v_index = p[INDEX_TIP] - p[WRIST]
            n_t, n_i = np.linalg.norm(v_thumb[:2]), np.linalg.norm(v_index[:2])
            if n_t > 1e-6 and n_i > 1e-6:
                cos = float(np.dot(v_thumb[:2], v_index[:2]) / (n_t * n_i))
                ang = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
                is_l = 55.0 <= ang <= 125.0

        return HandGesture(
            hand=hand, extended=ext, num_extended=num,
            pinch_index=pinch_index, pinch_middle=pinch_middle,
            pinch_index_ratio=d_index,
            is_fist=is_fist, is_open_palm=is_open_palm, is_pointing=is_pointing,
            is_v_sign=is_v, is_l_sign=is_l, is_four_fingers=is_four,
            is_three_fingers=is_three,
        )

    # ------------------------------------------------------------------
    # Gaze: huong nhin tu vi tri iris trong hooc mat
    # ------------------------------------------------------------------
    def _gaze_direction(self, frame: VisionFrame) -> Optional[str]:
        if not self.gaze_enabled or frame.face is None or not frame.face.has_iris:
            return None
        f = frame.face

        def ratio(iris: int, top: int, bottom: int) -> float:
            h = f.pt(bottom)[1] - f.pt(top)[1]
            if abs(h) < 1e-6:
                return 0.5
            return float((f.pt(iris)[1] - f.pt(top)[1]) / h)

        r = (ratio(LEFT_IRIS, LEFT_EYE_TOP, LEFT_EYE_BOTTOM) +
             ratio(RIGHT_IRIS, RIGHT_EYE_TOP, RIGHT_EYE_BOTTOM)) / 2.0
        if r < self.gaze_up:
            return "up"
        if r > self.gaze_down:
            return "down"
        return None

    # ------------------------------------------------------------------
    # Che do dieu khien (chi mot mode nhan input tai mot thoi diem)
    # ------------------------------------------------------------------
    def set_mode(self, mode: "Mode | str") -> Mode:
        new_mode = mode if isinstance(mode, Mode) else Mode[str(mode).upper()]
        if new_mode is not self.mode:
            log.info("Che do: %s -> %s", self.mode.value, new_mode.value)
        self.mode = new_mode
        self._two_open_since = None
        self._two_open_fired = False
        if not new_mode.accepts_gestures:
            # Nha moi trang thai lien tuc de khong ket chuot khi doi mode.
            self._pinch_active = False
            self._dragging = False
            self._reset_continuous()
            self.stability = StabilityTracker(self.stability.required)
            self._stable_prev.clear()
        return self.mode

    def toggle_mode(self, mode: "Mode | str") -> Mode:
        target = mode if isinstance(mode, Mode) else Mode[str(mode).upper()]
        return self.set_mode(Mode.IDLE if self.mode is target else target)

    # ------------------------------------------------------------------
    # Vong lap xu ly chinh: tra ve danh sach ActionEvent
    # ------------------------------------------------------------------
    def update(self, frame: VisionFrame) -> List[ActionEvent]:
        if not self.mode.accepts_gestures:
            # VOICE / VK / FOCUS: gesture khong duoc phep chen ngang.
            self._reset_continuous()
            return []
        now = frame.timestamp
        events: List[ActionEvent] = []
        self._mouse_active = False
        hands = [self._classify_hand(h) for h in frame.hands]
        n = len(hands)
        if n < 2:
            # Mat 1 tay -> huy bo dem giu 2 tay, phai giu lai tu dau.
            self._two_open_since = None
            self._two_open_fired = False

        # Cap nhat stability cho tat ca cu chi ung vien, tinh rising edge
        # tap trung de tranh trang thai cu khi mot kenh khong duoc danh gia.
        self._update_stability(hands, frame, now)
        self._detect_rising_edges()

        # Trong tai: chon kenh thang cuoc theo thu tu uu tien.
        for channel in self.priority:
            if channel == "TWO_HAND_SYSTEM" and n >= 2:
                ev = self._two_hand_system(hands, frame, now)
                if ev is not None:
                    events.extend(ev)
                    return self._finalize(events)
            elif channel == "FACE_SCROLL":
                ev = self._face_scroll(frame, now)
                if ev is not None:
                    events.extend(ev)
                    # Face scroll khong nhat thiet chan chuot, nhung uu tien
                    # cao hon -> return de tranh xung dot.
                    return self._finalize(events)
            elif channel == "ONE_HAND_MOUSE" and n == 1:
                ev = self._one_hand(hands[0], frame, now)
                events.extend(ev)
                return self._finalize(events)

        # Khong kenh nao kich hoat -> IDLE.
        self._transition(State.IDLE)
        self._reset_continuous()
        return self._finalize(events)

    # ------------------------------------------------------------------
    # Cap nhat bo dem stability cho cac cu chi
    # ------------------------------------------------------------------
    def _update_stability(self, hands: List[HandGesture], frame: VisionFrame, now: float):
        s = self.stability
        if len(hands) >= 2:
            h1, h2 = hands[0], hands[1]
            both_point = h1.is_pointing and h2.is_pointing
            both_open = h1.is_open_palm and h2.is_open_palm
            both_pinch = h1.pinch_index and h2.pinch_index
            tips_close = dist2d(h1.hand.pt(INDEX_TIP), h2.hand.pt(INDEX_TIP)) < 0.18
            s.update("two_volume", both_point)
            s.update("two_open", both_open)
            s.update("two_copy", both_pinch and tips_close)
        else:
            s.update("two_volume", False)
            s.update("two_open", False)
            s.update("two_copy", False)

        if len(hands) == 1:
            h = hands[0]
            s.update("alt_tab", h.is_four_fingers)
            s.update("close_tab", h.is_fist)
            s.update("play_pause", h.is_l_sign)
            s.update("right_click", h.pinch_middle)
            s.update("process_email", h.is_three_fingers and self.ai_gesture_enabled)
        else:
            for k in ("alt_tab", "close_tab", "play_pause", "right_click", "process_email"):
                s.update(k, False)

    # Tat ca key cu chi discrete can theo doi rising edge.
    _EDGE_KEYS = ("two_open", "two_copy", "alt_tab", "close_tab",
                  "play_pause", "right_click", "process_email")

    def _detect_rising_edges(self):
        """Tinh tap hop cu chi vua dat nguong on dinh trong frame nay.

        Lam tap trung cho moi key, ke ca khi nhanh xu ly tuong ung khong
        duoc goi (return som), nho do khong bi sot canh hay trang thai cu.
        """
        self._rising_keys = set()
        for key in self._EDGE_KEYS:
            stable = self.stability.is_stable(key)
            was = key in self._stable_prev
            if stable and not was:
                self._rising_keys.add(key)
            if stable:
                self._stable_prev.add(key)
            else:
                self._stable_prev.discard(key)

    def _rising(self, key: str) -> bool:
        """True neu cu chi vua dat nguong on dinh trong frame nay."""
        return key in getattr(self, "_rising_keys", set())

    # ------------------------------------------------------------------
    # Kenh 1: hai tay -> he thong (volume, open app, copy, desktop)
    # ------------------------------------------------------------------
    def _two_hand_system(self, hands: List[HandGesture],
                         frame: VisionFrame, now: float) -> Optional[List[ActionEvent]]:
        h1, h2 = hands[0], hands[1]
        ev: List[ActionEvent] = []

        # Volume: hai tay cung chi ngon tro, khoang cach 2 dau ngon tro.
        if self.stability.is_stable("two_volume"):
            d = dist2d(h1.hand.pt(INDEX_TIP), h2.hand.pt(INDEX_TIP))
            level = (d - self.vol_min) / max(self.vol_max - self.vol_min, 1e-6)
            level = max(0.0, min(1.0, level))
            self._transition(State.VOLUME)
            if self.cooldown.allow("volume", now):
                ev.append(ActionEvent("volume", {"level": level}))
            return ev

        # Giu hai ban tay xoe (5 ngon) du lau -> click tai diem mat nhin.
        # Chi phat 1 lan moi lan giu; tha tay hoac doi mode se reset.
        if self.stability.is_stable("two_open"):
            self._transition(State.WINDOW_MGMT)
            if self._two_open_since is None:
                self._two_open_since = now
                self._two_open_fired = False
            if (not self._two_open_fired
                    and now - self._two_open_since >= self.two_hand_click_hold):
                self._two_open_fired = True
                ev.append(ActionEvent("gaze_click", {}))
            return ev
        self._two_open_since = None
        self._two_open_fired = False

        # Copy plain text: hai tay cung pinch va dua lai gan nhau.
        if self._rising("two_copy"):
            self._transition(State.TEXT_EDIT)
            if self.cooldown.allow("copy_plain", now):
                ev.append(ActionEvent("copy_plain", {}))
            return ev

        # Chuyen desktop: vuot hai tay sang trai/phai.
        mid_x = (h1.hand.pt(WRIST)[0] + h2.hand.pt(WRIST)[0]) / 2.0
        direction = self._swipe_two.update(now, mid_x)
        if direction:
            self._transition(State.WINDOW_MGMT)
            if self.cooldown.allow("switch_desktop", now):
                ev.append(ActionEvent("switch_desktop", {"direction": direction}))
            return ev

        # Hai tay nhung khong cu chi ro rang -> khong lam gi (tranh xung dot).
        return None

    # ------------------------------------------------------------------
    # Kenh 2: mat -> cuon (gaze scroll)
    # ------------------------------------------------------------------
    def _face_scroll(self, frame: VisionFrame, now: float) -> Optional[List[ActionEvent]]:
        direction = self._gaze_direction(frame)
        if direction is None:
            self._gaze_dir = None
            return None
        # Bat dau dem thoi gian giu huong nhin.
        if direction != self._gaze_dir:
            self._gaze_dir = direction
            self._gaze_start = now
            return None
        if now - self._gaze_start < self.gaze_hold:
            return None
        # Da giu du lau -> cuon (lap lai khi con giu, theo cooldown scroll).
        if self.cooldown.allow("scroll", now):
            step = 1 if direction == "up" else -1
            return [ActionEvent("scroll", {"amount": step})]
        return []

    # ------------------------------------------------------------------
    # Kenh 3: mot tay -> chuot + cu chi he thong don
    # ------------------------------------------------------------------
    def _one_hand(self, h: HandGesture, frame: VisionFrame,
                  now: float) -> List[ActionEvent]:
        ev: List[ActionEvent] = []

        # Undo/Redo: vuot tay (ban tay mo) sang trai/phai.
        if h.is_open_palm:
            direction = self._swipe_one.update(now, h.hand.pt(WRIST)[0])
            if direction:
                self._transition(State.TEXT_EDIT)
                action = "undo" if direction == "left" else "redo"
                if self.cooldown.allow(action, now):
                    ev.append(ActionEvent(action, {}))
                return ev
        else:
            self._swipe_one.reset()

        # Alt+Tab: gio 4 ngon tay (tru cai). Giu state khi con on dinh,
        # chi phat event mot lan tai rising edge + cooldown.
        if self.stability.is_stable("alt_tab"):
            self._transition(State.WINDOW_MGMT)
            if self._rising("alt_tab") and self.cooldown.allow("alt_tab", now):
                ev.append(ActionEvent("alt_tab", {}))
            return ev

        # Dong tab: nam dam.
        if self.stability.is_stable("close_tab"):
            self._transition(State.WINDOW_MGMT)
            if self._rising("close_tab") and self.cooldown.allow("close_tab", now):
                ev.append(ActionEvent("close_tab", {}))
            return ev

        # Play/Pause: chu L.
        if self.stability.is_stable("play_pause"):
            self._transition(State.MEDIA)
            if self._rising("play_pause") and self.cooldown.allow("play_pause", now):
                ev.append(ActionEvent("play_pause", {}))
            return ev

        # Xu ly clipboard bang AI: 3 ngon tay (tro + giua + ap ut).
        if self.stability.is_stable("process_email"):
            self._transition(State.TEXT_EDIT)
            if self._rising("process_email") and self.cooldown.allow("process_email", now):
                ev.append(ActionEvent("process_email", {}))
            return ev

        # Chuot: ngon tro duoi (pointing) hoac dang pinch de drag/right-click.
        if h.is_pointing or h.pinch_index or h.pinch_middle or self._pinch_active:
            self._transition(State.MOUSE)
            ev.extend(self._mouse_control(h, now))
            return ev

        # Cuon bang chu V.
        if h.is_v_sign:
            self._transition(State.MOUSE)
            ev.extend(self._v_scroll(h, now))
            return ev

        self._transition(State.IDLE)
        self._reset_continuous()
        return ev

    # ------------------------------------------------------------------
    # Dieu khien chuot: move + click + drag + right click
    # ------------------------------------------------------------------
    def _mouse_control(self, h: HandGesture, now: float) -> List[ActionEvent]:
        ev: List[ActionEvent] = []
        self._mouse_active = True
        tip = h.hand.pt(INDEX_TIP)
        # Di chuyen con tro lien tuc (One Euro Filter se lam muot o action).
        ev.append(ActionEvent("mouse_move", {"x": float(tip[0]), "y": float(tip[1])}))

        # Right click: pinch cai + giua (rising edge).
        if self._rising("right_click"):
            if self.cooldown.allow("right_click", now):
                ev.append(ActionEvent("right_click", {}))

        # Left click / Drag dung hysteresis de chong nhay.
        engage = h.pinch_index_ratio < self.pinch_th
        release = h.pinch_index_ratio > self.pinch_th * 1.35
        pinch = self._pinch_active
        if not pinch and engage:
            pinch = True
        elif pinch and release:
            pinch = False

        if pinch and not self._pinch_active:
            # Bat dau pinch.
            self._pinch_active = True
            self._pinch_start = now
            self._dragging = False
        elif pinch and self._pinch_active:
            # Dang giu: neu du lau -> bat dau drag.
            if not self._dragging and now - self._pinch_start >= self.drag_hold_sec:
                self._dragging = True
                if self.cooldown.allow("drag", now):
                    ev.append(ActionEvent("drag_start", {}))
        elif not pinch and self._pinch_active:
            # Tha pinch.
            if self._dragging:
                ev.append(ActionEvent("drag_end", {}))
            else:
                if self.cooldown.allow("left_click", now):
                    ev.append(ActionEvent("left_click", {}))
            self._pinch_active = False
            self._dragging = False

        return ev

    # ------------------------------------------------------------------
    # Cuon bang chu V: di chuyen 2 ngon tay len/xuong
    # ------------------------------------------------------------------
    def _v_scroll(self, h: HandGesture, now: float) -> List[ActionEvent]:
        y = (h.hand.pt(INDEX_TIP)[1] + h.hand.pt(MIDDLE_TIP)[1]) / 2.0
        ev: List[ActionEvent] = []
        if self._v_scroll_last_y is None:
            self._v_scroll_last_y = y
            return ev
        dy = self._v_scroll_last_y - y   # tay di len (y giam) -> cuon len
        self._v_scroll_last_y = y
        if abs(dy) > 0.01 and self.cooldown.allow("scroll", now):
            amount = int(round(dy * self.v_scroll_sens * 10))
            if amount != 0:
                ev.append(ActionEvent("scroll", {"amount": amount}))
        return ev

    # ------------------------------------------------------------------
    # Tro ve
    # ------------------------------------------------------------------
    def _transition(self, new_state: State):
        if new_state != self.state:
            log.debug("State: %s -> %s", self.state.value, new_state.value)
            self.state = new_state

    def _reset_continuous(self):
        self._v_scroll_last_y = None
        self._gaze_dir = None
        # Khong reset swipe o day de tranh mat dau vet giua cac frame.

    def _finalize(self, events: List[ActionEvent]) -> List[ActionEvent]:
        # An toan: neu mat tay / roi kenh chuot khi dang drag, phai nha
        # chuot trai ra, neu khong he thong se bi "ket dinh" chuot.
        if self._pinch_active and not self._mouse_active:
            if self._dragging:
                events.append(ActionEvent("drag_end", {}))
            self._pinch_active = False
            self._dragging = False
        if events:
            self.last_action = events[-1].name
        return events
