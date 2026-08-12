import pytest
from unittest.mock import Mock, patch
import os

# Ensure env for main import
os.environ.setdefault("SUPABASE_URL", "http://dummy")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "dummy")

from main import resolve_versions, group_by_version


class TestResolveVersions:
    def test_none_detects_version(self):
        # English -> ESV, Korean -> NKRV
        assert resolve_versions("Genesis", None) == ["ESV"]
        assert resolve_versions("시편", None) == ["NKRV"]  # Hangul detected, but we use English now? book is English? For Korean test, need Hangul
        # Actually detect_version checks query string for Hangul, so Korean book name returns NKRV
        with patch("main.detect_version", return_value="NKRV"):
            assert resolve_versions("any", None) == ["NKRV"]

    def test_all_returns_both(self):
        assert set(resolve_versions("Genesis", "all")) == {"NKRV", "ESV"}
        assert set(resolve_versions("Genesis", "ALL")) == {"NKRV", "ESV"}
        assert set(resolve_versions("Genesis", "NKRV,ESV")) == {"NKRV", "ESV"}
        assert set(resolve_versions("Genesis", "ESV,NKRV")) == {"NKRV", "ESV"}
        assert set(resolve_versions("Genesis", " nkrv, esv ")) == {"NKRV", "ESV"}

    def test_single_version_upper(self):
        assert resolve_versions("Genesis", "esv") == ["ESV"]
        assert resolve_versions("Genesis", "nkrv") == ["NKRV"]
        assert resolve_versions("Genesis", "ESV") == ["ESV"]

    def test_whitespace_and_case(self):
        assert resolve_versions("Genesis", " ESV ") == ["ESV"]


class TestGroupByVersion:
    def test_single_version_flat(self):
        rows = [{"id": "1", "version": "ESV"}, {"id": "2", "version": "ESV"}]
        result = group_by_version(rows, ["ESV"])
        assert result == rows

    def test_single_version_nkrv_flat(self):
        rows = [{"id": "1", "version": "NKRV"}]
        assert group_by_version(rows, ["NKRV"]) == rows

    def test_multiple_versions_grouped(self):
        rows = [
            {"id": "1", "version": "ESV", "text": "a"},
            {"id": "2", "version": "NKRV", "text": "b"},
            {"id": "3", "version": "ESV", "text": "c"},
        ]
        result = group_by_version(rows, ["NKRV", "ESV"])
        assert isinstance(result, dict)
        assert len(result["ESV"]) == 2
        assert len(result["NKRV"]) == 1
        assert result["ESV"][0]["id"] == "1"

    def test_multiple_versions_empty_group(self):
        rows = [{"id": "1", "version": "ESV"}]
        result = group_by_version(rows, ["NKRV", "ESV"])
        assert result["NKRV"] == []
        assert result["ESV"] == [{"id": "1", "version": "ESV"}]

    def test_empty_rows(self):
        assert group_by_version([], ["ESV"]) == []
        assert group_by_version([], ["NKRV", "ESV"]) == {"NKRV": [], "ESV": []}
