# Changelog

## 1.2.0

### Changed
- **Captcha solver ported from OpenCV to scipy/numpy/Pillow.** OpenCV
  publishes zero musllinux (musl libc) wheels, and the real
  `homeassistant/home-assistant:stable` container is musllinux — so the
  integration was DOA on real Home Assistant (config flow returned HTTP 500
  on every add; the dependency physically could not install; not fixable
  config-side). scipy, numpy, and Pillow all ship musllinux wheels.
  `manifest.json`: removed `opencv-python-headless`, added `scipy>=1.16.2`
  and `Pillow>=12.0.0` (floors chosen as the earliest versions with
  musllinux cp314 wheels published, verified at build time).
- Algorithm is preserved exactly: 4 Canny-threshold-pair edge candidates +
  1 Sobel-magnitude candidate = 5 candidates, cluster-and-vote on x, same
  ±5px cluster tolerance. Canny replaced with a Sobel-gradient
  double-threshold + connectivity-linked scipy.ndimage equivalent;
  `cv2.matchTemplate`/`minMaxLoc` replaced with FFT-based normalized
  cross-correlation (`scipy.signal.fftconvolve`), pinned to the same
  top-left-origin matching convention (no template-width offset needed).
- Image decode now uses `PIL.Image.open(...).convert("RGBA")` (was
  `cv2.imdecode(IMREAD_UNCHANGED)`); `.convert("RGBA")` is mandatory so
  grayscale/palette source PNGs still decode to the H×W×4 shape the solver's
  channel-axis indexing requires.
- Added a small random ±3px jitter to the solved gap-x before the (unchanged)
  compact-JSON serialization, so submitted answers look hand-placed rather
  than pixel-perfect. Well inside the measured ≥5px accept band.
- Captcha retry delay lengthened from a flat 1s to ~1.5–2.5s (jittered) —
  the solver's own compute time now serves as authentic human-like
  think-time rather than a bot-tell-fast solve.
- Public API (`solve_captcha`, `authenticate`) unchanged; no caller changes.

## 1.1.1

### Changed
- **Minimum supported Home Assistant raised to 2026.6.0** (was 2024.1.0).
  Enforced via `hacs.json`; HACS will refuse to install/update on older HA.
  No integration behavior changed — this is a support-floor policy update.
- **Test suite now deterministically pinned**: `requirements_test.txt` pins
  exact `homeassistant==2026.6.0` and matching
  `pytest-homeassistant-custom-component==0.13.336` (was unpinned
  `>=2024.1.0`). CI now runs Python 3.14 (was 3.12) to match the HA
  2026.6.0 interpreter requirement (`requires_python>=3.14.2`).
  This closes an interpreter-skew false-green bug found during v1.1.0 QA,
  where an unpinned floor let pip silently resolve a much older
  non-crashing `homeassistant` release depending on the local Python version.

## 1.1.0

### Added
- **Per-gateway surplus sensor** (`sensor.epcube_<devid>_surplus`) — how much
  spare power is available at THIS gateway, grouped under that gateway's
  Device (not the whole-property level). Fixes surplus being meaningless on
  split/multi-location multi-gateway setups, where a single netted number
  corresponds to no physical panel.
- **Options Flow setting `surplus_mode`** — choose what "surplus" means for
  all gateways in the account:
  - **"Power sent to Grid"** (default) — `max(0, -grid_w)`, conservative,
    counts only power actually flowing to the grid right now.
  - **"Solar minus Load"** — `max(0, solar_w - home_load_w)`, more
    aggressive, shows headroom even while the battery is charging. Note:
    "Load" here is backup-circuit power, not whole-home load (see below).

### Changed — BEHAVIOR CHANGE
- **`sensor.epcube_property_surplus` sign convention flipped.** It was
  export-negative (a negative number meant "exporting"); it is now
  **export-positive and clamped at >= 0**, matching the new per-gateway
  surplus sensors: "surplus = spare watts, always a positive number." A
  deficit/import now simply reads 0 surplus. If you have an automation that
  depended on the old signed/negative value, update it (or use the
  still-signed `grid_w` sensor directly and invert as needed).

### Notes
- "Load" in the "Solar minus Load" surplus mode is **backup-circuit power**,
  not whole-home load — the EP Cube cloud API has no separate whole-home-load
  field, so `home_load_w` maps to the API's `backUpPower`. Backup/EPS
  circuits are typically a subset of whole-home consumption, so this mode
  can overstate true headroom for non-backup circuits. Calibrate your
  automation thresholds accordingly.
- Surplus sensors return `unknown` (not a false-high value) during a
  detected stale/session-expired reading, rather than reporting full solar
  or full grid export as spare power.
