import pytest
from books import (
    KO_TO_EN,
    detect_version,
    normalize_book,
    canonical_book,
    to_db_book,
    db_book_names,
    ko_to_en,
)


class TestDetectVersion:
    def test_korean_returns_nkrv(self):
        assert detect_version("하나님") == "NKRV"
        assert detect_version("시편 23:1") == "NKRV"
        assert detect_version("천지창조") == "NKRV"

    def test_english_returns_esv(self):
        assert detect_version("Genesis 1:1") == "ESV"
        assert detect_version("hello") == "ESV"
        assert detect_version("") == "ESV"
        assert detect_version("123") == "ESV"

    def test_mixed_contains_hangul_is_nkrv(self):
        assert detect_version("Genesis 창세기") == "NKRV"


class TestNormalizeBook:
    def test_english_to_korean_case_insensitive(self):
        assert normalize_book("Genesis") == "창세기"
        assert normalize_book("genesis") == "창세기"
        assert normalize_book("GENESIS") == "창세기"
        assert normalize_book("Psalms") == "시편"
        assert normalize_book("psalms") == "시편"

    def test_unknown_passthrough(self):
        assert normalize_book("UnknownBook") == "UnknownBook"
        assert normalize_book("") == ""

    def test_multiword(self):
        assert normalize_book("1 Samuel") == "사무엘상"
        assert normalize_book("1 samuel") == "사무엘상"
        assert normalize_book("Song of Solomon") == "아가"


class TestCanonicalBook:
    def test_english_canonical_case_insensitive(self):
        assert canonical_book("genesis") == "Genesis"
        assert canonical_book("GENESIS") == "Genesis"
        assert canonical_book("psalms") == "Psalms"
        assert canonical_book("1 samuel") == "1 Samuel"

    def test_unknown_passthrough(self):
        assert canonical_book("Unknown") == "Unknown"

    def test_korean_passthrough(self):
        # Korean input not in EN canonical map -> returned as-is
        assert canonical_book("창세기") == "창세기"


class TestToDbBook:
    def test_esv_uses_canonical(self):
        assert to_db_book("genesis", "ESV") == "Genesis"
        assert to_db_book("GENESIS", "ESV") == "Genesis"
        assert to_db_book("창세기", "ESV") == "창세기"  # not in canonical map

    def test_nkrv_uses_normalize(self):
        assert to_db_book("Genesis", "NKRV") == "창세기"
        assert to_db_book("Psalms", "NKRV") == "시편"
        assert to_db_book("창세기", "NKRV") == "창세기"  # already Korean, passthrough via normalize

    def test_other_version_treated_as_nkrv(self):
        assert to_db_book("Genesis", "OTHER") == "창세기"


class TestDbBookNames:
    def test_single_version(self):
        assert set(db_book_names("Genesis", ["ESV"])) == {"Genesis"}
        assert set(db_book_names("Genesis", ["NKRV"])) == {"창세기"}

    def test_both_versions_deduped(self):
        names = db_book_names("Genesis", ["NKRV", "ESV"])
        assert set(names) == {"창세기", "Genesis"}
        # order not guaranteed, but set size 2
        assert len(names) == 2

    def test_same_book_both_versions_same_when_input_is_korean_and_esv_canonical_is_korean_passthrough(self):
        # For a Korean book that has no English canonical mapping for ESV? Actually ESV canonical returns Korean passthrough
        # But for normal Genesis case they are distinct
        pass

    def test_dedup_when_versions_duplicate(self):
        names = db_book_names("Genesis", ["ESV", "ESV"])
        assert names == ["Genesis"] or set(names) == {"Genesis"}


class TestKoToEn:
    def test_direct_lookup(self):
        assert ko_to_en("창세기") == "Genesis"
        assert ko_to_en("시편") == "Psalms"

    def test_whitespace_tolerance(self):
        assert ko_to_en("디도 서") == "Titus"
        assert ko_to_en(" 디도 서 ") == "Titus"
        assert ko_to_en("열 왕기하") == "2 Kings"

    def test_unknown_returns_none(self):
        assert ko_to_en("Unknown") is None
        assert ko_to_en("") is None

    def test_all_ko_keys_have_en(self):
        for ko, en in KO_TO_EN.items():
            assert ko_to_en(ko) == en
