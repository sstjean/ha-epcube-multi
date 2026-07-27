"""AC5: captcha retry - solver failure path retries (up to 5) and surfaces a
clean error, not a stack trace."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from epcube_multi.auth import CaptchaSolveError, solve_captcha


def _fake_captcha_response():
    return {
        "data": {
            "secretKey": "0123456789abcdef",
            "token": "tok",
            "originalImageBase64": "x",
            "jigsawImageBase64": "y",
        }
    }


def test_captcha_solver_retries_up_to_five_times_then_raises_clean_error():
    """All 5 attempts fail -> CaptchaSolveError (not an uncaught exception /
    stack trace bubbling to the config flow)."""
    call_log = []

    def fake_api_request(base_url, method, path, data=None, token=None, timeout=30):
        call_log.append(path)
        if path == "/common/captcha/get":
            return _fake_captcha_response()
        if path == "/common/captcha/check":
            return {"status": 400}  # always fails
        raise AssertionError(f"unexpected path {path}")

    with patch("epcube_multi.auth.api_request", side_effect=fake_api_request), \
         patch("epcube_multi.auth._find_gap_x", return_value=42), \
         patch("epcube_multi.auth._aes_encrypt", return_value="enc"), \
         patch("epcube_multi.auth.time.sleep"):
        with pytest.raises(CaptchaSolveError):
            solve_captcha("https://monitoring-us.epcube.com/v1/api", max_attempts=5)

    check_calls = [p for p in call_log if p == "/common/captcha/check"]
    assert len(check_calls) == 5


def test_captcha_solver_succeeds_on_a_later_attempt():
    """Retries should recover once a subsequent attempt succeeds."""
    attempts = {"n": 0}

    def fake_api_request(base_url, method, path, data=None, token=None, timeout=30):
        if path == "/common/captcha/get":
            return _fake_captcha_response()
        if path == "/common/captcha/check":
            attempts["n"] += 1
            return {"status": 200} if attempts["n"] == 3 else {"status": 400}
        raise AssertionError(f"unexpected path {path}")

    with patch("epcube_multi.auth.api_request", side_effect=fake_api_request), \
         patch("epcube_multi.auth._find_gap_x", return_value=42), \
         patch("epcube_multi.auth._aes_encrypt", return_value="enc"), \
         patch("epcube_multi.auth.time.sleep"):
        token, secret_key, point_json = solve_captcha("https://monitoring-us.epcube.com/v1/api", max_attempts=5)

    assert attempts["n"] == 3
    assert token == "tok"
