import os
import sys
import re
import json
import time
import logging
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI

# Shared book mapping (single source of truth)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from books import KO_TO_EN

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("esv_ingester")

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
ESV_API_KEY = os.environ.get("ESV_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, OPENROUTER_API_KEY, ESV_API_KEY]):
    raise ValueError("SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, OPENROUTER_API_KEY, ESV_API_KEY required in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

EMBEDDING_MODEL = "openai/text-embedding-3-small"
VERSION = "ESV"
BATCH_SIZE = 50
# ESV API v3 limits: 60 requests/minute. Sleep between fetches to stay under.
FETCH_PACING_S = 1.1

PERICOPES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pericope_map.json")

# Commonly used books first so English search/chat gets useful results sooner
BOOK_PRIORITY = ['시편', '요한복음', '마태복음', '누가복음', '마가복음', '창세기', '로마서', '잠언',
                 '이사야', '출애굽기', '고린도전서', '고린도후서', '사도행전', '에베소서', '갈라디아서',
                 '빌립보서', '골로새서', '데살로니가전서', '디모데후서', '히브리서', '베드로전서',
                 '요한일서', '요한계시록', '다니엘', '에스더', '룻기']

def get_book_structure() -> Dict[str, List[int]]:
    structure: Dict[str, set] = {}
    page_size = 1000
    offset = 0
    while True:
        rows = supabase.table("bible_verses") \
            .select("book, chapter") \
            .eq("version", "NKRV") \
            .order("book") \
            .order("chapter") \
            .range(offset, offset + page_size - 1) \
            .execute().data
        if not rows:
            break
        for r in rows:
            structure.setdefault(r["book"], set()).add(r["chapter"])
        if len(rows) < page_size:
            break
        offset += page_size
    ordered = {b: sorted(chs) for b, chs in structure.items()}
    priority_books = [b for b in BOOK_PRIORITY if b in ordered]
    rest = [b for b in ordered if b not in BOOK_PRIORITY]
    return {b: ordered[b] for b in priority_books + rest}

def chapter_already_ingested(book: str, chapter: int) -> bool:
    r = supabase.table("bible_verses") \
        .select("text") \
        .eq("book", book) \
        .eq("chapter", chapter) \
        .eq("version", VERSION) \
        .order("verse_start") \
        .limit(5) \
        .execute()
    if not r.data:
        return False
    if any("[" in v["text"] for v in r.data):
        # Legacy line-parser bug merged verses; markers prove corruption.
        logger.warning("Corrupted ESV rows for %s %d; deleting and re-ingesting", book, chapter)
        supabase.table("bible_verses") \
            .delete().eq("book", book).eq("chapter", chapter).eq("version", VERSION).execute()
        supabase.table("bible_sections") \
            .delete().eq("book", book).eq("chapter", chapter).eq("version", VERSION).execute()
        return False
    return True

def fetch_esv_passage(en_book: str, chapter: int) -> Optional[str]:
    url = "https://api.esv.org/v3/passage/text/"
    params = {
        "q": f"{en_book} {chapter}",
        "include-verse-numbers": "true",
        "include-headings": "false",
        "include-passage-references": "false",
        "include-footnotes": "false",
        "include-short-copyright": "false",
        "line-length": 0,
    }
    headers = {"Authorization": f"Token {ESV_API_KEY}"}
    for attempt in range(4):
        resp = requests.get(url, params=params, headers=headers, timeout=60)
        if resp.status_code == 200:
            passages = resp.json().get("passages") or []
            return passages[0] if passages else None
        if resp.status_code == 429:
            wait = 15 * (attempt + 1)
            logger.warning("Rate limited (429) for %s %d; waiting %ds", en_book, chapter, wait)
            time.sleep(wait)
            continue
        logger.error("ESV API error %d for %s %d", resp.status_code, en_book, chapter)
        if resp.status_code in (401, 403):
            raise RuntimeError("ESV API key rejected")
        return None
    raise RuntimeError(f"Persistent 429 rate limit while fetching {en_book} {chapter}; re-run later to resume")

def parse_passage(passage_text: str) -> Dict[int, str]:
    # The ESV API packs multiple verses per line; markers can appear anywhere.
    # Drop everything before the first marker (headings/superscriptions), then
    # split on every marker in the text.
    first = re.search(r"\[(\d+)(?:[a-z])?\]", passage_text)
    if not first:
        return {}
    body = passage_text[first.start():]
    parts = re.split(r"\[(\d+)(?:[a-z])?\]", body)
    verses: Dict[int, List[str]] = {}
    for i in range(1, len(parts) - 1, 2):
        num = int(parts[i])
        clean = " ".join(parts[i + 1].split()).strip()
        if clean:
            verses.setdefault(num, []).append(clean)
    return {k: " ".join(v) for k, v in verses.items()}

def build_sections(book: str, chapter: int, verses: Dict[int, str], pericopes: List[Dict]) -> List[Dict]:
    if not verses:
        return []
    v_nums = sorted(verses.keys())
    max_v = v_nums[-1]
    sections = []
    if not pericopes:
        content = " ".join(verses[v] for v in v_nums)
        sections.append({
            "book": book, "chapter": chapter, "verse_range": f"{v_nums[0]}-{max_v}",
            "title": f"{book} {chapter}", "content": content, "version": VERSION
        })
        return sections
    for idx, p in enumerate(pericopes):
        start = 1 if idx == 0 else pericopes[idx - 1]["start"]
        end = p["start"] - 1
        if idx == len(pericopes) - 1:
            end = max_v
        vs = [verses[v] for v in range(start, end + 1) if v in verses]
        if not vs:
            continue
        sections.append({
            "book": book, "chapter": chapter, "verse_range": f"{start}-{end}",
            "title": p["title"], "content": " ".join(vs), "version": VERSION
        })
    return sections

def insert_rows(table: str, rows: List[Dict]):
    if not rows:
        return
    for i in range(0, len(rows), 500):
        supabase.table(table).insert(rows[i:i + 500]).execute()

def embed_sections():
    logger.info("Embedding sections without embeddings...")
    while True:
        r = supabase.table("bible_sections") \
            .select("id, book, chapter, verse_range, title, content") \
            .eq("version", VERSION) \
            .is_("embedding", "null") \
            .limit(BATCH_SIZE) \
            .execute()
        if not r.data:
            break
        texts = [f"[{s['book']} {s['chapter']}:{s['verse_range']}] {s['title']} - {s['content']}" for s in r.data]
        embeds = None
        for attempt in range(4):
            try:
                resp = openai_client.embeddings.create(input=texts, model=EMBEDDING_MODEL)
                embeds = [d.embedding for d in resp.data]
                break
            except Exception as e:
                logger.warning("Embedding attempt %d failed: %s", attempt + 1, e)
                time.sleep(10 * (attempt + 1))
        if embeds is None:
            raise RuntimeError("Embedding API persistently failing; re-run to continue")
        for s, emb in zip(r.data, embeds):
            supabase.table("bible_sections").update({"embedding": emb}).eq("id", s["id"]).execute()
        logger.info("Embedded %d sections", len(r.data))

def run_ingestion():
    with open(PERICOPES_PATH, encoding="utf-8") as f:
        pericope_map = json.load(f)
    structure = get_book_structure()
    total = sum(len(chs) for chs in structure.values())
    logger.info("Bible structure: %d books, %d chapters", len(structure), total)

    already = 0
    for book, chapters in structure.items():
        for chapter in chapters:
            if chapter_already_ingested(book, chapter):
                already += 1
    logger.info("%d of %d chapters already ingested (resume)", already, total)

    total = sum(len(chs) for chs in structure.values())
    processed = 0
    for book, chapters in structure.items():
        en_book = KO_TO_EN.get(book)
        if not en_book:
            logger.warning("No English mapping for book %r; skipping", book)
            continue
        for chapter in chapters:
            processed += 1
            if chapter_already_ingested(en_book, chapter):
                continue
            try:
                passage = fetch_esv_passage(en_book, chapter)
            except RuntimeError as e:
                # Rate limit exhausted: stop fetching, but still embed what we have
                logger.warning("%s — stopping early, embedding ingested sections", e)
                time.sleep(1)
                embed_sections()
                logger.info("Stopped early after %d/%d chapters; %d of %d books processed. Re-run later to resume.",
                            processed, total, list(structure).index(book) + 1, len(structure))
                return
            if passage is None:
                continue
            verses = parse_passage(passage)
            if not verses:
                logger.warning("No verses parsed for %s %d", book, chapter)
                continue
            verse_rows = [
                {"book": en_book, "chapter": chapter, "verse_start": n, "verse_end": n,
                 "text": text, "version": VERSION}
                for n, text in verses.items()
            ]
            insert_rows("bible_verses", verse_rows)
            pericopes = pericope_map.get(en_book, {}).get(str(chapter), [])
            sections = build_sections(en_book, chapter, verses, pericopes)
            insert_rows("bible_sections", sections)
            if processed % 25 == 0:
                logger.info("Processed %d/%d chapters", processed, total)
            time.sleep(FETCH_PACING_S)
    logger.info("Verse/section ingestion done. Starting embeddings...")
    embed_sections()
    logger.info("ESV ingestion completed!")

if __name__ == "__main__":
    run_ingestion()
