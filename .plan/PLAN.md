# PLAN — Voice-Driven Click (VOICE_CLICK)

## Feature
Voice command ("bấm nút Đăng nhập") -> find a UI element -> click it.

- Primary finder: Windows UI Automation (UIA) — accurate, returns role + bbox.
- Fallback: RapidOCR over a screen grab — bbox only; OCR text is never stored
  or logged. Privacy: no screenshots written to disk, no transcripts logged.
- No teencode map, no cloud LLM, no semantic model.
- Mode: `VOICE_CLICK` (hotkey `Ctrl+Alt+O`), blocks gestures, allows voice +
  gaze highlight. Mode exclusivity is preserved.

## Baseline (verified)
- `pytest -q`: 128 passed.
- `ruff check .` on tracked paths: clean.
- Local `main` == `origin/main` == `fa65fda`.

## Files to CREATE
- `core/finder/__init__.py`
- `core/finder/uia_finder.py`  (UiaFinder, FoundElement)
- `core/finder/ocr_finder.py`  (OcrFinder, bbox + fuzzy match only)
- `core/finder/hybrid.py`      (HybridFinder: UIA then OCR)
- `core/finder/actions.py`     (click_found, telemetry_fields)
- `scripts/cleanup_repo.py`
- `scripts/auto_dev.py`
- `scripts/install_startup_windows.ps1`
- `scripts/install_auto_dev_windows.ps1`
- `scripts/run_silent.vbs`
- `install.bat`
- `tieu_vu.spec`
- `.github/workflows/canary.yml`
- `.github/workflows/post-merge-check.yml`
- `tests/test_finder_uia.py`
- `tests/test_finder_ocr.py`
- `tests/test_finder_hybrid.py`
- `tests/test_integration_voice_click.py`
- `tests/test_perf_bench.py`
- `docs/VOICE_CLICK.md`

## Files to MODIFY (limited)
- `core/state_machine.py` — `Mode.VOICE_CLICK`, accepts_voice/gaze, wake stay.
- `core/nlu.py` — `click_target` rule (slot `target`).
- `main.py` — finder wiring, `click_target` handler + telemetry redaction,
  hotkey, HUD accent, `--dry-run-for`.
- `ui/hud.py` — optional accent color for the status ring.
- `config.yaml` — `voice_click` block + mode comment.
- `requirements.txt`, `requirements-dev.txt`, `.gitignore`.
- `README.md`, `SOLUTION.md`, `AGENTS.md`.
- `.github/workflows/release.yml` — build on main, tag `v1.0.<run>`.

## Safety / constraints
- Single action queue: voice -> `ActionEvent("click_target")` -> ActionWorker.
- Finder is blocking but runs inside ActionWorker, never in the vision loop.
- Telemetry redaction: `click_target` stores `target_chars`, then
  `{element_id, role, duration_ms}` only.
- All optional deps (`uiautomation`, `rapidocr_onnxruntime`, `mss`,
  `rapidfuzz`) are lazy-imported; missing -> degrade, never crash.
- Existing 128 tests must stay green. No breaking changes.
- No `git push --force`, no direct commit to `main`, no secrets.

## Rollback
- Tag `pre-auto-<ts>` before merge.
- If post-merge check fails: revert merge SHA (`git revert <sha>`) and push.
