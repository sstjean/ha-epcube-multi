"""AC6 & AC7 (static/manifest-level checks): dependency declaration is
correct (scipy/Pillow musllinux-installable solver deps, no OpenCV) and
HACS-required files are present. Live container install + hacs/action/
hassfest execution happen in CI (AC6/AC7 runtime enforcement); these tests
are the fast, local, always-run guardrails against regressing the manifest.
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MANIFEST = REPO_ROOT / "custom_components" / "epcube_multi" / "manifest.json"
HACS_JSON = REPO_ROOT / "hacs.json"


def test_manifest_requires_scipy_and_pillow_no_opencv():
    """v1.2.0: OpenCV publishes zero musllinux wheels and cannot install on
    the real HA container; the captcha solver was ported to scipy/numpy/
    Pillow specifically because those DO have musllinux wheels. OpenCV must
    never reappear in requirements."""
    manifest = json.loads(MANIFEST.read_text())
    reqs = manifest["requirements"]
    assert any(r.startswith("scipy") for r in reqs)
    assert any(r.lower().startswith("pillow") for r in reqs)
    assert not any("opencv" in r.lower() for r in reqs)


def test_manifest_requires_pycryptodome():
    manifest = json.loads(MANIFEST.read_text())
    reqs = manifest["requirements"]
    assert any(r.startswith("pycryptodome") for r in reqs)


def test_manifest_has_version_and_config_flow():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["domain"] == "epcube_multi"
    assert manifest["config_flow"] is True
    assert "version" in manifest
    assert manifest["iot_class"] == "cloud_polling"


def test_hacs_json_present_and_well_formed():
    hacs = json.loads(HACS_JSON.read_text())
    assert hacs["name"] == "EP Cube Multi-Gateway"
    assert hacs["render_readme"] is True
    assert "homeassistant" in hacs


def test_license_present():
    assert (REPO_ROOT / "LICENSE").exists()


def test_ci_workflows_present_for_hacs_and_hassfest():
    validate_workflow = (REPO_ROOT / ".github" / "workflows" / "validate.yml").read_text()
    assert "hacs/action" in validate_workflow
    assert "hassfest" in validate_workflow


def test_readme_has_no_comparison_table():
    """Design directive: no comparison table / no competitor call-out."""
    readme = (REPO_ROOT / "README.md").read_text().lower()
    assert "bobsilvio" not in readme
    assert "| feature" not in readme  # no markdown comparison table header
    assert "vs." not in readme and " vs " not in readme
