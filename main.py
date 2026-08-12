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
from typing import List, Optional, Dict, Union
from agent import BibleAgent, ChatRequest, ESV_COPYRIGHT
from books import detect_version, db_book_names

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

# Single version -> flat array; multiple versions -> { "NKRV": [...], "ESV": [...] }
VerseListResponse = Union[List[VerseResponse], Dict[str, List[VerseResponse]]]

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

def resolve_versions(book: str, version: Optional[str]) -> List[str]:
    """Resolve the version param to a list. 'all' or comma-separated returns both."""
    if version:
        normalized = version.strip().lower().replace(" ", "")
        if normalized == "all" or normalized == "nkrv,esv" or normalized == "esv,nkrv":
            return ["NKRV", "ESV"]
        return [version.upper()]
    return [detect_version(book)]

def group_by_version(rows: List[dict], versions: List[str]):
    """Flat array for a single version; {version: rows} when both are requested."""
    if len(versions) <= 1:
        return rows
    grouped = {}
    for v in versions:
        grouped[v] = [r for r in rows if r.get("version") == v]
    return grouped

@app.get("/api/bible/search", response_model=List[SectionResponse])
async def search_bible(
    query: str = Query(..., description="Semantic search query"),
    limit: int = Query(5, ge=1, le=20),
    version: Optional[str] = Query(None, description="NKRV or ESV (defaults to auto-detected from query language)")
):
    try:
        if version and version.lower().replace(" ", "") in ("all", "nkrv,esv", "esv,nkrv"):
            raise HTTPException(status_code=422, detail="Semantic search is per-version; use 'NKRV' or 'ESV'")
        # 1. Embed the user's query
        response = openai_client.embeddings.create(
            input=query,
            model="text-embedding-3-small"
        )
        query_embedding = response.data[0].embedding

        # 2. Detect version: Korean queries use NKRV, everything else uses ESV
        version = version or detect_version(query)

        # 3. Call the version-aware Supabase RPC function (match_bible_sections_v)
        result = supabase.rpc(
            "match_bible_sections_v",
            {
                "query_embedding": query_embedding,
                "match_threshold": 0.3, # Slightly lower threshold for broader context
                "match_count": limit,
                "version_filter": version
            }
        ).execute()
        
        logger.info(f"search_bible ({version}) response for query '{query}': {len(result.data)} results")
        rows = result.data
        for row in rows:
            row["version"] = row.get("version") or version
            if row["version"] == "ESV":
                row["copyright"] = ESV_COPYRIGHT
        return rows
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"search_bible error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bible/text", response_model=VerseListResponse)
async def get_bible_text(
    book: str = Query(..., description="Name of the book (e.g., Genesis)"),
    chapter: int = Query(..., description="Chapter number"),
    verse_start: int = Query(..., description="Starting verse number"),
    verse_end: Optional[int] = Query(None, description="Ending verse number (inclusive)"),
    version: Optional[str] = Query(None, description="NKRV, ESV, or both: 'all' / 'NKRV,ESV' (defaults by book language)")
):
    try:
        # Determine the end verse range
        end = verse_end if verse_end is not None else verse_start

        versions = resolve_versions(book, version)

        # Query Supabase exactly for the requested range
        result = supabase.table("bible_verses") \
            .select("id, book, chapter, verse_start, verse_end, text, version") \
            .in_("book", db_book_names(book, versions)) \
            .eq("chapter", chapter) \
            .in_("version", versions) \
            .gte("verse_start", verse_start) \
            .lte("verse_end", end) \
            .order("verse_start") \
            .order("version") \
            .execute()
            
        if not result.data:
            logger.warning(f"get_bible_text no verses found for {book} {chapter}:{verse_start}-{end}")
            raise HTTPException(status_code=404, detail="Verses not found")
            
        rows = result.data[:500]  # ESV terms: max 500 consecutive verses per response
        for row in rows:
            if row.get("version") == "ESV":
                row["copyright"] = ESV_COPYRIGHT
        logger.info(f"get_bible_text response for '{book} {chapter}:{verse_start}-{end}': {len(rows)} verses")
        return group_by_version(rows, versions)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_bible_text error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bible/chapters", response_model=VerseListResponse)
async def get_bible_chapters(
    book: str = Query(..., description="Name of the book (e.g., Genesis)"),
    chapter_start: int = Query(..., description="Starting chapter number"),
    chapter_end: Optional[int] = Query(None, description="Ending chapter number (inclusive)"),
    version: Optional[str] = Query(None, description="NKRV, ESV, or both: 'all' / 'NKRV,ESV' (defaults by book language)")
):
    try:
        # Determine the end chapter range
        end = chapter_end if chapter_end is not None else chapter_start

        versions = resolve_versions(book, version)

        # Query Supabase for the requested chapter range
        result = supabase.table("bible_verses") \
            .select("id, book, chapter, verse_start, verse_end, text, version") \
            .in_("book", db_book_names(book, versions)) \
            .in_("version", versions) \
            .gte("chapter", chapter_start) \
            .lte("chapter", end) \
            .order("chapter") \
            .order("verse_start") \
            .order("version") \
            .execute()
            
        if not result.data:
            logger.warning(f"get_bible_chapters no verses found for {book} chapters {chapter_start}-{end}")
            raise HTTPException(status_code=404, detail="Chapters not found")
            
        rows = result.data[:500]  # ESV terms: max 500 consecutive verses per response
        for row in rows:
            if row.get("version") == "ESV":
                row["copyright"] = ESV_COPYRIGHT
        logger.info(f"get_bible_chapters response for '{book} chapters {chapter_start}-{end}': {len(rows)} verses")
        return group_by_version(rows, versions)
        
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