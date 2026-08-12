import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: Supabase credentials not found in .env")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def check_db():
    print("--- Database Status Check ---")
    
    # 1. Count total verses
    try:
        count_res = supabase.table("bible_verses").select("id", count="exact").execute()
        total_count = count_res.count
        print(f"Total verses in 'bible_verses' table: {total_count}")
    except Exception as e:
        print(f"Error counting verses: {e}")
        return

    # 2. Check a few samples to verify version (NKRV)
    try:
        sample_res = supabase.table("bible_verses").select("book, chapter, verse_start, text").limit(3).execute()
        print("\nSample Verses:")
        for row in sample_res.data:
            print(f"[{row['book']} {row['chapter']}:{row['verse_start']}] {row['text']}")
    except Exception as e:
        print(f"Error fetching samples: {e}")

    # 3. Check for embedding existence - Fetch one row and check the column
    try:
        row_with_emb = supabase.table("bible_verses").select("book, chapter, verse_start, embedding").limit(1).execute()
        if row_with_emb.data and "embedding" in row_with_emb.data[0]:
            emb = row_with_emb.data[0]["embedding"]
            if emb:
                # If it's a string (Postgres vector format), print first part
                emb_str = str(emb)
                print(f"\nEmbedding found for {row_with_emb.data[0]['book']} {row_with_emb.data[0]['chapter']}:{row_with_emb.data[0]['verse_start']}")
                print(f"Embedding snippet: {emb_str[:50]}...")
            else:
                print("\nEmbedding field exists but is NULL for this row.")
        else:
            print("\nEmbedding field NOT found in the row data.")
    except Exception as e:
        print(f"Error checking embeddings: {e}")

    # 4. Test semantic search (RPC call)
    print("\n--- Testing Semantic Search (RPC: match_bible_verses) ---")
    try:
        # Dummy query embedding (1536 dims for text-embedding-3-small)
        dummy_embedding = [0.0] * 1536
        search_res = supabase.rpc(
            "match_bible_verses",
            {
                "query_embedding": dummy_embedding,
                "match_threshold": 0.0, # Just to see if it returns anything
                "match_count": 1
            }
        ).execute()
        print(f"RPC 'match_bible_verses' call successful. Result count: {len(search_res.data)}")
        if search_res.data:
            print(f"Top result: {search_res.data[0].get('book')} {search_res.data[0].get('chapter')}:{search_res.data[0].get('verse_start')}")
    except Exception as e:
        print(f"RPC 'match_bible_verses' failed: {e}")
        print("Tip: If this failed, the HNSW index or the RPC function might not be set up correctly in Supabase.")

if __name__ == "__main__":
    check_db()
