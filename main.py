from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import os
import time
import json
import logging
import traceback
from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI
from typing import List, Optional, Dict
from enum import Enum
from agent import BibleAgent, ChatRequest, ESV_COPYRIGHT
from books import detect_version, to_db_book

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("api_logger")

# Load environment variables
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase credentials not found in .env")
if not OPENROUTER_API_KEY:
    raise ValueError("OpenRouter API key not found in .env")

# Initialize clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
bible_agent = BibleAgent(openai_client, supabase)

app = FastAPI(title="Logos Mind API", description=f"Bilingual Bible search and theological chat. NKRV for Korean, ESV for English. {ESV_COPYRIGHT}")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    logger.info(f"Incoming request: {request.method} {request.url}")
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(f"Completed request: {request.method} {request.url} - Status: {response.status_code} - Took {process_time:.4f}s")
    return response

class VerseResponse(BaseModel):
    id: str
    book: str
    chapter: int
    verse_start: int
    verse_end: int
    text: str
    similarity: Optional[float] = None
    version: Optional[str] = None
    copyright: Optional[str] = None

class Version(str, Enum):
    NKRV = "NKRV"
    ESV = "ESV"
    ALL = "all"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            for member in cls:
                if member.value.lower() == normalized:
                    return member
        return None

class SearchVersion(str, Enum):
    NKRV = "NKRV"
    ESV = "ESV"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            for member in cls:
                if member.value.lower() == normalized:
                    return member
        return None

MAX_VERSES = 500

class VersionVerses(BaseModel):
    verses: List[VerseResponse]
    truncated: bool = False
    next_verse_id: Optional[str] = None

class VersesResponse(BaseModel):
    book: str
    chapter_start: int
    chapter_end: int
    versions: Dict[str, VersionVerses]

class SermonResponse(BaseModel):
    id: str
    title: Optional[str] = None
    date: Optional[str] = None
    speaker: Optional[str] = None
    chunk_text: str
    similarity: Optional[float] = None

class SectionResponse(BaseModel):
    id: str
    book: str
    chapter: int
    verse_range: str
    title: Optional[str] = None
    content: str
    similarity: Optional[float] = None
    version: Optional[str] = None
    copyright: Optional[str] = None

def resolve_versions(book: str, version: Optional[Version]) -> List[str]:
    """Resolve the validated version param to the list of versions to query."""
    if version is None:
        return [detect_version(book)]
    if version is Version.ALL:
        return ["NKRV", "ESV"]
    return [version.value]

def fetch_version_rows(book: str, chapter_start: int, chapter_end: int, version: str,
                       verse_start: Optional[int] = None, verse_end: Optional[int] = None):
    """Fetch one version's rows, capped per version. Returns (rows, truncated, next_verse_id)."""
    query = supabase.table("bible_verses") \
        .select("id, book, chapter, verse_start, verse_end, text, version") \
        .eq("book", to_db_book(book, version)) \
        .ilike("version", version) \
        .gte("chapter", chapter_start) \
        .lte("chapter", chapter_end)
    if verse_start is not None:
        query = query.gte("verse_start", verse_start).lte("verse_end", verse_end)
    rows = query.order("chapter").order("verse_start").limit(MAX_VERSES + 1).execute().data or []
    truncated = len(rows) > MAX_VERSES
    next_verse_id = rows[MAX_VERSES]["id"] if truncated else None
    rows = rows[:MAX_VERSES]
    if version == "ESV":
        for row in rows:
            row["copyright"] = ESV_COPYRIGHT
    return rows, truncated, next_verse_id

def fetch_verses(book: str, chapter_start: int, chapter_end: int, versions: List[str],
                 verse_start: Optional[int] = None, verse_end: Optional[int] = None):
    """Fetch every requested version, including an empty block when a version has no rows."""
    blocks = {}
    for version in versions:
        rows, truncated, next_verse_id = fetch_version_rows(
            book, chapter_start, chapter_end, version, verse_start, verse_end
        )
        blocks[version] = VersionVerses(
            verses=rows, truncated=truncated, next_verse_id=next_verse_id
        )
    return blocks

@app.get("/api/bible/search", response_model=List[SectionResponse])
async def search_bible(
    query: str = Query(..., description="Semantic search query"),
    limit: int = Query(5, ge=1, le=20),
    version: Optional[SearchVersion] = Query(None, description="NKRV or ESV (defaults to auto-detected from query language)")
):
    try:
        # 1. Embed the user's query
        response = openai_client.embeddings.create(
            input=query,
            model="text-embedding-3-small"
        )
        query_embedding = response.data[0].embedding

        # 2. Detect version: Korean queries use NKRV, everything else uses ESV
        version_value = version.value if version else detect_version(query)

        # 3. Call the version-aware Supabase RPC function (match_bible_sections_v)
        result = supabase.rpc(
            "match_bible_sections_v",
            {
                "query_embedding": query_embedding,
                "match_threshold": 0.3, # Slightly lower threshold for broader context
                "match_count": limit,
                "version_filter": version_value
            }
        ).execute()
        
        logger.info(f"search_bible ({version_value}) response for query '{query}': {len(result.data)} results")
        rows = result.data
        for row in rows:
            row["version"] = row.get("version") or version_value
            if row["version"] == "ESV":
                row["copyright"] = ESV_COPYRIGHT
        return rows
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"search_bible error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bible/text", response_model=VersesResponse)
async def get_bible_text(
    book: str = Query(..., description="Name of the book (e.g., Genesis)"),
    chapter: int = Query(..., description="Chapter number"),
    verse_start: int = Query(..., description="Starting verse number"),
    verse_end: Optional[int] = Query(None, description="Ending verse number (inclusive)"),
    version: Optional[Version] = Query(None, description="NKRV, ESV, or all (defaults by book language)")
):
    try:
        end = verse_end if verse_end is not None else verse_start
        versions = resolve_versions(book, version)
        blocks = fetch_verses(book, chapter, chapter, versions, verse_start, end)

        if not any(block.verses for block in blocks.values()):
            logger.warning(f"get_bible_text no verses found for {book} {chapter}:{verse_start}-{end}")
            raise HTTPException(status_code=404, detail="Verses not found")

        total = sum(len(block.verses) for block in blocks.values())
        logger.info(f"get_bible_text response for '{book} {chapter}:{verse_start}-{end}': {total} verses")
        return VersesResponse(book=book, chapter_start=chapter, chapter_end=chapter, versions=blocks)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_bible_text error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bible/chapters", response_model=VersesResponse)
async def get_bible_chapters(
    book: str = Query(..., description="Name of the book (e.g., Genesis)"),
    chapter_start: int = Query(..., description="Starting chapter number"),
    chapter_end: Optional[int] = Query(None, description="Ending chapter number (inclusive)"),
    version: Optional[Version] = Query(None, description="NKRV, ESV, or all (defaults by book language)")
):
    try:
        end = chapter_end if chapter_end is not None else chapter_start
        versions = resolve_versions(book, version)
        blocks = fetch_verses(book, chapter_start, end, versions)

        if not any(block.verses for block in blocks.values()):
            logger.warning(f"get_bible_chapters no verses found for {book} chapters {chapter_start}-{end}")
            raise HTTPException(status_code=404, detail="Chapters not found")

        total = sum(len(block.verses) for block in blocks.values())
        logger.info(f"get_bible_chapters response for '{book} chapters {chapter_start}-{end}': {total} verses")
        return VersesResponse(book=book, chapter_start=chapter_start, chapter_end=end, versions=blocks)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_bible_chapters error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sermons/search", response_model=List[SermonResponse])
async def find_pastor_quotes(
    query: str = Query(..., description="Verse reference or topic to find in sermons (e.g., 'Genesis 1:1')"),
    limit: int = Query(3, ge=1, le=10)
):
    try:
        # 1. Embed the query to search against sermon chunks
        response = openai_client.embeddings.create(
            input=query,
            model="text-embedding-3-small"
        )
        query_embedding = response.data[0].embedding

        # 2. Call the Supabase RPC function (match_sermons)
        result = supabase.rpc(
            "match_sermons",
            {
                "query_embedding": query_embedding,
                "match_threshold": 0.4, # Higher threshold for sermons to ensure relevance
                "match_count": limit
            }
        ).execute()
        
        logger.info(f"find_pastor_quotes response for '{query}': {result.data}")
        return result.data
        
    except Exception as e:
        logger.error(f"find_pastor_quotes error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/stream")
async def chat_with_agent_stream(request: ChatRequest):
    """Server-Sent Events: yields {type: delta, content} chunks, then {type: done, ...}."""
    async def event_stream():
        try:
            for event in bible_agent.run_stream(request.message, request.history or []):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"chat_with_agent_stream error: {e}\n{traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)}, ensure_ascii=False)}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)