import os
import sys
import json
import time
from supabase import create_client, Client
from openai import OpenAI
from dotenv import load_dotenv
import logging
from typing import List, Dict

# Shared book mapping (single source of truth)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from books import KO_TO_EN, ko_to_en

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("chunker")

# Load environment variables
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

EMBEDDING_MODEL = "text-embedding-3-small"
BATCH_SIZE = 50

def get_embeddings(texts: List[str]) -> List[List[float]]:
    try:
        response = openai_client.embeddings.create(input=texts, model=EMBEDDING_MODEL)
        return [data.embedding for data in response.data]
    except Exception as e:
        logger.error(f"Error fetching embeddings: {e}")
        return []

def upload_to_db(data: List[Dict]):
    if not data: return
    try:
        supabase.table("bible_sections").insert(data).execute()
    except Exception as e:
        logger.error(f"Error uploading to DB: {e}")

def apply_chunking_strategy():
    with open("pericope_map.json", "r", encoding="utf-8") as f:
        pericope_map = json.load(f)

    db_books = ['나훔', '룻기', '미가', '시편', '아가', '요나', '요엘', '욥기', '잠언', '학개', '다니엘', '디도 서', '레위기', '로마서', '말라기', '민수기', '사사기', '스가랴', '스바냐', '신명기', '아모스', ' 에스겔', '에스더', '에스라', '역대상', '역대하', '오바댜', '유다서', '이사야', '전도서', '창세기', '하박국', '호세아', '골로새서', '누가복음', '느헤미야', '마가복음', '마태복음', '빌레몬서', '빌립보서', '사도행전', '사무엘상', '사무엘하', '야고보서', '에베소서', '여호수아', '열왕기상', '열 왕기하', '예레미야', '요한복음', '요한삼서', '요한이서', '요한일서', '출애굽기', '히브리서', '갈 라디아서', '고린도전서', '고린도후서', '디모데전서', '디모데후서', '베드로전서', '베드로후서', ' 요한계시록', '예레미야애가', '데살로니가전서', '데살로니가후서']

    all_chunks_to_process = []

    for actual_db_book in db_books:
        eng_key = ko_to_en(actual_db_book)

        if not eng_key: continue
        pericopes_by_chapter = pericope_map.get(eng_key, {})
        logger.info(f"Preparing: {actual_db_book}")

        res = supabase.table("bible_verses").select("chapter, verse_start, text").eq("book", actual_db_book).execute()
        if not res.data: continue

        book_data = {}
        for r in res.data:
            ch = str(r['chapter'])
            if ch not in book_data: book_data[ch] = {}
            book_data[ch][r['verse_start']] = r['text']

        for ch_num, verses in book_data.items():
            pericopes = pericopes_by_chapter.get(ch_num, [])
            v_nums = sorted(verses.keys())
            if not v_nums: continue
            max_v = max(v_nums)
            
            if not pericopes:
                text = " ".join([verses[v] for v in v_nums])
                all_chunks_to_process.append({
                    "book": actual_db_book.strip(), "chapter": int(ch_num), "verse_range": f"1-{max_v}",
                    "title": f"{actual_db_book.strip()} {ch_num}장", "content": text,
                    "embedding_text": f"[{actual_db_book.strip()} {ch_num}:1-{max_v}] {text}"
                })
            else:
                for idx, p in enumerate(pericopes):
                    start = p['start']
                    title = p['title']
                    end = pericopes[idx+1]['start'] - 1 if idx + 1 < len(pericopes) else max_v
                    current_verses = [verses[v] for v in range(start, end + 1) if v in verses]
                    if current_verses:
                        content_text = " ".join(current_verses)
                        all_chunks_to_process.append({
                            "book": actual_db_book.strip(), "chapter": int(ch_num), "verse_range": f"{start}-{end}",
                            "title": title, "content": content_text,
                            "embedding_text": f"[{actual_db_book.strip()} {ch_num}:{start}-{end}] {title} - {content_text}"
                        })

    logger.info(f"Total chunks to process: {len(all_chunks_to_process)}")
    for i in range(0, len(all_chunks_to_process), BATCH_SIZE):
        batch = all_chunks_to_process[i:i + BATCH_SIZE]
        texts = [b["embedding_text"] for b in batch]
        logger.info(f"Embedding and uploading batch {i//BATCH_SIZE + 1}...")
        embeddings = get_embeddings(texts)
        if len(embeddings) == len(batch):
            upload_data = []
            for j, chunk in enumerate(batch):
                upload_data.append({
                    "book": chunk["book"], "chapter": chunk["chapter"], "verse_range": chunk["verse_range"],
                    "title": chunk["title"], "content": chunk["content"], "embedding": embeddings[j]
                })
            upload_to_db(upload_data)
        time.sleep(0.1)
    logger.info("Done! Bible sections fully updated.")

if __name__ == "__main__":
    apply_chunking_strategy()
