"""EP Cube cloud API authentication and headless captcha solving.

Ported from sstjean/EPCubeGraph local/epcube-exporter/auth.py @ b46461a.
Logic lifted ~verbatim; the module-level CLOUD_API_BASE import is replaced
with a per-instance base_url so each config entry can point at its own
regional host (US/EU/JP).

Captcha solver uses scipy/numpy/Pillow (not OpenCV) so it installs cleanly
on musllinux (musl libc) HA containers, where OpenCV publishes zero wheels.
"""
from __future__ import annotations

import base64
import io
import json
import secrets
import time
import urllib.error
import urllib.request

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.signal import fftconvolve
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
    """Decode base64 PNG -> numpy H×W×4 (RGBA) array.

    .convert("RGBA") is mandatory (not optional/cosmetic): a bare
    np.array(Image.open(...)) on a grayscale (mode L) or palette (mode P)
    PNG yields a 2-D H×W array with no channel axis, and _find_gap_x
    indexes piece.shape[2] / bg.shape[2] unconditionally. Forcing RGBA
    guarantees the rank-3 H×W×4 shape the channel-axis indexing requires.
    """
    img = Image.open(io.BytesIO(base64.b64decode(b64_str))).convert("RGBA")
    return np.array(img)


def _rgba_to_gray(arr):
    """RGB(A)->gray using standard luma weights, dropping alpha."""
    r, g, b = arr[:, :, 0].astype(np.float64), arr[:, :, 1].astype(np.float64), arr[:, :, 2].astype(np.float64)
    return (0.299 * r + 0.587 * g + 0.114 * b).astype(np.uint8)


def _canny_like(gray, low, high):
    """Sobel-gradient double-threshold edge map, connectivity-linked
    (scipy.ndimage equivalent of cv2.Canny's hysteresis)."""
    gray_f = gray.astype(np.float64)
    sx = ndimage.sobel(gray_f, axis=1)
    sy = ndimage.sobel(gray_f, axis=0)
    mag = np.hypot(sx, sy)

    strong = mag >= high
    weak = mag >= low
    labeled, num = ndimage.label(weak, structure=np.ones((3, 3)))
    if num == 0:
        return np.zeros(gray.shape, dtype=np.uint8)
    strong_labels = set(labeled[strong].tolist()) - {0}
    keep = np.isin(labeled, list(strong_labels)) if strong_labels else np.zeros_like(weak)
    return (keep * 255).astype(np.uint8)


def _dilate3x3(edges):
    """3×3 dilation, matching cv2.dilate(kernel=np.ones((3,3))) iterations=1."""
    return ndimage.grey_dilation(edges, size=(3, 3))


def _ncc_match_x(image, template):
    """Normalized cross-correlation via FFT; return the x of the max-NCC
    location using cv2.matchTemplate's top-left-origin convention.

    C1: fftconvolve(image, template[::-1, ::-1], mode="valid") is
    correlation (not convolution) because the kernel is pre-flipped, and
    mode="valid" places output index (0,0) at the template's top-left
    origin sliding over the image -- exactly matchTemplate's convention.
    Do NOT use mode="full" (shifts argmax by ~template_width) and do NOT
    subtract a template-width offset; both would break the calibrated
    ±5px cluster tolerance.
    """
    image_f = image.astype(np.float64)
    template_f = template.astype(np.float64)

    template_mean = template_f - template_f.mean()
    template_norm = np.sqrt(np.sum(template_mean**2))
    if template_norm == 0:
        return 0, 0.0

    corr = fftconvolve(image_f, template_mean[::-1, ::-1], mode="valid")

    th, tw = template_f.shape
    image_sq = image_f**2
    window_sum = fftconvolve(image_f, np.ones((th, tw)), mode="valid")
    window_sq_sum = fftconvolve(image_sq, np.ones((th, tw)), mode="valid")
    window_energy = window_sq_sum - (window_sum**2) / (th * tw)
    window_energy = np.clip(window_energy, a_min=0, a_max=None)
    denom = np.sqrt(window_energy) * template_norm

    with np.errstate(divide="ignore", invalid="ignore"):
        ncc = np.where(denom > 1e-9, corr / denom, 0.0)

    max_idx = np.unravel_index(np.argmax(ncc), ncc.shape)
    max_val = float(ncc[max_idx])
    return int(max_idx[1]), max_val


def _find_gap_x(bg_b64, piece_b64):
    """Find the puzzle-piece gap x-position via edge/contour template matching.

    scipy/numpy/Pillow port of the original OpenCV solver -- musllinux has
    zero OpenCV wheels, so this is not optional. Algorithm structure
    (4 Canny threshold pairs + 1 Sobel-magnitude pass = 5 candidates,
    cluster-and-vote) is preserved exactly.
    """
    bg = _decode_image(bg_b64)
    piece = _decode_image(piece_b64)

    piece_alpha = piece[:, :, 3] if piece.shape[2] == 4 else np.ones(piece.shape[:2], np.uint8) * 255
    piece_outline = _canny_like(piece_alpha, 100, 200)
    piece_outline = _dilate3x3(piece_outline)

    bg_gray = _rgba_to_gray(bg)

    candidates = []
    for low, high in [(50, 150), (80, 200), (100, 250), (30, 100)]:
        bg_edges = _canny_like(bg_gray, low, high)
        bg_edges = _dilate3x3(bg_edges)
        max_x, max_val = _ncc_match_x(bg_edges, piece_outline)
        candidates.append((max_x, max_val))

    sx = ndimage.sobel(bg_gray.astype(np.float64), axis=1)
    sy = ndimage.sobel(bg_gray.astype(np.float64), axis=0)
    sobel_mag = np.uint8(np.clip(np.hypot(sx, sy), 0, 255))
    max_x_s, max_val_s = _ncc_match_x(sobel_mag, piece_outline)
    candidates.append((max_x_s, max_val_s))

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
            time.sleep(1.5 + secrets.randbelow(1000) / 1000)  # ~1.5-2.5s jittered retry delay

        captcha = api_request(base_url, "POST", ENDPOINT_CAPTCHA_GET, {"captchaType": "blockPuzzle"})["data"]
        secret_key = captcha["secretKey"]
        token = captcha["token"]

        gap_x = _find_gap_x(captcha["originalImageBase64"], captcha["jigsawImageBase64"])
        # R2: jitter the INT before the unchanged compact-JSON serialization.
        # point_json MUST stay a compact-JSON STRING (separators=(",",":"),
        # no spaces) -- that exact byte sequence is what gets AES-encrypted
        # and reused verbatim in authenticate(). Emitting a dict literal or
        # using default json.dumps (which inserts spaces) changes the
        # ciphertext the oracle validates and silently breaks the solve.
        jitter = secrets.randbelow(7) - 3  # uniform in {-3..+3}
        x_pos = gap_x + jitter
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
