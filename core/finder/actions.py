"""Click a found element and build privacy-safe telemetry fields."""

from __future__ import annotations


def click_found(el, mouse) -> None:
    cx = el.bbox[0] + el.bbox[2] // 2
    cy = el.bbox[1] + el.bbox[3] // 2
    mouse.move_screen(cx, cy)
    mouse.left_click()


def telemetry_fields(el, duration_ms: float) -> dict:
    """Only element_id / role / duration — never the element name or OCR text."""
    return {
        "element_id": el.id,
        "role": el.role,
        "duration_ms": int(duration_ms),
    }
