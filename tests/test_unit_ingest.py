from types import SimpleNamespace
from scripts import ingest_esv


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_single_chapter_book_requests_the_whole_chapter(monkeypatch):
    sent: dict = {}

    def fake_get(_url, params=None, headers=None, timeout=None):
        sent.update(params or {})
        body = " ".join(f"[{n}] verse {n}" for n in range(1, 26))
        return FakeResponse({"passages": [body]})

    monkeypatch.setattr(ingest_esv.requests, "get", fake_get)
    passage = ingest_esv.fetch_esv_passage("Philemon", 1)

    assert sent["q"] == "Philemon 1:1-999"
    assert passage is not None
    assert len(ingest_esv.parse_passage(passage)) == 25


def test_sections_use_their_own_heading():
    verses = {n: f"v{n}" for n in range(1, 26)}
    pericopes = [
        {"title": "Greeting", "start": 1},
        {"title": "Philemon's Love and Faith", "start": 4},
        {"title": "Paul's Plea for Onesimus", "start": 8},
        {"title": "Final Greetings", "start": 23},
    ]

    sections = ingest_esv.build_sections("Philemon", 1, verses, pericopes)

    assert [(s["verse_range"], s["title"]) for s in sections] == [
        ("1-3", "Greeting"),
        ("4-7", "Philemon's Love and Faith"),
        ("8-22", "Paul's Plea for Onesimus"),
        ("23-25", "Final Greetings"),
    ]


def test_verses_before_the_first_heading_get_their_own_section():
    verses = {1: "superscription", 2: "b", 3: "c"}
    pericopes = [{"title": "Edom Will Be Humbled", "start": 2}]

    sections = ingest_esv.build_sections("Obadiah", 1, verses, pericopes)

    assert [(s["verse_range"], s["title"]) for s in sections] == [
        ("1-1", "Obadiah 1"),
        ("2-3", "Edom Will Be Humbled"),
    ]


def test_verse_text_lands_in_exactly_one_section():
    verses = {n: f"v{n}" for n in range(1, 26)}
    pericopes = [{"title": "Greeting", "start": 1}, {"title": "Body", "start": 4}]

    sections = ingest_esv.build_sections("Philemon", 1, verses, pericopes)

    covered = [v for s in sections for v in range(int(s["verse_range"].split("-")[0]), int(s["verse_range"].split("-")[1]) + 1)]
    assert covered == list(range(1, 26))


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows
        self.deleted = []

    def table(self, name):
        return FakeTable(self, name)


class FakeTable:
    def __init__(self, db, name):
        self.db = db
        self.name = name

    def select(self, *args):
        return self

    def eq(self, *args):
        return self

    def order(self, *args):
        return self

    def limit(self, *args):
        return self

    def delete(self):
        self.db.deleted.append(self.name)
        return self

    def execute(self):
        return SimpleNamespace(data=self.db.rows if self.name == "bible_verses" else [])


def test_single_verse_chapter_is_deleted_and_refetched(monkeypatch):
    db = FakeSupabase([{"text": "only verse"}])
    monkeypatch.setattr(ingest_esv, "supabase", db)

    assert ingest_esv.chapter_already_ingested("Philemon", 1) is False
    assert db.deleted == ["bible_verses", "bible_sections"]


def test_healthy_chapter_is_skipped(monkeypatch):
    db = FakeSupabase([{"text": f"verse {n}"} for n in range(1, 6)])
    monkeypatch.setattr(ingest_esv, "supabase", db)

    assert ingest_esv.chapter_already_ingested("Philemon", 1) is True
    assert db.deleted == []
