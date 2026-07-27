# Changelog

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
