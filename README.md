# EP Cube Multi-Gateway

A Home Assistant custom integration for households running **multiple EP Cube
(Canadian Solar) energy storage gateways**.

## The need

If you have more than one EP Cube gateway on your property (e.g. two separate
battery/inverter banks on different circuits), you need per-gateway
visibility to reason about your property's real energy state — and you don't
want your integration to silently die every time your login token expires.

## What it does

- Authenticates to the EP Cube cloud API with **username + password only**.
  Login solves the AJ-Captcha block-puzzle **headlessly** using a computer-
  vision solver — no manual captcha interaction, ever.
- **Auto-refreshes** your session token before it expires and re-authenticates
  automatically on session loss — no manual token extraction, no silent
  outages.
- **Enumerates every gateway on your account** and exposes **per-gateway
  entities**: state of charge, grid power, solar generation, home load,
  battery power, and **per-gateway surplus** (spare power available at that
  specific gateway, always export-positive and clamped at 0 or above).
- Exposes a **computed whole-property surplus sensor**
  (`sensor.epcube_property_surplus`) — total spare power across all your
  gateways (export-positive, clamped at 0 or above), useful as an input for
  surplus-following automations.
- **Configurable surplus definition** via the integration's Options: choose
  "Power sent to Grid" (default, conservative — only counts power actually
  exporting right now) or "Solar minus Load" (more aggressive — shows
  headroom even while the battery is charging). **Note:** "Load" in this
  second mode is backup-circuit power, not whole-home load — the EP Cube
  cloud API has no separate whole-home-load field, so this can overstate
  true headroom for non-backup circuits.
- Supports **US, EU, and JP** EP Cube cloud regions via a dropdown in the
  config flow (defaults to US).
- Standard Home Assistant config-flow setup; installable via HACS.

## Installation

1. Add this repository as a custom repository in HACS (category:
   Integration), or place `custom_components/epcube_multi/` directly in your
   Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration**, search for
   "EP Cube Multi-Gateway", and follow the config flow (choose your region,
   then enter your EP Cube account username and password).

## Requirements

**Home Assistant 2026.6.0 or newer.** HACS enforces this floor at install/update
time (see `hacs.json`); older Home Assistant is not supported and will fail to
install.

This integration depends on `opencv-python-headless` (for headless captcha
solving) and `pycryptodome` (for the login handshake). Home Assistant
installs these automatically from the integration's manifest.

## Disclaimer

This integration is **not affiliated with, endorsed by, or supported by**
EP Cube or Canadian Solar. It uses an unofficial, reverse-engineered API.
Use at your own risk — the cloud API may change without notice.
