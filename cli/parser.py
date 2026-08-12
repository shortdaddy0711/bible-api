from books import detect_version, to_db_book

class ReferenceError(Exception):
    pass

class Reference:
    def __init__(self, book: str, chapter: int, verse_start: int, verse_end: int):
        self.book = book
        self.chapter = chapter
        self.verse_start = verse_start
        self.verse_end = verse_end

    @property
    def version(self) -> str:
        return detect_version(self.book)

    def __str__(self):
        if self.verse_start == self.verse_end:
            return f"{self.book} {self.chapter}:{self.verse_start}"
        return f"{self.book} {self.chapter}:{self.verse_start}-{self.verse_end}"


def parse_reference(ref: str) -> Reference:
    """Parse '시편 23:1-3' / 'John 3:16' / '창세기 1' (whole chapter)."""
    parts = ref.strip().split()
    if not parts:
        raise ReferenceError("Empty reference")
    chapter_str = parts[-1]
    book = " ".join(parts[:-1]) if len(parts) > 1 else None
    if not book:
        raise ReferenceError(f"Missing chapter/verse for '{parts[0]}'")
    if ":" in chapter_str:
        chapter, _, verse_range = chapter_str.partition(":")
        try:
            chapter = int(chapter)
        except ValueError:
            raise ReferenceError(f"Invalid chapter in '{ref}'")
        if "-" in verse_range:
            try:
                v_start, v_end = (int(v) for v in verse_range.split("-", 1))
            except ValueError:
                raise ReferenceError(f"Invalid verse range in '{ref}'")
        else:
            try:
                v_start = v_end = int(verse_range)
            except ValueError:
                raise ReferenceError(f"Invalid verse in '{ref}'")
    else:
        try:
            chapter = int(chapter_str)
        except ValueError:
            raise ReferenceError(f"Invalid chapter in '{ref}'")
        v_start, v_end = 1, 999
    return Reference(book, chapter, v_start, v_end)


def db_book(book: str) -> str:
    return to_db_book(book, detect_version(book))