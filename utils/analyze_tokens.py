import os
import tiktoken
from supabase import create_client, Client
from dotenv import load_dotenv
import csv
from collections import defaultdict

# Load environment variables
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase credentials not found in .env")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Initialize tokenizer for text-embedding-3-small
enc = tiktoken.get_encoding("cl100k_base")

def get_bible_chapters_tokens():
    print("Fetching verses from Supabase...")
    
    all_verses = []
    page_size = 1000  # Smaller page size to avoid timeouts
    offset = 0
    
    while True:
        try:
            # We don't need all fields, just these 3
            result = supabase.table("bible_verses") \
                .select("book, chapter, text") \
                .order("book", desc=False) \
                .order("chapter", desc=False) \
                .order("verse_start", desc=False) \
                .range(offset, offset + page_size - 1) \
                .execute()
            
            if not result.data:
                break
                
            all_verses.extend(result.data)
            print(f"Fetched {len(all_verses)} verses so far...")
            
            if len(result.data) < page_size:
                break
                
            offset += page_size
        except Exception as e:
            print(f"Error fetching data at offset {offset}: {e}")
            # If it's a timeout, maybe try again once with even smaller page size
            if "timeout" in str(e).lower():
                 print("Retrying with smaller page size...")
                 page_size = 500
                 continue
            break

    if not all_verses:
        print("No verses found.")
        return

    # Group text by Book and Chapter
    chapters_text = defaultdict(lambda: defaultdict(str))
    
    book_order = []
    seen_books = set()

    for verse in all_verses:
        book = verse['book']
        chapter = verse['chapter']
        text = verse['text']
        
        if book not in seen_books:
            book_order.append(book)
            seen_books.add(book)
            
        if chapters_text[book][chapter]:
            chapters_text[book][chapter] += " "
        chapters_text[book][chapter] += text

    # Prepare CSV data
    csv_data = []
    total_tokens = 0
    
    for book in book_order:
        sorted_chapters = sorted(chapters_text[book].keys())
        for chapter in sorted_chapters:
            text = chapters_text[book][chapter]
            tokens = len(enc.encode(text))
            total_tokens += tokens
            csv_data.append({
                "book": book,
                "chapter": chapter,
                "token_count": tokens
            })

    output_file = "bible_chapter_tokens.csv"
    with open(output_file, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["book", "chapter", "token_count"])
        writer.writeheader()
        writer.writerows(csv_data)
        
    print(f"\nDone! Results saved to {output_file}")
    print(f"Total tokens across the Bible: {total_tokens}")

if __name__ == "__main__":
    get_bible_chapters_tokens()
