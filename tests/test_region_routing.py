"""AC2: region dropdown routes to the correct regional host."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from epcube_multi.const import DEFAULT_REGION, REGIONS


def test_exactly_three_regions_us_eu_jp():
    """Only US/EU/JP are DNS+HTTP-verified live regions (2026-07-25).
    au/uk/de/cn/in/apac/emea/global do NOT resolve - must not be present."""
    assert set(REGIONS.keys()) == {"US", "EU", "JP"}


def test_default_region_is_us():
    """Default region is US and must remain the default."""
    assert DEFAULT_REGION == "US"


def test_region_hosts_match_verified_hosts():
    assert REGIONS["US"] == "https://monitoring-us.epcube.com/v1/api"
    assert REGIONS["EU"] == "https://monitoring-eu.epcube.com/v1/api"
    assert REGIONS["JP"] == "https://monitoring-jp.epcube.com/v1/api"


def test_region_selection_maps_to_distinct_base_urls():
    """Selecting a different region must route to a genuinely different
    host, not silently reuse the US host."""
    hosts = list(REGIONS.values())
    assert len(hosts) == len(set(hosts))
