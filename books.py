"""Single source of truth for Bible book name mappings.

Only KO_TO_EN is stored. Reverse lookups are via functions backed by
private caches — no public EN_TO_KO / EN_TO_KO_LOWER / EN_NAMES_LOWER.
"""
import re
from typing import List, Optional

HANGUL_RE = re.compile(r"[\uac00-\ud7af]")

KO_TO_EN: dict[str, str] = {
    '창세기': 'Genesis', '출애굽기': 'Exodus', '레위기': 'Leviticus', '민수기': 'Numbers', '신명기': 'Deuteronomy',
    '여호수아': 'Joshua', '사사기': 'Judges', '룻기': 'Ruth', '사무엘상': '1 Samuel', '사무엘하': '2 Samuel',
    '열왕기상': '1 Kings', '열왕기하': '2 Kings', '역대상': '1 Chronicles', '역대하': '2 Chronicles',
    '에스라': 'Ezra', '느헤미야': 'Nehemiah', '에스더': 'Esther', '욥기': 'Job', '시편': 'Psalms',
    '잠언': 'Proverbs', '전도서': 'Ecclesiastes', '아가': 'Song of Solomon', '이사야': 'Isaiah',
    '예레미야': 'Jeremiah', '예레미야애가': 'Lamentations', '에스겔': 'Ezekiel', '다니엘': 'Daniel',
    '호세아': 'Hosea', '요엘': 'Joel', '아모스': 'Amos', '오바댜': 'Obadiah', '요나': 'Jonah',
    '미가': 'Micah', '나훔': 'Nahum', '하박국': 'Habakkuk', '스바냐': 'Zephaniah', '학개': 'Haggai',
    '스가랴': 'Zechariah', '말라기': 'Malachi', '마태복음': 'Matthew', '마가복음': 'Mark',
    '누가복음': 'Luke', '요한복음': 'John', '사도행전': 'Acts', '로마서': 'Romans',
    '고린도전서': '1 Corinthians', '고린도후서': '2 Corinthians', '갈라디아서': 'Galatians',
    '에베소서': 'Ephesians', '빌립보서': 'Philippians', '골로새서': 'Colossians',
    '데살로니가전서': '1 Thessalonians', '데살로니가후서': '2 Thessalonians',
    '디모데전서': '1 Timothy', '디모데후서': '2 Timothy', '디도서': 'Titus', '빌레몬서': 'Philemon',
    '히브리서': 'Hebrews', '야고보서': 'James', '베드로전서': '1 Peter', '베드로후서': '2 Peter',
    '요한일서': '1 John', '요한이서': '2 John', '요한삼서': '3 John', '유다서': 'Jude', '요한계시록': 'Revelation'
}

# Private reverse caches — not part of public API
_EN_TO_KO_LOWER: dict[str, str] = {v.lower(): k for k, v in KO_TO_EN.items()}
_EN_CANONICAL_LOWER: dict[str, str] = {v.lower(): v for v in KO_TO_EN.values()}
_KO_NORMALIZED_TO_EN: dict[str, str] = {k.replace(" ", ""): v for k, v in KO_TO_EN.items()}


def detect_version(query: str) -> str:
    """NKRV for Korean queries, ESV for everything else."""
    return "NKRV" if HANGUL_RE.search(query) else "ESV"


def normalize_book(book: str) -> str:
    """Map an English book name (any case) to the Korean name used in the DB."""
    return _EN_TO_KO_LOWER.get(book.lower(), book)


def canonical_book(book: str) -> str:
    """Canonical English book name as stored in the DB (any case input)."""
    return _EN_CANONICAL_LOWER.get(book.lower(), book)


def to_db_book(book: str, version: str) -> str:
    """Map any book name to the DB book name for a given version."""
    return canonical_book(book) if version == "ESV" else normalize_book(book)


def db_book_names(book: str, versions: List[str]) -> List[str]:
    """DB book names for a book across one or more versions (deduped)."""
    names: set[str] = set()
    for v in versions:
        names.add(to_db_book(book, v))
    return list(names)


def ko_to_en(ko: str) -> Optional[str]:
    """KO -> EN with whitespace tolerance for DB entries like '디도 서'."""
    return KO_TO_EN.get(ko) or _KO_NORMALIZED_TO_EN.get(ko.replace(" ", "").strip())
