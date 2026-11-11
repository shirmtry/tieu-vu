# =====================================================================
# core/vision_engine.py
# Tang Vision: doc camera, chay MediaPipe Hands + FaceMesh, va dong goi
# ket qua thanh cac VisionFrame bat bien (immutable) de State Machine
# tieu thu. Camera duoc doc trong thread rieng de khong block main loop.
# =====================================================================
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from queue import Empty, Full, Queue
from typing import List, Optional

import cv2
import numpy as np

try:
    import mediapipe as mp
except ImportError:  # cho phep import module ngay ca khi chua cai mediapipe
    mp = None

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Hang so chi muc landmark cua MediaPipe Hands (21 diem).
# Tham khao: https://developers.google.com/mediapipe/solutions/vision/hand_landmarker
# ---------------------------------------------------------------------
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20

# Chi muc FaceMesh cho vung mat (dung cho gaze scroll, can refine_landmarks).
# Iris trai / phai va bien mi tren / duoi.
LEFT_IRIS = 468
RIGHT_IRIS = 473
LEFT_EYE_TOP, LEFT_EYE_BOTTOM = 159, 145
RIGHT_EYE_TOP, RIGHT_EYE_BOTTOM = 386, 374
# Goc mat (de chuan hoa vi tri iris theo phuong ngang).
LEFT_EYE_OUTER, LEFT_EYE_INNER = 33, 133
RIGHT_EYE_INNER, RIGHT_EYE_OUTER = 362, 263
# 6 diem EAR cho moi mat: (p1..p6) theo cong thuc Soukupova & Cech.
LEFT_EAR_POINTS = (33, 160, 158, 133, 153, 144)
RIGHT_EAR_POINTS = (362, 385, 387, 263, 373, 380)
# Diem uoc luong pitch dau (mui / cam) de phan biet cuon mat chu dong.
NOSE_TIP, CHIN = 1, 152


@dataclass
class EyeObservation:
    """Trang thai mat tai mot thoi diem: ti le iris + do mo mat (EAR)."""

    timestamp: float
    h_ratio: float          # 0..1 trai -> phai (trung binh 2 mat)
    v_ratio: float          # 0..1 tren -> duoi (trung binh 2 mat)
    ear_left: float
    ear_right: float
    valid: bool = True

    @property
    def ear(self) -> float:
        return (self.ear_left + self.ear_right) / 2.0


class EyeTracker:
    """Trich xuat tin hieu mat tu FaceLandmarks (MediaPipe 478 diem).

    Khong phu thuoc MediaPipe runtime -> co the test bang landmark tong hop.
    """

    def __init__(self, config: dict | None = None):
        cfg = (config or {}).get("gaze", {})
        self.min_ear = float(cfg.get("min_ear", 0.10))

    # ------------------------------------------------------------------
    @staticmethod
    def _h_ratio(face: FaceLandmarks, iris: int, inner: int, outer: int) -> float:
        left, right = sorted((face.pt(inner)[0], face.pt(outer)[0]))
        span = right - left
        if abs(span) < 1e-6:
            return 0.5
        return float((face.pt(iris)[0] - left) / span)

    @staticmethod
    def _v_ratio(face: FaceLandmarks, iris: int, top: int, bottom: int) -> float:
        span = face.pt(bottom)[1] - face.pt(top)[1]
        if abs(span) < 1e-6:
            return 0.5
        return float((face.pt(iris)[1] - face.pt(top)[1]) / span)

    @staticmethod
    def _ear(face: FaceLandmarks, idx) -> float:
        p1, p2, p3, p4, p5, p6 = (face.pt(i) for i in idx)
        horizontal = dist2d(p1, p4)
        if horizontal < 1e-6:
            return 0.0
        return float((dist2d(p2, p6) + dist2d(p3, p5)) / (2.0 * horizontal))

    # ------------------------------------------------------------------
    def observe(self, face: Optional[FaceLandmarks],
                timestamp: float) -> Optional[EyeObservation]:
        """Tra ve EyeObservation hoac None neu khong co du landmark iris."""
        if face is None or not face.has_iris:
            return None
        h_l = self._h_ratio(face, LEFT_IRIS, LEFT_EYE_INNER, LEFT_EYE_OUTER)
        h_r = self._h_ratio(face, RIGHT_IRIS, RIGHT_EYE_INNER, RIGHT_EYE_OUTER)
        v_l = self._v_ratio(face, LEFT_IRIS, LEFT_EYE_TOP, LEFT_EYE_BOTTOM)
        v_r = self._v_ratio(face, RIGHT_IRIS, RIGHT_EYE_TOP, RIGHT_EYE_BOTTOM)
        ear_l = self._ear(face, LEFT_EAR_POINTS)
        ear_r = self._ear(face, RIGHT_EAR_POINTS)
        return EyeObservation(
            timestamp=timestamp,
            h_ratio=(h_l + h_r) / 2.0,
            v_ratio=(v_l + v_r) / 2.0,
            ear_left=ear_l,
            ear_right=ear_r,
            valid=True,
        )


def dist2d(a, b) -> float:
    """Khoang cach Euclid 2D giua 2 landmark (x, y)."""
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


@dataclass
class HandLandmarks:
    """Goi 21 landmark cua mot ban tay + nhan trai/phai."""

    points: np.ndarray                 # shape (21, 3), toa do chuan hoa [0,1]
    handedness: str                    # "Left" | "Right"
    score: float = 0.0                 # do tin cay cua nhan handedness

    def pt(self, idx: int) -> np.ndarray:
        return self.points[idx]

    @property
    def wrist(self) -> np.ndarray:
        return self.points[WRIST]

    @property
    def palm_size(self) -> float:
        """Khoang cach co tay -> MCP ngon giua, dung lam mau so chuan hoa.

        Dung palm size thay vi khung hinh giup nguong pinch on dinh khi
        tay lai gan / ra xa camera.
        """
        return max(dist2d(self.points[WRIST], self.points[MIDDLE_MCP]), 1e-6)


@dataclass
class FaceLandmarks:
    """Goi landmark khuon mat (468 co ban + iris neu refine)."""

    points: np.ndarray                 # shape (N, 3)

    def pt(self, idx: int) -> np.ndarray:
        return self.points[idx]

    @property
    def has_iris(self) -> bool:
        return self.points.shape[0] > RIGHT_IRIS


@dataclass
class VisionFrame:
    """Ket qua vision cua mot frame, bat bien, an toan de truyen giua thread."""

    timestamp: float
    hands: List[HandLandmarks] = field(default_factory=list)
    face: Optional[FaceLandmarks] = None
    # Anh BGR da lat guong (dung cho preview). Khong bat buoc.
    image: Optional[np.ndarray] = None
    frame_id: int = 0

    @property
    def num_hands(self) -> int:
        return len(self.hands)


class VisionEngine:
    """Quan ly camera + MediaPipe. Chay capture/inference trong thread rieng.

    Cach dung:
        engine = VisionEngine(config)
        engine.start()
        frame = engine.get_latest_frame()   # khong block
        ...
        engine.stop()
    """

    def __init__(self, config: dict):
        self.cfg = config
        cam = config.get("camera", {})
        self.cam_index = int(cam.get("index", 0))
        self.width = int(cam.get("width", 960))
        self.height = int(cam.get("height", 540))
        self.fps = int(cam.get("fps", 30))
        self.flip = bool(cam.get("flip_horizontal", True))
        self.max_retries = int(cam.get("max_retries", 5))
        self.retry_delay = float(cam.get("retry_delay_sec", 1.0))

        vis = config.get("vision", {})
        self.hands_cfg = vis.get("hands", {})
        self.face_cfg = vis.get("face", {})
        self.face_enabled = bool(self.face_cfg.get("enabled", True))

        self._cap: Optional[cv2.VideoCapture] = None
        self._hands = None
        self._face = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: Optional[VisionFrame] = None
        self._frame_id = 0
        # Queue gioi han de tranh tich tu bo nho khi consumer cham.
        self.frame_queue: Queue = Queue(maxsize=4)
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Khoi tao / giai phong tai nguyen
    # ------------------------------------------------------------------
    def _open_camera(self) -> bool:
        """Mo camera, thu lai max_retries lan. Tra ve True neu thanh cong."""
        for attempt in range(1, self.max_retries + 1):
            try:
                # CAP_DSHOW giup mo camera nhanh va on dinh hon tren Windows.
                cap = cv2.VideoCapture(self.cam_index, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap.release()
                    raise RuntimeError("VideoCapture khong mo duoc")
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                cap.set(cv2.CAP_PROP_FPS, self.fps)
                self._cap = cap
                log.info("Camera %d da mo (%dx%d @ %dfps)",
                         self.cam_index, self.width, self.height, self.fps)
                return True
            except Exception as exc:  # loi camera: thu lai thay vi crash
                self.last_error = str(exc)
                log.warning("Mo camera lan %d that bai: %s", attempt, exc)
                time.sleep(self.retry_delay)
        log.error("Khong the mo camera sau %d lan thu.", self.max_retries)
        return False

    def _init_mediapipe(self) -> bool:
        if mp is None:
            self.last_error = "Chua cai mediapipe (pip install mediapipe)"
            log.error(self.last_error)
            return False
        try:
            self._hands = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=int(self.hands_cfg.get("max_num_hands", 2)),
                model_complexity=int(self.hands_cfg.get("model_complexity", 1)),
                min_detection_confidence=float(self.hands_cfg.get("min_detection_confidence", 0.7)),
                min_tracking_confidence=float(self.hands_cfg.get("min_tracking_confidence", 0.6)),
            )
            if self.face_enabled:
                self._face = mp.solutions.face_mesh.FaceMesh(
                    static_image_mode=False,
                    max_num_faces=1,
                    refine_landmarks=bool(self.face_cfg.get("refine_landmarks", True)),
                    min_detection_confidence=float(self.face_cfg.get("min_detection_confidence", 0.6)),
                    min_tracking_confidence=float(self.face_cfg.get("min_tracking_confidence", 0.6)),
                )
            return True
        except Exception as exc:
            self.last_error = f"Loi khoi tao MediaPipe: {exc}"
            log.exception(self.last_error)
            return False

    # ------------------------------------------------------------------
    # Vong lap capture + inference (chay trong thread rieng)
    # ------------------------------------------------------------------
    def _run(self):
        if not self._open_camera() or not self._init_mediapipe():
            return
        log.info("VisionEngine bat dau vong lap capture.")
        while not self._stop.is_set():
            try:
                ok, frame = self._cap.read()
                if not ok or frame is None:
                    log.warning("Mat frame camera, dang thu ket noi lai...")
                    if not self._reopen_camera():
                        break
                    continue
                if self.flip:
                    frame = cv2.flip(frame, 1)
                vf = self._process(frame)
                with self._lock:
                    self._latest = vf
                try:
                    self.frame_queue.put_nowait(vf)
                except Full:
                    # Consumer cham: bo frame cu, giu frame moi nhat.
                    try:
                        self.frame_queue.get_nowait()
                    except Empty:
                        pass
                    try:
                        self.frame_queue.put_nowait(vf)
                    except Full:
                        pass
            except Exception as exc:
                self.last_error = str(exc)
                log.exception("Loi trong vong lap vision: %s", exc)
                time.sleep(0.05)
        self._cleanup()
        log.info("VisionEngine da dung.")

    def _reopen_camera(self) -> bool:
        try:
            if self._cap is not None:
                self._cap.release()
        except Exception:
            pass
        self._cap = None
        return self._open_camera()

    def _process(self, frame_bgr: np.ndarray) -> VisionFrame:
        """Chay suy luyen MediaPipe tren mot frame BGR."""
        self._frame_id += 1
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        hands_out = self._hands.process(rgb)
        face_out = self._face.process(rgb) if self._face is not None else None

        hands: List[HandLandmarks] = []
        if hands_out.multi_hand_landmarks:
            for i, lm in enumerate(hands_out.multi_hand_landmarks):
                pts = np.array([[p.x, p.y, p.z] for p in lm.landmark], dtype=np.float32)
                label, score = "Right", 0.0
                if hands_out.multi_handedness and i < len(hands_out.multi_handedness):
                    cls = hands_out.multi_handedness[i].classification[0]
                    label, score = cls.label, float(cls.score)
                hands.append(HandLandmarks(points=pts, handedness=label, score=score))

        face: Optional[FaceLandmarks] = None
        if face_out and face_out.multi_face_landmarks:
            lm = face_out.multi_face_landmarks[0]
            pts = np.array([[p.x, p.y, p.z] for p in lm.landmark], dtype=np.float32)
            face = FaceLandmarks(points=pts)

        return VisionFrame(
            timestamp=time.time(),
            hands=hands,
            face=face,
            image=frame_bgr,
            frame_id=self._frame_id,
        )

    def _cleanup(self):
        try:
            if self._cap is not None:
                self._cap.release()
        except Exception:
            pass
        for sol in (self._hands, self._face):
            try:
                if sol is not None:
                    sol.close()
            except Exception:
                pass
        self._cap = None

    # ------------------------------------------------------------------
    # API cong khai
    # ------------------------------------------------------------------
    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="VisionEngine", daemon=True)
        self._thread.start()
        return True

    def get_latest_frame(self) -> Optional[VisionFrame]:
        with self._lock:
            return self._latest

    def get_frame_blocking(self, timeout: float = 1.0) -> Optional[VisionFrame]:
        try:
            return self.frame_queue.get(timeout=timeout)
        except Empty:
            return None

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
