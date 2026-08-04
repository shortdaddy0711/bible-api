import os
import re
import json
import time
import logging
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI

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

KO_TO_EN = {
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
        .select("id") \
        .eq("book", book) \
        .eq("chapter", chapter) \
        .eq("version", VERSION) \
        .limit(1) \
        .execute()
    return bool(r.data)

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
    verses: Dict[int, List[str]] = {}
    current: Optional[int] = None
    marker = re.compile(r"^\[(\d+)(?:[a-z])?\]\s*(.*)$")
    for raw_line in passage_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = marker.match(line)
        if m:
            current = int(m.group(1))
            verses.setdefault(current, []).append(m.group(2).strip())
        elif current is not None:
            verses[current].append(line)
    return {k: " ".join(v).strip() for k, v in verses.items()}

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
            if chapter_already_ingested(book, chapter):
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
                {"book": book, "chapter": chapter, "verse_start": n, "verse_end": n,
                 "text": text, "version": VERSION}
                for n, text in verses.items()
            ]
            insert_rows("bible_verses", verse_rows)
            pericopes = pericope_map.get(en_book, {}).get(str(chapter), [])
            sections = build_sections(book, chapter, verses, pericopes)
            insert_rows("bible_sections", sections)
            if processed % 25 == 0:
                logger.info("Processed %d/%d chapters", processed, total)
            time.sleep(FETCH_PACING_S)
    logger.info("Verse/section ingestion done. Starting embeddings...")
    embed_sections()
    logger.info("ESV ingestion completed!")

if __name__ == "__main__":
    run_ingestion()
