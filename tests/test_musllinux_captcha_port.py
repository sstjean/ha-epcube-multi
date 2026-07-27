"""v1.2.0 scipy/numpy/Pillow captcha solver port (replaces OpenCV, which
publishes zero musllinux wheels and cannot install on the real HA container).

R1: _decode_image must always return H×W×4 (RGBA), even for grayscale/
    palette source PNGs, because _find_gap_x indexes .shape[2] unconditionally.
C1: FFT-NCC must use the top-left-origin convention (fftconvolve mode="valid"
    on a flipped template) with no template-width offset -- verified against
    a synthetic image with a KNOWN template offset.
R2: gap-x jitter is applied to the integer BEFORE the unchanged compact-JSON
    serialization; point_json stays a no-space compact-JSON string.
AC-3 (combined bound, secondary local check): jitter alone never exceeds
    the ±3px contract (the combined solver-drift+jitter bound against the
    live oracle is verified separately, outside unit tests).
"""
import base64
import io
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from epcube_multi.auth import _decode_image, _ncc_match_x, solve_captcha


def _png_b64(mode, size=(20, 20), color=128):
    img = Image.new(mode, size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_r1_decode_grayscale_mode_l_yields_rank3_hw4():
    """A mode-L (grayscale) PNG must decode to H×W×4, not H×W -- otherwise
    piece.shape[2] raises IndexError as a real crash class."""
    b64 = _png_b64("L")
    arr = _decode_image(b64)
    assert arr.ndim == 3
    assert arr.shape[2] == 4


def test_r1_decode_palette_mode_p_yields_rank3_hw4():
    """A mode-P (palette) PNG must also decode to H×W×4."""
    img = Image.new("P", (16, 16))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    arr = _decode_image(b64)
    assert arr.ndim == 3
    assert arr.shape[2] == 4


def test_r1_decode_rgba_stays_rank3_hw4():
    b64 = _png_b64("RGBA", color=(10, 20, 30, 255))
    arr = _decode_image(b64)
    assert arr.shape == (20, 20, 4)


def test_c1_ncc_match_finds_known_template_offset_top_left_origin():
    """Plant a template at a KNOWN x-offset inside a larger image and confirm
    _ncc_match_x recovers that exact offset with the top-left-origin
    convention (no template-width subtraction needed)."""
    rng = np.random.default_rng(42)
    image = rng.integers(0, 255, size=(40, 100), dtype=np.uint8).astype(np.float64)

    known_offset_x = 37
    template = image[:, known_offset_x:known_offset_x + 20].copy()

    found_x, confidence = _ncc_match_x(image, template)

    assert found_x == known_offset_x
    assert confidence > 0.99  # near-perfect match on an exact-copy template


def test_c1_ncc_match_full_mode_would_be_wrong_sanity_check():
    """Negative-control: confirms the test itself would catch a mode="full"
    regression (which shifts the argmax by ~template_width) -- if someone
    reintroduces mode="full", found_x would land far from the true offset,
    not within a few px."""
    rng = np.random.default_rng(7)
    image = rng.integers(0, 255, size=(30, 80), dtype=np.uint8).astype(np.float64)
    known_offset_x = 15
    template = image[:, known_offset_x:known_offset_x + 15].copy()

    found_x, _ = _ncc_match_x(image, template)
    # mode="full" would shift this by ~template_width (15); "valid" must not.
    assert abs(found_x - known_offset_x) < 2


@pytest.mark.parametrize("gap_x", [10, 50, 137])
def test_r2_jitter_applied_to_int_before_compact_json_serialization(gap_x):
    """solve_captcha must jitter the integer gap_x, then serialize with
    json.dumps(..., separators=(",", ":")) -- a no-space compact string,
    matching what authenticate() re-uses verbatim for AES + oracle check."""
    from unittest.mock import patch

    def fake_api_request(base_url, method, path, data=None, token=None, timeout=30):
        if path == "/common/captcha/get":
            return {"data": {"secretKey": "0123456789abcdef", "token": "tok", "originalImageBase64": "x", "jigsawImageBase64": "y"}}
        if path == "/common/captcha/check":
            return {"status": 200}
        raise AssertionError(f"unexpected path {path}")

    with patch("epcube_multi.auth.api_request", side_effect=fake_api_request), \
         patch("epcube_multi.auth._find_gap_x", return_value=gap_x), \
         patch("epcube_multi.auth._aes_encrypt", return_value="enc"), \
         patch("epcube_multi.auth.time.sleep"):
        token, secret_key, point_json = solve_captcha("https://monitoring-us.epcube.com/v1/api")

    # Must be a compact string, no spaces, exact separators contract.
    assert isinstance(point_json, str)
    assert " " not in point_json
    parsed = json.loads(point_json)
    assert parsed["y"] == 5
    # Jitter contract: final x must be within ±3 of the raw solver gap_x.
    assert abs(parsed["x"] - gap_x) <= 3
    # Round-trip: re-serializing with the same separators must byte-match
    # (guards against a dict-literal / default-json.dumps regression that
    # would insert spaces and change the AES ciphertext).
    assert point_json == json.dumps({"x": parsed["x"], "y": 5}, separators=(",", ":"))


def test_r2_jitter_range_never_exceeds_contract():
    """Unit-level jitter-only guard (secondary check) -- jitter itself
    never exceeds ±3px across many draws. The COMBINED solver-drift + jitter
    bound (|solver_x-true_x|+3<=5) is verified against the live oracle
    separately, not here (no oracle access in unit tests)."""
    from unittest.mock import patch

    gap_x = 60
    seen_deltas = set()

    def fake_api_request(base_url, method, path, data=None, token=None, timeout=30):
        if path == "/common/captcha/get":
            return {"data": {"secretKey": "0123456789abcdef", "token": "tok", "originalImageBase64": "x", "jigsawImageBase64": "y"}}
        if path == "/common/captcha/check":
            return {"status": 200}
        raise AssertionError(f"unexpected path {path}")

    for _ in range(60):
        with patch("epcube_multi.auth.api_request", side_effect=fake_api_request), \
             patch("epcube_multi.auth._find_gap_x", return_value=gap_x), \
             patch("epcube_multi.auth._aes_encrypt", return_value="enc"), \
             patch("epcube_multi.auth.time.sleep"):
            _, _, point_json = solve_captcha("https://monitoring-us.epcube.com/v1/api")
        delta = json.loads(point_json)["x"] - gap_x
        assert -3 <= delta <= 3
        seen_deltas.add(delta)

    # Over 60 draws we should see meaningful spread, not a constant/no-op jitter.
    assert len(seen_deltas) >= 3
