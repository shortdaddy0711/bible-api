import os
from unittest.mock import patch

# Ensure env for main import
os.environ.setdefault("SUPABASE_URL", "http://dummy")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "dummy")

from main import resolve_versions, Version


class TestResolveVersions:
    def test_none_detects_version(self):
        # English -> ESV, Korean -> NKRV
        assert resolve_versions("Genesis", None) == ["ESV"]
        assert resolve_versions("시편", None) == ["NKRV"]
        with patch("main.detect_version", return_value="NKRV"):
            assert resolve_versions("any", None) == ["NKRV"]

    def test_all_returns_both(self):
        assert resolve_versions("Genesis", Version.ALL) == ["NKRV", "ESV"]

    def test_single_version(self):
        assert resolve_versions("Genesis", Version.NKRV) == ["NKRV"]
        assert resolve_versions("Genesis", Version.ESV) == ["ESV"]
