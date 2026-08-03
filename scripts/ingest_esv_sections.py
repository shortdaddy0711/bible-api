import os
import json
import time
import requests
import logging
from typing import List, Dict
from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("esv_section_ingester")

# Load environment variables
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Assuming the local API is running
API_BASE_URL = "http://localhost:8080/api/bible"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
EMBEDDING_MODEL = "text-embedding-3-small"

def get_embeddings(texts: List[str]) -> List[List[float]]:
    try:
        response = openai_client.embeddings.create(input=texts, model=EMBEDDING_MODEL)
        return [data.embedding for data in response.data]
    except Exception as e:
        logger.error(f"Error fetching embeddings: {e}")
        return []

def fetch_chapter_verses_from_api(book: str, chapter: int, version: str = "ESV") -> List[Dict]:
    url = f"{API_BASE_URL}/chapters"
    params = {"book": book, "chapter_start": chapter, "chapter_end": chapter, "version": version}
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(f"Failed to fetch {book} {chapter} ({version}): {response.status_code}")
            return []
    except Exception as e:
        logger.error(f"API Error fetching {book} {chapter}: {e}")
        return []

def ingest_esv_sections():
    # Load the pericope map
    try:
        with open("../pericope_map.json", "r", encoding="utf-8") as f:
            pericope_map = json.load(f)
    except FileNotFoundError:
        logger.error("pericope_map.json not found in backend/")
        return

    total_books = len(pericope_map)
    logger.info(f"Starting ESV section ingestion for {total_books} books...")

    for book, chapters in pericope_map.items():
        logger.info(f"Processing book: {book}")
        
        for ch_num, pericopes in chapters.items():
            chapter = int(ch_num)
            
            # 1. Fetch verses via the Backend API
            verses = fetch_chapter_verses_from_api(book, chapter, version="ESV")
            if not verses:
                continue
                
            # Create a lookup dictionary by verse start number
            verse_dict = {v["verse_start"]: v for v in verses}
            max_v = max(verse_dict.keys()) if verse_dict else 0

            for idx, p in enumerate(pericopes):
                start = p["start"]
                title = p["title"]
                end = pericopes[idx+1]["start"] - 1 if idx + 1 < len(pericopes) else max_v
                
                # Collect verses for this pericope
                current_verses = [verse_dict[v] for v in range(start, end + 1) if v in verse_dict]
                verse_ids_to_update = [v["id"] for v in current_verses]
                
                if not current_verses:
                    continue

                content_text = " ".join([v["text"] for v in current_verses])
                embedding_text = f"[{book} {chapter}:{start}-{end}] {title} - {content_text}"
                
                # 2. Insert into bible_sections to get the section_id
                try:
                    section_data = {
                        "book": book,
                        "chapter": chapter,
                        "verse_range": f"{start}-{end}",
                        "title": title,
                        "version": "ESV",
                        # We temporarily leave embedding out, or do it immediately if we prefer
                    }
                    
                    res = supabase.table("bible_sections").insert(section_data).execute()
                    if not res.data:
                        logger.error(f"Failed to insert section: {book} {chapter}:{start}-{end}")
                        continue
                        
                    section_id = res.data[0]["id"]
                    
                    # 3. Relational Link: Update the verses to point to the new section_id
                    if verse_ids_to_update:
                        supabase.table("bible_verses") \
                            .update({"section_id": section_id}) \
                            .in_("id", verse_ids_to_update) \
                            .execute()
                    
                    # 4. Generate Embedding and Update Section
                    emb = get_embeddings([embedding_text])
                    if emb:
                        supabase.table("bible_sections") \
                            .update({"embedding": emb[0]}) \
                            .eq("id", section_id) \
                            .execute()
                            
                    logger.info(f"Processed section: {book} {chapter}:{start}-{end} ({title})")
                    
                except Exception as e:
                    logger.error(f"Error processing section {book} {chapter}:{start}-{end} -> {e}")
            
            # Sleep briefly to avoid rate limits
            time.sleep(0.1)

    logger.info("ESV section ingestion completed.")

if __name__ == "__main__":
    ingest_esv_sections()
