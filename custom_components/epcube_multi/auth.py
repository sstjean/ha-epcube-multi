"""EP Cube cloud API authentication and headless captcha solving.

Ported from sstjean/EPCubeGraph local/epcube-exporter/auth.py @ b46461a.
Logic lifted ~verbatim; the module-level CLOUD_API_BASE import is replaced
with a per-instance base_url so each config entry can point at its own
regional host (US/EU/JP).
"""
from __future__ import annotations

import base64
import json
import secrets
import time
import urllib.error
import urllib.request

import cv2
import numpy as np
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from .const import ENDPOINT_CAPTCHA_CHECK, ENDPOINT_CAPTCHA_GET, ENDPOINT_LOGIN


class AuthExpiredError(Exception):
    """Raised when the cloud API returns 401 for an expired/invalid token."""


class CaptchaSolveError(Exception):
    """Raised when the captcha solver exhausts all retry attempts."""


class LoginError(Exception):
    """Raised when the cloud API rejects login credentials."""


def api_request(base_url, method, path, data=None, token=None, timeout=30):
    """Make an HTTP request to the EP Cube cloud API at base_url."""
    url = f"{base_url}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise AuthExpiredError("Token expired (401)") from e
        raise


def jwt_exp(token):
    """Decode JWT expiry (exp claim) without external libraries."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return claims.get("exp", 0)
    except Exception:  # noqa: BLE001 - malformed token yields "unknown", not a crash
        return 0


# ---------------------------------------------------------------------------
# Captcha solver (headless AJ-Captcha block-puzzle solver, OpenCV-based)
# ---------------------------------------------------------------------------

def _aes_encrypt(text, key):
    """AES-ECB encrypt with PKCS7 padding -> base64."""
    cipher = AES.new(key.encode("utf-8"), AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(text.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode()


def _decode_image(b64_str):
    """Decode base64 PNG -> numpy array."""
    nparr = np.frombuffer(base64.b64decode(b64_str), np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)


def _find_gap_x(bg_b64, piece_b64):
    """Find the puzzle-piece gap x-position via edge/contour template matching."""
    bg = _decode_image(bg_b64)
    piece = _decode_image(piece_b64)

    piece_alpha = piece[:, :, 3] if piece.shape[2] == 4 else np.ones(piece.shape[:2], np.uint8) * 255
    piece_outline = cv2.Canny(piece_alpha, 100, 200)
    kernel = np.ones((3, 3), np.uint8)
    piece_outline = cv2.dilate(piece_outline, kernel, iterations=1)

    bg_gray = cv2.cvtColor(bg, cv2.COLOR_BGRA2GRAY) if bg.shape[2] == 4 else cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)

    candidates = []
    for low, high in [(50, 150), (80, 200), (100, 250), (30, 100)]:
        bg_edges = cv2.Canny(bg_gray, low, high)
        bg_edges = cv2.dilate(bg_edges, kernel, iterations=1)
        result = cv2.matchTemplate(bg_edges, piece_outline, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        candidates.append((max_loc[0], max_val))

    sx = cv2.Sobel(bg_gray, cv2.CV_64F, 1, 0, ksize=3)
    sy = cv2.Sobel(bg_gray, cv2.CV_64F, 0, 1, ksize=3)
    sobel_mag = np.uint8(np.clip(np.sqrt(sx**2 + sy**2), 0, 255))
    result_s = cv2.matchTemplate(sobel_mag, piece_outline, cv2.TM_CCOEFF_NORMED)
    _, max_val_s, _, max_loc_s = cv2.minMaxLoc(result_s)
    candidates.append((max_loc_s[0], max_val_s))

    candidates.sort(key=lambda c: c[0])
    clusters = []
    for x, conf in candidates:
        added = False
        for cluster in clusters:
            if abs(cluster[0] - x) <= 5:
                cluster[1].append((x, conf))
                added = True
                break
        if not added:
            clusters.append([x, [(x, conf)]])
    clusters.sort(key=lambda c: (-len(c[1]), -max(r[1] for r in c[1])))
    return int(round(np.mean([r[0] for r in clusters[0][1]])))


def solve_captcha(base_url, max_attempts=5, log=None):
    """Solve AJ-Captcha block puzzle. Returns (token, secret_key, point_json)."""
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            time.sleep(1)

        captcha = api_request(base_url, "POST", ENDPOINT_CAPTCHA_GET, {"captchaType": "blockPuzzle"})["data"]
        secret_key = captcha["secretKey"]
        token = captcha["token"]

        x_pos = _find_gap_x(captcha["originalImageBase64"], captcha["jigsawImageBase64"])
        point_json = json.dumps({"x": x_pos, "y": 5}, separators=(",", ":"))
        encrypted_point = _aes_encrypt(point_json, secret_key)

        # Human-like delay before submitting the solved puzzle
        delay = 1.9 + (secrets.randbelow(1500) - 500) / 1000  # 1.4-2.9s
        time.sleep(delay)

        result = api_request(base_url, "POST", ENDPOINT_CAPTCHA_CHECK, {
            "captchaType": "blockPuzzle",
            "pointJson": encrypted_point,
            "token": token,
        })

        if result.get("status") == 200:
            return token, secret_key, point_json

        if log:
            log.warning("Captcha attempt %d failed (x=%d)", attempt, x_pos)

    raise CaptchaSolveError(f"Failed to solve captcha after {max_attempts} attempts")


def authenticate(base_url, username, password, log=None):
    """Full login: solve captcha + login -> JWT token."""
    if log:
        log.info("Authenticating as %s ...", username)
    token, secret_key, point_json = solve_captcha(base_url, log=log)
    captcha_verification = _aes_encrypt(token + "---" + point_json, secret_key)

    result = api_request(base_url, "POST", ENDPOINT_LOGIN, {
        "userName": username,
        "password": password,
        "captchaVerification": captcha_verification,
    })

    if result.get("status") != 200:
        raise LoginError(result.get("message", "unknown error"))

    jwt = result["data"]["token"]
    if jwt.startswith("Bearer "):
        jwt = jwt[7:]
    if log:
        log.info("Authentication successful")
    return jwt
