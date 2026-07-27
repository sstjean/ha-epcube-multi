"""Shared test fixtures for the EP Cube Multi-Gateway test suite."""
import sys
from pathlib import Path

# Make custom_components importable as a top-level package for tests.
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

pytest_plugins = ["pytest_homeassistant_custom_component"]
