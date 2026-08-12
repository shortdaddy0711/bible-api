import os
import httpx

DEFAULT_API_URL = os.environ.get("BIBLE_API_URL", "http://76.13.110.111:8080")


class BibleAPIError(Exception):
    pass


class BibleClient:
    def __init__(self, base_url: str = DEFAULT_API_URL, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict) -> list:
        try:
            resp = httpx.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise BibleAPIError(f"Network error: {e}")
        if resp.status_code != 200:
            detail = self._detail(resp)
            raise BibleAPIError(f"{resp.status_code}: {detail}")
        return resp.json()

    @staticmethod
    def _detail(resp) -> str:
        try:
            data = resp.json()
            if isinstance(data, dict):
                return str(data.get("detail", data))
            return str(data)
        except Exception:
            return resp.text[:300]

    def text(self, book: str, verse_start: int, verse_end: int, chapter: int, version: str | None = None):
        return self._get("/api/bible/text", {
            "book": book, "chapter": chapter,
            "verse_start": verse_start, "verse_end": verse_end,
            **({"version": version} if version else {}),
        })

    def verse(self, ref: str, version: str | None = None):
        book, chapter, v_start, v_end = parse_reference(ref)
        data = self.text(book, v_start, v_end, chapter, version)
        rows = list(data.values())[0] if isinstance(data, dict) else data
        return rows

    def chapters(self, book: str, chapter_start: int, chapter_end: int, version: str | None = None):
        return self._get("/api/bible/chapters", {
            "book": book, "chapter_start": chapter_start, "chapter_end": chapter_end,
            **({"version": version} if version else {}),
        })

    def search(self, query: str, limit: int = 5, version: str | None = None):
        return self._get("/api/bible/search", {
            "query": query, "limit": limit,
            **({"version": version} if version else {}),
        })

    def chat_stream(self, message: str, history: list | None = None):
        """Yield parsed SSE events: {"type": "delta"|"done"|"error", ...}."""
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/chat/stream",
                json={"message": message, "history": history or []},
                timeout=self.timeout,
            ) as resp:
                if resp.status_code != 200:
                    yield {"type": "error", "detail": f"{resp.status_code}: {self._detail(resp)}"}
                    return
                for line in resp.iter_lines():
                    if line.startswith("data: "):
                        import json as _json
                        try:
                            event = _json.loads(line[6:])
                            yield event
                        except Exception:
                            continue
        except httpx.HTTPError as e:
            yield {"type": "error", "detail": f"Network error: {e}"}


def parse_reference(ref: str) -> tuple[str, int, int, int]:
    """Parse '시편 23:1-3' / 'John 3:16' / '창세기 1' -> (book, chapter, start, end)."""
    parts = ref.strip().split()
    if not parts:
        raise ValueError("Empty reference")
    book = parts[0]
    if len(parts) == 1:
        raise ValueError(f"Missing chapter/verse for '{book}'")
    chapter_str = parts[-1]
    book = " ".join(parts[:-1]) if len(parts) > 2 else book
    if ":" in chapter_str:
        chapter, _, verse_range = chapter_str.partition(":")
        chapter = int(chapter)
        if "-" in verse_range:
            v_start, v_end = (int(v) for v in verse_range.split("-", 1))
        else:
            v_start = v_end = int(verse_range)
    else:
        chapter = int(chapter_str)
        v_start = 1
        v_end = 999  # whole chapter: cap server-side by the chapter itself
    return book, chapter, v_start, v_end