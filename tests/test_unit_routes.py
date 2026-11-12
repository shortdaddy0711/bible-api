from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main


def verse(row_id, chapter, verse_start, version, text=None):
    return {
        "id": row_id,
        "book": "Genesis" if version == "ESV" else "창세기",
        "chapter": chapter,
        "verse_start": verse_start,
        "verse_end": verse_start,
        "text": text or f"{version} {chapter}:{verse_start}",
        "version": version,
    }


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.version_filter = None
        self.limit_value = None

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def ilike(self, column, value):
        self.version_filter = value
        return self

    def gte(self, *args, **kwargs):
        return self

    def lte(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        rows = self.rows
        if self.version_filter is not None:
            rows = [r for r in rows if str(r.get("version", "")).lower() == self.version_filter.lower()]
        if self.limit_value is not None:
            rows = rows[:self.limit_value]
        return SimpleNamespace(data=rows)


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        return FakeQuery(self.rows)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase([]))
    return TestClient(main.app)


def set_rows(monkeypatch, rows):
    monkeypatch.setattr(main, "supabase", FakeSupabase(rows))


def test_all_versions_return_one_envelope(monkeypatch, client):
    set_rows(monkeypatch, [verse("n1", 1, 1, "NKRV"), verse("e1", 1, 1, "ESV")])

    response = client.get(
        "/api/bible/chapters",
        params={"book": "Genesis", "chapter_start": 1, "version": "all"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["book"] == "Genesis"
    assert body["chapter_start"] == 1
    assert body["chapter_end"] == 1
    assert set(body["versions"]) == {"NKRV", "ESV"}
    assert body["versions"]["NKRV"]["verses"][0]["id"] == "n1"
    assert body["versions"]["ESV"]["verses"][0]["id"] == "e1"
    assert body["versions"]["NKRV"]["truncated"] is False
    assert body["versions"]["NKRV"]["next_verse_id"] is None


def test_single_version_is_still_an_envelope(monkeypatch, client):
    set_rows(monkeypatch, [verse("e1", 1, 1, "ESV")])

    response = client.get(
        "/api/bible/text",
        params={"book": "Genesis", "chapter": 1, "verse_start": 1, "version": "ESV"},
    )

    assert response.status_code == 200
    body = response.json()
    assert list(body["versions"]) == ["ESV"]
    assert body["versions"]["ESV"]["verses"][0]["id"] == "e1"


def test_invalid_version_is_422(monkeypatch, client):
    set_rows(monkeypatch, [verse("e1", 1, 1, "ESV")])

    response = client.get(
        "/api/bible/chapters",
        params={"book": "Genesis", "chapter_start": 1, "version": "bogus"},
    )

    assert response.status_code == 422


def test_lowercase_stored_version_is_not_dropped(monkeypatch, client):
    set_rows(monkeypatch, [verse("n1", 1, 1, "nkrv"), verse("e1", 1, 1, "ESV")])

    response = client.get(
        "/api/bible/chapters",
        params={"book": "Genesis", "chapter_start": 1, "version": "all"},
    )

    assert response.status_code == 200
    assert [v["id"] for v in response.json()["versions"]["NKRV"]["verses"]] == ["n1"]


def test_truncation_is_explicit_per_version(monkeypatch, client):
    rows = [verse(f"n{i}", 1, i + 1, "NKRV") for i in range(600)]
    set_rows(monkeypatch, rows)

    response = client.get(
        "/api/bible/chapters",
        params={"book": "Genesis", "chapter_start": 1, "version": "NKRV"},
    )

    assert response.status_code == 200
    block = response.json()["versions"]["NKRV"]
    assert len(block["verses"]) == 500
    assert block["truncated"] is True
    assert block["next_verse_id"] == "n500"


def test_no_rows_is_404(monkeypatch, client):
    set_rows(monkeypatch, [])

    response = client.get(
        "/api/bible/chapters",
        params={"book": "Genesis", "chapter_start": 1, "version": "all"},
    )

    assert response.status_code == 404
