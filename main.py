from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import time
import logging
from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI
from typing import List, Optional

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("api_logger")

# Load environment variables
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase credentials not found in .env")
if not OPENAI_API_KEY:
    raise ValueError("OpenAI API key not found in .env")

# Initialize clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI(title="Logos Mind API")

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

class SermonResponse(BaseModel):
    id: str
    title: Optional[str] = None
    date: Optional[str] = None
    speaker: Optional[str] = None
    chunk_text: str
    similarity: Optional[float] = None

@app.get("/api/bible/search", response_model=List[VerseResponse])
async def search_bible(
    query: str = Query(..., description="Semantic search query"),
    limit: int = Query(5, ge=1, le=20)
):
    try:
        # 1. Embed the user's query
        response = openai_client.embeddings.create(
            input=query,
            model="text-embedding-3-small"
        )
        query_embedding = response.data[0].embedding

        # 2. Call the Supabase RPC function (match_bible_verses)
        # Using a conservative threshold of 0.4 for similarity (1 - distance)
        result = supabase.rpc(
            "match_bible_verses",
            {
                "query_embedding": query_embedding,
                "match_threshold": 0.4,
                "match_count": limit
            }
        ).execute()
        
        logger.info(f"search_bible response for query '{query}': {result.data}")
        return result.data
        
    except Exception as e:
        logger.error(f"search_bible error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bible/text", response_model=List[VerseResponse])
async def get_bible_text(
    book: str = Query(..., description="Name of the book (e.g., 창세기)"),
    chapter: int = Query(..., description="Chapter number"),
    verse_start: int = Query(..., description="Starting verse number"),
    verse_end: Optional[int] = Query(None, description="Ending verse number (inclusive)")
):
    try:
        # Determine the end verse range
        end = verse_end if verse_end is not None else verse_start
        
        # Query Supabase exactly for the requested range
        result = supabase.table("bible_verses") \
            .select("id, book, chapter, verse_start, verse_end, text") \
            .eq("book", book) \
            .eq("chapter", chapter) \
            .gte("verse_start", verse_start) \
            .lte("verse_end", end) \
            .order("verse_start") \
            .execute()
            
        if not result.data:
            logger.warning(f"get_bible_text no verses found for {book} {chapter}:{verse_start}-{end}")
            raise HTTPException(status_code=404, detail="Verses not found")
            
        logger.info(f"get_bible_text response for '{book} {chapter}:{verse_start}-{end}': {result.data}")
        return result.data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_bible_text error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bible/chapters", response_model=List[VerseResponse])
async def get_bible_chapters(
    book: str = Query(..., description="Name of the book (e.g., 창세기)"),
    chapter_start: int = Query(..., description="Starting chapter number"),
    chapter_end: Optional[int] = Query(None, description="Ending chapter number (inclusive)")
):
    try:
        # Determine the end chapter range
        end = chapter_end if chapter_end is not None else chapter_start
        
        # Query Supabase for the requested chapter range
        result = supabase.table("bible_verses") \
            .select("id, book, chapter, verse_start, verse_end, text") \
            .eq("book", book) \
            .gte("chapter", chapter_start) \
            .lte("chapter", end) \
            .order("chapter") \
            .order("verse_start") \
            .execute()
            
        if not result.data:
            logger.warning(f"get_bible_chapters no verses found for {book} chapters {chapter_start}-{end}")
            raise HTTPException(status_code=404, detail="Chapters not found")
            
        logger.info(f"get_bible_chapters response for '{book} chapters {chapter_start}-{end}': {len(result.data)} verses")
        return result.data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_bible_chapters error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sermons/search", response_model=List[SermonResponse])
async def find_pastor_quotes(
    query: str = Query(..., description="Verse reference or topic to find in sermons (e.g., '창세기 1:1')"),
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

@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)